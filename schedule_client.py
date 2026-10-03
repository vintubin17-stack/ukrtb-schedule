# -*- coding: utf-8 -*-
"""Клиент расписания учебного портала УКРТБ (study.ukrtb.ru).

Модуль отвечает за:

* обращение к публичному JSON API портала (``/api/schedules``);
* приведение ответа к виду, удобному для фронтенда;
* разрешение «человеческого» имени группы (например, ``КСК-40``) в точное
  название из списка групп портала;
* двухуровневое кэширование (память + диск) и работу с демо-данными,
  когда источник недоступен.

Модуль можно использовать как самостоятельный CLI для проверки парсинга::

    python schedule_client.py --group КСК-40 --days 3
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import re
import sys
import threading
import time
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any, Iterable

import requests

LOGGER = logging.getLogger("ukrtb.schedule")

# --- Настройки, которые можно переопределить переменными окружения ---------

BASE_URL = os.getenv("UKRTB_BASE_URL", "https://study.ukrtb.ru/api").rstrip("/")

# Публичный ключ портала: он опубликован самим колледжем в postman-коллекции
# (https://study.ukrtb.ru/postman_collection.json) и не является секретом.
API_KEY = os.getenv("UKRTB_API_KEY", "26c6156f5f342530e852ad496ee80201")

DEFAULT_GROUP = os.getenv("UKRTB_GROUP", "КСК-40-23")
DEFAULT_DAYS = 3
MAX_DAYS = 14

CACHE_TTL = float(os.getenv("UKRTB_CACHE_TTL", "600"))          # расписание, сек
GROUPS_CACHE_TTL = float(os.getenv("UKRTB_GROUPS_CACHE_TTL", "43200"))  # группы, сек
RANGE_CACHE_TTL = float(os.getenv("UKRTB_RANGE_CACHE_TTL", "21600"))    # границы, сек

# Минимальная пауза между принудительными обновлениями одной группы.
# Кнопка «Обновить расписание» бьёт напрямую в портал колледжа, поэтому при
# публичном доступе её нужно ограничивать. 0 — без ограничения.
REFRESH_COOLDOWN = float(os.getenv("UKRTB_REFRESH_COOLDOWN", "30"))

REQUEST_TIMEOUT = float(os.getenv("UKRTB_TIMEOUT", "15"))
REQUEST_ATTEMPTS = int(os.getenv("UKRTB_ATTEMPTS", "3"))

# «Предохранитель»: если портал не ответил, следующие запросы в течение
# этого времени не пытаются идти в сеть, а сразу берут кэш или демо-данные.
# Без него окно из 7 дней в недоступной сети висело бы минутами:
# 7 дней × 3 попытки × 15 секунд.
SOURCE_BREAK_SECONDS = float(os.getenv("UKRTB_SOURCE_BREAK", "90"))

VERIFY_TLS = os.getenv("UKRTB_VERIFY_TLS", "1") not in {"0", "false", "False"}

PROJECT_ROOT = Path(__file__).resolve().parent
CACHE_DIR = Path(os.getenv("UKRTB_CACHE_DIR", PROJECT_ROOT / "data" / "cache"))
SAMPLE_FILE = PROJECT_ROOT / "data" / "sample_schedule.json"

WEEKDAYS = [
    "Понедельник", "Вторник", "Среда", "Четверг",
    "Пятница", "Суббота", "Воскресенье",
]
WEEKDAYS_SHORT = ["Пн", "Вт", "Ср", "Чт", "Пт", "Сб", "Вс"]

SOURCE_LIVE = "live"
SOURCE_CACHE = "cache"
SOURCE_SAMPLE = "sample"
SOURCE_ERROR = "error"


# --- Исключения ------------------------------------------------------------


class ScheduleError(Exception):
    """Базовая ошибка модуля."""


class ScheduleSourceError(ScheduleError):
    """Источник (портал УКРТБ) недоступен или вернул ошибку."""


class GroupNotFoundError(ScheduleError):
    """Группа не найдена в списке групп портала."""

    def __init__(self, query: str, suggestions: Iterable[str] = ()) -> None:
        self.query = query
        self.suggestions = list(suggestions)[:8]
        message = f"Группа «{query}» не найдена в расписании портала."
        if self.suggestions:
            message += " Похожие группы: " + ", ".join(self.suggestions) + "."
        super().__init__(message)


# --- Вспомогательные функции ----------------------------------------------


def _today() -> date:
    """Сегодняшняя дата (вынесено в функцию, чтобы легко тестировать)."""
    return date.today()


def _clean(value: Any) -> str:
    """Убирает лишние пробелы и неразрывные пробелы из строки."""
    if value is None:
        return ""
    text = str(value).replace("\xa0", " ")
    return re.sub(r"\s+", " ", text).strip()


def _fio(teacher: dict[str, Any]) -> str:
    """Собирает ФИО преподавателя из отдельных полей."""
    full = _clean(teacher.get("fullName"))
    if full:
        return full
    parts = [teacher.get("surname"), teacher.get("name"), teacher.get("patronymic")]
    return _clean(" ".join(_clean(p) for p in parts if p))


def _short_fio(full_name: str) -> str:
    """«Плотникова Виктория Константиновна» -> «Плотникова В. К.»."""
    parts = full_name.split()
    if len(parts) < 2:
        return full_name
    initials = " ".join(f"{p[0]}." for p in parts[1:] if p)
    return f"{parts[0]} {initials}"


def _safe_slug(value: str) -> str:
    """Превращает название группы в безопасное имя файла кэша."""
    slug = re.sub(r"[^\w\-.]+", "_", value, flags=re.UNICODE).strip("_")
    return slug or "group"


def parse_iso_date(value: Any) -> date | None:
    """Разбирает дату ``ГГГГ-ММ-ДД``. Возвращает ``None``, если формат неверный."""
    text = _clean(value)
    if not text:
        return None
    match = re.match(r"^(\d{4})-(\d{2})-(\d{2})$", text)
    if not match:
        return None
    try:
        return date(int(match.group(1)), int(match.group(2)), int(match.group(3)))
    except ValueError:
        return None


def _human_date(value: Any) -> str:
    """``2026-10-10`` -> ``10.10.2026`` (для сообщений пользователю)."""
    parsed = parse_iso_date(value)
    return parsed.strftime("%d.%m.%Y") if parsed else _clean(value)


def _fmt_time(raw: Any) -> str:
    """«9:5» -> «09:05» (портал отдаёт время в формате HH:MM)."""
    text = _clean(raw)
    match = re.match(r"^(\d{1,2}):(\d{2})", text)
    if not match:
        return text
    return f"{int(match.group(1)):02d}:{match.group(2)}"


class ScheduleClient:
    """Клиент API расписания с кэшированием и деградацией до демо-данных."""

    def __init__(
        self,
        base_url: str = BASE_URL,
        api_key: str = API_KEY,
        cache_dir: Path = CACHE_DIR,
        cache_ttl: float = CACHE_TTL,
        groups_cache_ttl: float = GROUPS_CACHE_TTL,
        timeout: float = REQUEST_TIMEOUT,
        attempts: int = REQUEST_ATTEMPTS,
        refresh_cooldown: float = REFRESH_COOLDOWN,
        sample_file: Path = SAMPLE_FILE,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.api_key = api_key
        self.cache_dir = Path(cache_dir)
        self.cache_ttl = cache_ttl
        self.groups_cache_ttl = groups_cache_ttl
        self.timeout = timeout
        self.attempts = max(1, attempts)
        self.refresh_cooldown = max(0.0, refresh_cooldown)
        self.sample_file = Path(sample_file)

        self._lock = threading.Lock()
        self._memory: dict[str, tuple[float, Any]] = {}
        self._sample_cache: dict[str, Any] | None = None

        # Замки на каждый ключ запроса (single-flight) и время последнего
        # принудительного обновления по группам.
        self._key_locks: dict[str, threading.Lock] = {}
        self._key_locks_guard = threading.Lock()
        self._last_forced: dict[str, float] = {}
        self._source_down_until = 0.0

        self._session = requests.Session()
        self._session.headers.update({
            "apikey": self.api_key,
            "Accept": "application/json",
            "User-Agent": "ukrtb-schedule-viewer/1.0 (+local)",
        })

        try:
            self.cache_dir.mkdir(parents=True, exist_ok=True)
        except OSError as exc:  # pragma: no cover - зависит от прав на ФС
            LOGGER.warning("Не удалось создать каталог кэша %s: %s", self.cache_dir, exc)

    # -- низкий уровень: HTTP ---------------------------------------------

    def _request(self, path: str, params: dict[str, Any] | None = None) -> Any:
        """GET-запрос к API с повторами. Возвращает распарсенный JSON или None.

        ``None`` означает, что у портала нет данных (HTTP 204).
        """
        url = f"{self.base_url}/{path.lstrip('/')}"
        last_error: Exception | None = None

        for attempt in range(1, self.attempts + 1):
            try:
                response = self._session.get(
                    url,
                    params=params,
                    timeout=self.timeout,
                    verify=VERIFY_TLS,
                )
            except requests.RequestException as exc:
                last_error = exc
                LOGGER.warning(
                    "Попытка %s/%s к %s не удалась: %s", attempt, self.attempts, url, exc
                )
            else:
                if response.status_code == 204:
                    return None
                if response.status_code == 200:
                    try:
                        payload = response.json()
                    except ValueError as exc:
                        raise ScheduleSourceError(
                            "Портал вернул ответ, который не удалось разобрать как JSON."
                        ) from exc
                    if isinstance(payload, dict) and payload.get("success") is False:
                        raise ScheduleSourceError(
                            _clean(payload.get("message")) or "Портал отклонил запрос."
                        )
                    return payload

                if 400 <= response.status_code < 500 and response.status_code != 429:
                    raise ScheduleSourceError(
                        f"Портал вернул ошибку {response.status_code} для {url}."
                    )
                last_error = ScheduleSourceError(
                    f"Портал вернул ошибку {response.status_code} для {url}."
                )
                LOGGER.warning("Попытка %s/%s: HTTP %s", attempt, self.attempts, response.status_code)

            if attempt < self.attempts:
                time.sleep(0.5 * 2 ** (attempt - 1))

        raise ScheduleSourceError(
            f"Не удалось получить данные с портала УКРТБ ({url}): {last_error}"
        )

    # -- низкий уровень: кэш ----------------------------------------------

    def _cache_file(self, name: str) -> Path:
        return self.cache_dir / f"{name}.json"

    def source_is_down(self) -> bool:
        """True, если недавно была сетевая ошибка и портал считается недоступным."""
        return time.time() < self._source_down_until

    def _mark_source_down(self, seconds: float | None = None) -> None:
        """Включает «предохранитель», чтобы не долбить недоступный портал."""
        pause = SOURCE_BREAK_SECONDS if seconds is None else seconds
        self._source_down_until = time.time() + max(0.0, pause)

    def _key_lock(self, key: str) -> threading.Lock:
        """Отдельный замок на каждый ключ запроса (single-flight)."""
        with self._key_locks_guard:
            lock = self._key_locks.get(key)
            if lock is None:
                lock = threading.Lock()
                self._key_locks[key] = lock
            return lock

    def allow_forced_refresh(self, group: str) -> bool:
        """Разрешает принудительное обновление не чаще, чем раз в cooldown.

        Кнопка «Обновить расписание» обращается к порталу колледжа напрямую.
        При публичном доступе без такого ограничения поток посетителей
        превратился бы в нагрузку на чужой сервер.
        """
        if self.refresh_cooldown <= 0:
            return True
        now = time.time()
        with self._key_locks_guard:
            last = self._last_forced.get(group, 0.0)
            if now - last < self.refresh_cooldown:
                return False
            self._last_forced[group] = now
            return True

    def _cache_read(self, name: str, ttl: float) -> tuple[Any, bool]:
        """Читает запись кэша. Возвращает ``(payload, is_fresh)``."""
        with self._lock:
            entry = self._memory.get(name)
        if entry is not None:
            stored_at, payload = entry
            if ttl <= 0 or time.time() - stored_at <= ttl:
                return payload, True

        path = self._cache_file(name)
        try:
            raw = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return None, False

        payload = raw.get("payload")
        stored_at = float(raw.get("stored_at") or 0)
        fresh = ttl <= 0 or (time.time() - stored_at) <= ttl
        if payload is not None:
            with self._lock:
                self._memory[name] = (stored_at, payload)
        return payload, fresh

    def _cache_write(self, name: str, payload: Any) -> None:
        now = time.time()
        with self._lock:
            self._memory[name] = (now, payload)
        path = self._cache_file(name)
        try:
            tmp = path.with_suffix(".tmp")
            tmp.write_text(
                json.dumps({"stored_at": now, "payload": payload}, ensure_ascii=False),
                encoding="utf-8",
            )
            tmp.replace(path)
        except OSError as exc:
            LOGGER.warning("Не удалось записать кэш %s: %s", path, exc)

    # -- границы опубликованного расписания ---------------------------------

    def get_published_range(self, force: bool = False) -> dict[str, Any] | None:
        """Период, за который портал вообще публикует расписание.

        Возвращает ``{"min": "2023-09-02", "max": "2026-10-10"}`` или ``None``,
        если границы узнать не удалось. Ответ кэшируется на 6 часов: границы
        меняются редко, а запрос нужен для подсказок в интерфейсе.
        """
        if not force:
            cached, fresh = self._cache_read("published_range", RANGE_CACHE_TTL)
            if cached and fresh:
                return cached

        if self.source_is_down():
            cached, _ = self._cache_read("published_range", 0)
            return cached

        try:
            payload = self._request("/frontend/schedule/get/border/date")
        except ScheduleSourceError as exc:
            LOGGER.warning("Не удалось получить границы расписания: %s", exc)
            self._mark_source_down()
            cached, _ = self._cache_read("published_range", 0)
            return cached

        data = payload or {}
        result = {
            "min": _clean(data.get("min")),
            "max": _clean(data.get("max")),
        }
        result["min_label"] = _human_date(result["min"])
        result["max_label"] = _human_date(result["max"])
        if not result["min"] and not result["max"]:
            return None

        self._cache_write("published_range", result)
        return result

    # -- группы -------------------------------------------------------------

    def get_groups(self, force: bool = False) -> list[dict[str, Any]]:
        """Список учебных групп портала (с суточным кэшем)."""
        if not force:
            cached, fresh = self._cache_read("groups", self.groups_cache_ttl)
            if cached and fresh:
                return cached

        if self.source_is_down():
            cached, _ = self._cache_read("groups", 0)
            if cached:
                return cached
            raise ScheduleSourceError("Портал временно помечен недоступным.")

        try:
            payload = self._request("/schedules/groups")
        except ScheduleSourceError:
            self._mark_source_down()
            cached, _ = self._cache_read("groups", 0)
            if cached:
                LOGGER.warning("Список групп взят из кэша: портал недоступен.")
                return cached
            raise

        groups = (payload or {}).get("data") or []
        if not isinstance(groups, list):
            raise ScheduleSourceError("Неожиданный формат списка групп.")
        self._cache_write("groups", groups)
        return groups

    def resolve_group(self, query: str) -> str:
        """Находит точное название группы по свободному запросу.

        ``КСК-40`` -> ``КСК-40-23``. Сначала ищется точное совпадение, затем
        совпадение по началу строки, затем по вхождению подстроки.

        Если список групп получить не удалось (портал недоступен и кэша нет),
        возвращает запрос как есть: проверка названия — не повод не показать
        сохранённые или демонстрационные данные.
        """
        query = _clean(query)
        if not query:
            raise GroupNotFoundError(query)

        try:
            titles = [_clean(g.get("title")) for g in self.get_groups()]
        except ScheduleSourceError as exc:
            LOGGER.warning(
                "Список групп недоступен, использую название «%s» без проверки: %s",
                query, exc,
            )
            return query

        titles = [t for t in titles if t]
        needle = query.casefold()

        exact = [t for t in titles if t.casefold() == needle]
        if exact:
            return exact[0]

        prefixed = sorted(
            (t for t in titles if t.casefold().startswith(needle)),
            key=lambda t: (len(t), t),
        )
        if prefixed:
            return prefixed[0]

        contained = sorted(
            (t for t in titles if needle in t.casefold()),
            key=lambda t: (len(t), t),
        )
        if contained:
            return contained[0]

        # Ничего не нашли — предложим варианты по первому «слову» запроса.
        head = re.split(r"[-–\s]", needle, maxsplit=1)[0]
        suggestions = [t for t in titles if head and t.casefold().startswith(head)]
        if not suggestions:
            # Совсем не похоже — лучше не подсказывать, чем подсказывать неверное.
            suggestions = [t for t in titles if head and head in t.casefold()]
        raise GroupNotFoundError(query, suggestions)

    # -- расписание ---------------------------------------------------------

    def _fetch_day(self, group: str, day: date) -> list[dict[str, Any]] | None:
        """Сырой список пар на дату (``None`` — портал ответил «нет данных»)."""
        payload = self._request(
            "/schedules",
            {"date": day.isoformat(), "group": group},
        )
        if payload is None:
            return None
        data = payload.get("data")
        if data is None:
            return None
        if isinstance(data, list):  # на всякий случай: плоский список
            return data
        return data.get("schedules") or []

    def _day_cache_name(self, group: str, day: date) -> str:
        return f"day__{_safe_slug(group)}__{day.isoformat()}"

    def get_day(self, group: str, day: date, force: bool = False) -> dict[str, Any]:
        """Расписание на один день в нормализованном виде."""
        today = _today()
        cache_name = self._day_cache_name(group, day)

        if not force:
            cached, fresh = self._cache_read(cache_name, self.cache_ttl)
            if cached is not None and fresh:
                return self._build_day(group, day, cached.get("lessons") or [],
                                       SOURCE_CACHE, today, cached.get("note", ""))

        # За одним и тем же днём в сеть идёт ровно один поток. Остальные
        # дожидаются его и забирают готовый результат из кэша: при публичном
        # доступе это не даёт трафику превратиться в лавину запросов к
        # порталу колледжа (thundering herd).
        with self._key_lock(f"day:{group}:{day.isoformat()}"):
            if not force:
                cached, fresh = self._cache_read(cache_name, self.cache_ttl)
                if cached is not None and fresh:
                    return self._build_day(group, day, cached.get("lessons") or [],
                                           SOURCE_CACHE, today, cached.get("note", ""))
            return self._load_day(group, day, cache_name, today)

    def _load_day(self, group: str, day: date, cache_name: str,
                  today: date) -> dict[str, Any]:
        """Тянет день из сети; при сбое — кэш, затем демо-данные."""
        if self.source_is_down():
            # Предохранитель сработал: в сеть не идём, отдаём что есть.
            return self._fallback_day(
                group, day, cache_name, today,
                ScheduleSourceError("Портал временно помечен недоступным."),
            )

        try:
            raw_lessons = self._fetch_day(group, day)
            lessons = [self._normalise_lesson(item) for item in (raw_lessons or [])]
            lessons.sort(key=lambda item: (item["number"] or 99, item["start"] or "99:99"))
            self._cache_write(cache_name, {"lessons": lessons})
        except ScheduleSourceError as exc:
            self._mark_source_down()
            return self._fallback_day(group, day, cache_name, today, exc)

        return self._build_day(group, day, lessons, SOURCE_LIVE, today, "")

    def _fallback_day(self, group: str, day: date, cache_name: str, today: date,
                      exc: Exception) -> dict[str, Any]:
        """Кэш, затем демо-данные — когда портал недоступен."""
        cached, _ = self._cache_read(cache_name, 0)
        if cached is not None:
            LOGGER.warning("День %s взят из кэша: %s", day, exc)
            return self._build_day(
                group, day, cached.get("lessons") or [], SOURCE_CACHE, today,
                "Портал недоступен — показаны сохранённые ранее данные.",
            )
        sample = self._sample_lessons(group, day, today)
        if sample is not None:
            LOGGER.warning("День %s показан из демо-файла: %s", day, exc)
            return self._build_day(
                group, day, sample, SOURCE_SAMPLE, today,
                "Портал недоступен — показаны демонстрационные данные.",
            )
        raise ScheduleSourceError(str(exc))

    def get_schedule(
        self,
        group: str,
        days: int = DEFAULT_DAYS,
        force: bool = False,
        start: date | None = None,
    ) -> dict[str, Any]:
        """Расписание на ``days`` дней, начиная с сегодня (или с ``start``)."""
        days = max(1, min(int(days), MAX_DAYS))
        today = _today()
        start = start or today
        target_dates = [start + timedelta(days=offset) for offset in range(days)]

        resolved = self.resolve_group(group)

        # Принудительное обновление — не чаще cooldown на группу.
        requested_force = force
        if force:
            force = self.allow_forced_refresh(resolved)

        result_days: list[dict[str, Any]] = []
        for day in target_dates:
            try:
                result_days.append(self.get_day(resolved, day, force=force))
            except ScheduleSourceError as exc:
                # Ни живых данных, ни кэша, ни демо-файла: показываем честное
                # «данных нет» вместо ложного «занятий нет».
                LOGGER.error("День %s недоступен: %s", day, exc)
                failed = self._build_day(
                    resolved, day, [], SOURCE_ERROR, today,
                    f"Данные за {day.strftime('%d.%m.%Y')} недоступны: портал не отвечает.",
                )
                failed["unavailable"] = True
                result_days.append(failed)

        sources = {day["source"] for day in result_days}
        if sources <= {SOURCE_LIVE}:
            overall = SOURCE_LIVE
        elif sources == {SOURCE_ERROR}:
            overall = SOURCE_ERROR
        elif SOURCE_ERROR in sources or SOURCE_LIVE in sources:
            overall = "mixed"
        elif SOURCE_SAMPLE in sources:
            overall = SOURCE_SAMPLE
        else:
            overall = SOURCE_CACHE

        # Одинаковые предупреждения по каждому дню схлопываем в одно.
        warnings = list(dict.fromkeys(
            day["note"] for day in result_days if day.get("note")
        ))

        window_start, window_end = target_dates[0], target_dates[-1]
        has_lessons = any(day["has_lessons"] for day in result_days)

        # Подсказки, чтобы пустой экран не читался как «выходной».
        if not has_lessons and not warnings:
            if window_start > today:
                warnings.append(
                    "На выбранные даты занятий нет. Возможно, расписание ещё "
                    "не опубликовано."
                )
            elif window_end < today:
                warnings.append("За выбранные прошедшие даты занятий не найдено.")

        published = self.get_published_range()
        if published and (published.get("min") or published.get("max")):
            min_iso, max_iso = published.get("min"), published.get("max")
            min_date = parse_iso_date(min_iso)
            max_date = parse_iso_date(max_iso)
            if (min_date and window_start < min_date) or (max_date and window_end > max_date):
                warnings.append(
                    "Выбранные даты выходят за пределы опубликованного расписания "
                    f"({published.get('min_label')} — {published.get('max_label')})."
                )

        if requested_force and not force:
            warnings.append(
                "Обновление запрашивали меньше "
                f"{int(self.refresh_cooldown)} сек назад — данные взяты из кэша."
            )

        return {
            "group": resolved,
            "group_query": _clean(group),
            "generated_at": datetime.now().isoformat(timespec="seconds"),
            "days_count": days,
            "start_date": window_start.isoformat(),
            "end_date": window_end.isoformat(),
            "start_label": window_start.strftime("%d.%m.%Y"),
            "end_label": window_end.strftime("%d.%m.%Y"),
            "has_lessons": has_lessons,
            "published_range": published,
            "source": overall,
            "from_cache": not force and sources <= {SOURCE_CACHE},
            "warnings": warnings,
            "days": result_days,
        }

    # -- нормализация -------------------------------------------------------

    @staticmethod
    def _normalise_lesson(raw: dict[str, Any]) -> dict[str, Any]:
        """Приводит одну пару из API к плоскому виду."""
        raw = raw or {}
        timetable = raw.get("timetable") or {}
        teacher = raw.get("teacher") or {}
        cab = raw.get("cab") or {}
        group = raw.get("group") or {}

        full_name = _fio(teacher)
        room_number = _clean(cab.get("number") or cab.get("cab"))
        room_title = _clean(cab.get("title"))
        start = _fmt_time(timetable.get("start"))
        end = _fmt_time(timetable.get("end"))

        return {
            "number": raw.get("number"),
            "type": _clean(raw.get("type")),
            "discipline": _clean(raw.get("discipline")),
            "start": start,
            "end": end,
            "time": f"{start}–{end}" if start and end else (start or end),
            "teacher": full_name,
            "teacher_short": _short_fio(full_name),
            "teacher_link": _clean(teacher.get("link")) or None,
            "room": room_number,
            "room_title": room_title,
            "room_label": room_number or room_title,
            "remote": bool(raw.get("do")),
            "subgroup": raw.get("subgroup") or 0,
            "group": _clean(group.get("title")),
        }

    @staticmethod
    def _build_day(
        group: str,
        day: date,
        lessons: list[dict[str, Any]],
        source: str,
        today: date,
        note: str = "",
    ) -> dict[str, Any]:
        """Собирает карточку дня для фронтенда."""
        return {
            "date": day.isoformat(),
            "date_label": day.strftime("%d.%m.%Y"),
            "weekday": WEEKDAYS[day.weekday()],
            "weekday_short": WEEKDAYS_SHORT[day.weekday()],
            "is_today": day == today,
            "is_tomorrow": day == today + timedelta(days=1),
            "is_past": day < today,
            "is_weekend": day.weekday() >= 5,
            "has_lessons": bool(lessons),
            "lessons_count": len(lessons),
            "group": group,
            "source": source,
            "note": note,
            "lessons": lessons,
        }

    # -- демо-данные --------------------------------------------------------

    def _load_sample(self) -> dict[str, Any] | None:
        if self._sample_cache is None:
            try:
                self._sample_cache = json.loads(self.sample_file.read_text(encoding="utf-8"))
            except (OSError, ValueError) as exc:
                LOGGER.error("Не удалось прочитать демо-файл %s: %s", self.sample_file, exc)
                self._sample_cache = {}
        return self._sample_cache or None

    def _sample_lessons(
        self, group: str, day: date, today: date
    ) -> list[dict[str, Any]] | None:
        """Берёт демо-пары для нужного смещения дней (0 = сегодня)."""
        sample = self._load_sample()
        if not sample:
            return None
        offset = (day - today).days
        for entry in sample.get("days", []):
            if int(entry.get("offset", -1)) != offset:
                continue
            lessons: list[dict[str, Any]] = []
            for item in entry.get("lessons", []):
                raw = dict(item)
                if not raw.get("group"):
                    raw["group"] = {"title": group}
                lessons.append(self._normalise_lesson(raw))
            return lessons
        return []


# --- CLI -------------------------------------------------------------------


def _print_schedule(data: dict[str, Any]) -> None:
    print(f"\nГруппа: {data['group']}   (источник: {data['source']})")
    print(f"Обновлено: {data['generated_at']}")
    for day in data["days"]:
        marker = "  <-- сегодня" if day["is_today"] else ""
        print(f"\n=== {day['weekday']}, {day['date_label']}{marker}")
        if not day["has_lessons"]:
            print("    Занятий нет")
            continue
        for lesson in day["lessons"]:
            room = lesson["room_label"] or "—"
            remote = " [дистанционно]" if lesson["remote"] else ""
            print(
                f"    {lesson['number']}. {lesson['time']:>13}  {lesson['discipline']}"
                f"{remote}\n        {lesson['type']} · {lesson['teacher_short']} · ауд. {room}"
            )
    for warning in data["warnings"]:
        print(f"\n[!] {warning}")


def main(argv: list[str] | None = None) -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")

    parser = argparse.ArgumentParser(description="Расписание группы с портала УКРТБ.")
    parser.add_argument("--group", default=DEFAULT_GROUP, help="группа, например КСК-40")
    parser.add_argument("--days", type=int, default=DEFAULT_DAYS, help="сколько дней (1..14)")
    parser.add_argument("--date", help="дата начала в формате ГГГГ-ММ-ДД (по умолчанию сегодня)")
    parser.add_argument("--refresh", action="store_true", help="игнорировать кэш")
    parser.add_argument("--json", action="store_true", help="вывести сырой JSON")
    parser.add_argument("--list-groups", action="store_true", help="показать все группы портала")
    parser.add_argument("--published-range", action="store_true",
                        help="показать период, за который портал публикует расписание")
    args = parser.parse_args(argv)

    logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
    client = ScheduleClient()

    start = None
    if args.date:
        start = parse_iso_date(args.date)
        if start is None:
            print("Ошибка: --date должен быть датой в формате ГГГГ-ММ-ДД.", file=sys.stderr)
            return 2

    try:
        if args.list_groups:
            for group in client.get_groups(force=args.refresh):
                print(group.get("title"))
            return 0

        if args.published_range:
            published = client.get_published_range(force=args.refresh)
            if not published:
                print("Не удалось получить границы расписания.", file=sys.stderr)
                return 1
            print(f"Расписание опубликовано: {published['min_label']} — {published['max_label']}")
            return 0

        data = client.get_schedule(args.group, days=args.days, force=args.refresh, start=start)
    except GroupNotFoundError as exc:
        print(f"Ошибка: {exc}", file=sys.stderr)
        return 2
    except ScheduleError as exc:
        print(f"Ошибка: {exc}", file=sys.stderr)
        return 1

    if args.json:
        print(json.dumps(data, ensure_ascii=False, indent=2))
    else:
        _print_schedule(data)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
