# -*- coding: utf-8 -*-
"""Самотесты: разбор данных, выбор даты и деградация при недоступном портале.

Запуск (без сторонних библиотек, только стандартная)::

    python tests/test_schedule_client.py
"""

from __future__ import annotations

import json
import logging
import sys
import tempfile
import threading
import time
import unittest
from datetime import date, timedelta
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from schedule_client import (  # noqa: E402  (импорт после правки sys.path)
    SOURCE_CACHE,
    SOURCE_LIVE,
    SOURCE_SAMPLE,
    GroupNotFoundError,
    ScheduleClient,
    ScheduleSourceError,
    parse_iso_date,
)

# Заведомо недоступный адрес: гарантирует сценарий «портала нет».
DEAD_URL = "http://127.0.0.1:9/api"


def make_client(cache_dir: Path, base_url: str = DEAD_URL) -> ScheduleClient:
    return ScheduleClient(
        base_url=base_url,
        cache_dir=cache_dir,
        cache_ttl=600,
        timeout=1,
        attempts=1,
    )


class TestNormalisation(unittest.TestCase):
    """Разбор ответа API в плоскую структуру."""

    def test_remote_lesson(self) -> None:
        lesson = ScheduleClient._normalise_lesson({
            "number": 1,
            "type": "Лекции",
            "discipline": "  МДК. Программирование   микроконтроллеров ",
            "timetable": {"start": "9:10", "end": "10:10"},
            "do": True,
            "teacher": {"surname": "Альметова", "name": "Лилия", "patronymic": "Илфатовна",
                        "fullName": "Альметова Лилия Илфатовна", "link": "https://max.ru/join/x"},
            "cab": {"number": "", "title": ""},
        })
        self.assertEqual(lesson["start"], "09:10")          # время дополняется нулём
        self.assertEqual(lesson["time"], "09:10–10:10")
        self.assertTrue(lesson["remote"])
        self.assertEqual(lesson["teacher_short"], "Альметова Л. И.")
        self.assertIsNone(lesson["room_label"] or None)     # аудитории нет
        self.assertEqual(lesson["discipline"],
                         "МДК. Программирование микроконтроллеров")

    def test_offline_lesson_with_room(self) -> None:
        lesson = ScheduleClient._normalise_lesson({
            "number": 2,
            "type": "Практические занятия",
            "discipline": "Компьютерные сети",
            "timetable": {"start": "08:00", "end": "09:20"},
            "do": False,
            "teacher": {"fullName": "Плотникова Виктория Константиновна"},
            "cab": {"number": "414", "title": "Зона «Облачные технологии»"},
        })
        self.assertFalse(lesson["remote"])
        self.assertEqual(lesson["room_label"], "414")
        self.assertEqual(lesson["room_title"], "Зона «Облачные технологии»")
        self.assertIsNone(lesson["teacher_link"])


class TestGroupResolution(unittest.TestCase):
    """Сопоставление «КСК-40» -> «КСК-40-23»."""

    class FakeGroups(ScheduleClient):
        def __init__(self, titles, **kwargs):  # noqa: D107
            kwargs.setdefault("cache_dir", Path(tempfile.mkdtemp()))
            super().__init__(**kwargs)
            self._titles = titles

        def get_groups(self, force: bool = False):  # noqa: D102
            return [{"title": title} for title in self._titles]

    def setUp(self) -> None:
        self.titles = ["КСК-40-23", "КСК-30-24", "КСК-40-23к", "ВЕБ-1-26П", "ИСП-21-24"]
        self.client = self.FakeGroups(self.titles)

    def test_exact_match(self) -> None:
        self.assertEqual(self.client.resolve_group("КСК-40-23"), "КСК-40-23")

    def test_prefix_match_prefers_shortest(self) -> None:
        self.assertEqual(self.client.resolve_group("КСК-40"), "КСК-40-23")

    def test_case_insensitive_and_spaces(self) -> None:
        self.assertEqual(self.client.resolve_group("  кск-40  "), "КСК-40-23")

    def test_substring_match(self) -> None:
        self.assertEqual(self.client.resolve_group("40-23к"), "КСК-40-23к")

    def test_unknown_group_raises(self) -> None:
        with self.assertRaises(GroupNotFoundError) as ctx:
            self.client.resolve_group("QQQ-999")
        self.assertEqual(ctx.exception.suggestions, [])  # не подсказываем чужое


class TestGracefulDegradation(unittest.TestCase):
    """Поведение при недоступном портале: кэш, затем демо-данные."""

    def setUp(self) -> None:
        self.tmp = Path(tempfile.mkdtemp(prefix="ukrtb-test-"))

    def test_sample_fallback_when_source_dead(self) -> None:
        client = make_client(self.tmp)
        day = date.today() + timedelta(days=2)
        result = client.get_day("КСК-40-23", day)
        self.assertEqual(result["source"], SOURCE_SAMPLE)
        self.assertTrue(result["note"])                 # пользователь предупреждён
        self.assertTrue(result["lessons"])              # демо-данные не пустые
        self.assertEqual(result["date"], day.isoformat())
        self.assertTrue(result["lessons"][0]["discipline"])

    def test_sample_fallback_keeps_empty_days_empty(self) -> None:
        client = make_client(self.tmp)
        day = date.today() + timedelta(days=1)          # offset 1 -> без пар
        result = client.get_day("КСК-40-23", day)
        self.assertEqual(result["source"], SOURCE_SAMPLE)
        self.assertFalse(result["has_lessons"])

    def _write_cached_day(self, client: ScheduleClient, day: date, age_seconds: float = 0) -> None:
        """Кладёт запись в кэш, при необходимости «состаривая» её."""
        name = client._day_cache_name("КСК-40-23", day)
        client._cache_write(name, {"lessons": [{
            "number": 1, "discipline": "Из кэша", "time": "08:00–09:20",
            "start": "08:00", "end": "09:20", "teacher": "Тестовый Преподаватель",
            "teacher_short": "Тестовый П.", "teacher_link": None, "room": "101",
            "room_title": "", "room_label": "101", "remote": False, "subgroup": 0,
            "type": "Лекции", "group": "КСК-40-23",
        }]})
        if age_seconds:
            path = client._cache_file(name)
            raw = json.loads(path.read_text(encoding="utf-8"))
            raw["stored_at"] = time.time() - age_seconds
            path.write_text(json.dumps(raw, ensure_ascii=False), encoding="utf-8")

    def test_fresh_cache_served_without_network(self) -> None:
        """Свежий кэш отдаётся молча: портал вообще не опрашивается."""
        day = date.today()
        writer = make_client(self.tmp)
        self._write_cached_day(writer, day)

        reader = make_client(self.tmp)  # память пуста, портал недоступен
        result = reader.get_day("КСК-40-23", day)

        self.assertEqual(result["source"], SOURCE_CACHE)
        self.assertEqual(result["lessons"][0]["discipline"], "Из кэша")
        self.assertEqual(result["note"], "")

    def test_stale_cache_used_when_source_dead(self) -> None:
        """Просроченный кэш спасает положение, но с предупреждением."""
        day = date.today()
        writer = make_client(self.tmp)
        self._write_cached_day(writer, day, age_seconds=7200)  # 2 часа назад

        reader = make_client(self.tmp)
        result = reader.get_day("КСК-40-23", day)

        self.assertEqual(result["source"], SOURCE_CACHE)
        self.assertEqual(result["lessons"][0]["discipline"], "Из кэша")
        self.assertTrue(result["note"], "должно быть предупреждение о неактуальности")

    def test_hard_failure_without_cache_and_without_sample(self) -> None:
        client = ScheduleClient(
            base_url=DEAD_URL,
            cache_dir=self.tmp,
            timeout=1,
            attempts=1,
            sample_file=self.tmp / "missing.json",   # демо-файла тоже нет
        )
        client._memory.clear()
        with self.assertRaises(ScheduleSourceError):
            client.get_day("КСК-40-23", date.today())


class TestSampleFileFormat(unittest.TestCase):
    """Проверка структуры демо-файла."""

    def test_sample_file_is_valid(self) -> None:
        path = PROJECT_ROOT / "data" / "sample_schedule.json"
        payload = json.loads(path.read_text(encoding="utf-8"))
        offsets = sorted(int(entry["offset"]) for entry in payload["days"])
        self.assertEqual(offsets, [0, 1, 2])
        for entry in payload["days"]:
            for lesson in entry["lessons"]:
                self.assertIn("discipline", lesson)
                self.assertIn("timetable", lesson)
                self.assertIn("start", lesson["timetable"])


class TestParseIsoDate(unittest.TestCase):
    """Разбор даты из параметра запроса."""

    def test_valid_date(self) -> None:
        self.assertEqual(parse_iso_date("2026-10-07"), date(2026, 10, 7))
        self.assertEqual(parse_iso_date(" 2026-01-01 "), date(2026, 1, 1))

    def test_invalid_dates(self) -> None:
        for bad in ["07.10.2026", "2026-10", "", None, "abc",
                    "2026-13-01", "2026-02-30", "2026-1-1"]:
            self.assertIsNone(parse_iso_date(bad), f"должно быть None: {bad!r}")


def _lesson(discipline: str = "Тестовая дисциплина") -> dict:
    return {
        "number": 1,
        "type": "Лекции",
        "discipline": discipline,
        "timetable": {"start": "08:00", "end": "09:20"},
        "do": False,
        "teacher": {"fullName": "Тестов Тест Тестович"},
        "cab": {"number": "101", "title": ""},
    }


class FakeApi(ScheduleClient):
    """Клиент с подставным API: тесты выбора даты не зависят от сети."""

    BORDER = {"success": True, "min": "2023-09-02", "max": "2026-10-10"}

    def __init__(self, lessons_by_date: dict | None = None, **kwargs) -> None:
        kwargs.setdefault("cache_dir", Path(tempfile.mkdtemp(prefix="ukrtb-fake-")))
        super().__init__(base_url="http://fake.invalid/api", **kwargs)
        self.lessons_by_date = lessons_by_date or {}

    def _request(self, path: str, params: dict | None = None):
        clean = path.rstrip("/")
        if clean.endswith("/border/date"):
            return self.BORDER
        if clean.endswith("/schedules/groups"):
            return {"success": True, "data": [{"title": "КСК-40-23"}]}
        if clean.endswith("/schedules"):
            day = (params or {}).get("date")
            lessons = self.lessons_by_date.get(day)
            if lessons is None:
                return None  # портал отвечает 204: данных на дату нет
            return {"success": True, "data": {
                "type": "groups", "date": day, "title": "КСК-40-23",
                "schedules": lessons,
            }}
        raise ScheduleSourceError(f"Неожиданный путь: {path}")


class TestDateSelection(unittest.TestCase):
    """Выбор произвольной даты: прошлое, будущее, границы периода."""

    def test_past_start_date(self) -> None:
        day = date(2026, 9, 28)
        client = FakeApi({day.isoformat(): [_lesson()]})
        data = client.get_schedule("КСК-40", days=1, start=day)

        self.assertEqual(data["start_date"], "2026-09-28")
        self.assertEqual(data["start_label"], "28.09.2026")
        self.assertEqual(data["end_date"], "2026-09-28")
        self.assertEqual(data["days"][0]["source"], SOURCE_LIVE)
        self.assertTrue(data["days"][0]["is_past"])
        self.assertFalse(data["days"][0]["is_today"])
        self.assertEqual(data["days"][0]["lessons_count"], 1)
        self.assertEqual(data["warnings"], [])

    def test_today_is_not_marked_as_past(self) -> None:
        today = date.today()
        client = FakeApi({today.isoformat(): [_lesson()]})
        day = client.get_schedule("КСК-40", days=1, start=today)["days"][0]

        self.assertTrue(day["is_today"])
        self.assertFalse(day["is_past"])

    def test_window_covers_requested_dates_in_order(self) -> None:
        start = date(2026, 9, 28)
        data = FakeApi().get_schedule("КСК-40", days=7, start=start)
        expected = [(start + timedelta(days=i)).isoformat() for i in range(7)]

        self.assertEqual(data["days_count"], 7)
        self.assertEqual([d["date"] for d in data["days"]], expected)
        # Первые дни окна — прошедшие, последние — будущие.
        self.assertTrue(data["days"][0]["is_past"])
        self.assertFalse(data["days"][-1]["is_past"])

    def test_empty_future_window_warns_about_publication(self) -> None:
        client = FakeApi()  # пар нет ни на одну дату
        data = client.get_schedule("КСК-40", days=3, start=date.today() + timedelta(days=30))

        self.assertFalse(data["has_lessons"])
        self.assertTrue(any("не опубликовано" in w for w in data["warnings"]))

    def test_empty_past_window_warns_too(self) -> None:
        client = FakeApi()
        data = client.get_schedule("КСК-40", days=1, start=date.today() - timedelta(days=10))

        self.assertTrue(any("прошедшие даты" in w for w in data["warnings"]))

    def test_quiet_weekend_without_warnings(self) -> None:
        """Пустой сегодняшний день — это норма, а не проблема."""
        client = FakeApi()
        data = client.get_schedule("КСК-40", days=1, start=date.today())

        self.assertFalse(data["has_lessons"])
        self.assertEqual(data["warnings"], [])

    def test_out_of_published_range_warning(self) -> None:
        client = FakeApi()
        data = client.get_schedule("КСК-40", days=1, start=date(2027, 1, 1))

        self.assertTrue(any("за пределы опубликованного" in w for w in data["warnings"]))
        self.assertEqual(data["published_range"]["max"], "2026-10-10")

    def test_published_range_present_in_response(self) -> None:
        data = FakeApi().get_schedule("КСК-40", days=1, start=date.today())

        self.assertEqual(data["published_range"]["min_label"], "02.09.2023")
        self.assertEqual(data["published_range"]["max_label"], "10.10.2026")


class TestPublicLoadProtection(unittest.TestCase):
    """Защита портала колледжа от публичного трафика."""

    def test_single_flight_fetches_day_once(self) -> None:
        """Десять одновременных запросов одного дня = один запрос к порталу."""
        day = date.today()
        client = FakeApi({day.isoformat(): [_lesson()]})
        client.cache_ttl = 600

        calls = []
        original = client._fetch_day

        def counting_fetch(group, target):
            calls.append(target)
            time.sleep(0.05)  # имитируем сетевую задержку
            return original(group, target)

        client._fetch_day = counting_fetch  # type: ignore[assignment]

        results: list[dict] = []
        guard = threading.Lock()

        def worker():
            data = client.get_day("КСК-40-23", day)
            with guard:
                results.append(data)

        threads = [threading.Thread(target=worker) for _ in range(10)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join(timeout=10)

        self.assertEqual(len(results), 10)
        self.assertEqual(len(calls), 1, "в сеть должен уйти ровно один запрос")
        self.assertTrue(all(r["lessons_count"] == 1 for r in results))

    def test_forced_refresh_is_throttled(self) -> None:
        client = FakeApi(refresh_cooldown=60)

        self.assertTrue(client.allow_forced_refresh("КСК-40-23"))
        self.assertFalse(client.allow_forced_refresh("КСК-40-23"))
        # Другая группа — свой счётчик.
        self.assertTrue(client.allow_forced_refresh("КСК-30-24"))

    def test_forced_refresh_can_be_disabled(self) -> None:
        client = FakeApi(refresh_cooldown=0)
        for _ in range(5):
            self.assertTrue(client.allow_forced_refresh("КСК-40-23"))

    def test_throttled_refresh_warns_and_serves_cache(self) -> None:
        day = date.today()
        client = FakeApi({day.isoformat(): [_lesson()]})

        first = client.get_schedule("КСК-40", days=1, start=day, force=True)
        self.assertEqual(first["days"][0]["source"], SOURCE_LIVE)
        self.assertEqual(first["warnings"], [])

        second = client.get_schedule("КСК-40", days=1, start=day, force=True)
        self.assertEqual(second["days"][0]["source"], SOURCE_CACHE)
        self.assertTrue(any("меньше" in w for w in second["warnings"]))


class TestCircuitBreaker(unittest.TestCase):
    """«Предохранитель»: недоступный портал не должен растягивать ответ."""

    def test_one_network_attempt_for_whole_request(self) -> None:
        """Неделя при мёртвом портале: одна попытка в сеть, а не восемь."""
        client = make_client(Path(tempfile.mkdtemp(prefix="ukrtb-breaker-")))
        attempts: list[str] = []
        real_request = client._request

        def counting_request(path, params=None):
            attempts.append(path)
            return real_request(path, params)

        client._request = counting_request  # type: ignore[assignment]
        data = client.get_schedule("КСК-40", days=7)

        self.assertEqual(
            len(attempts), 1,
            f"ожидалась 1 попытка в сеть, было {len(attempts)}: {attempts}",
        )
        self.assertEqual(len(data["days"]), 7)
        self.assertTrue(all(d["source"] == SOURCE_SAMPLE for d in data["days"]))
        self.assertTrue(any("демонстрационные" in w for w in data["warnings"]))

    def test_breaker_expires(self) -> None:
        """Через заданное время попытки возобновляются."""
        client = make_client(Path(tempfile.mkdtemp(prefix="ukrtb-breaker-")))
        self.assertFalse(client.source_is_down())

        client._mark_source_down(60)
        self.assertTrue(client.source_is_down())

        client._mark_source_down(0)          # как будто пауза истекла
        self.assertFalse(client.source_is_down())

    def test_breaker_does_not_block_cached_days(self) -> None:
        """Даже с включённым предохранителем кэш отдаётся."""
        client = make_client(Path(tempfile.mkdtemp(prefix="ukrtb-breaker-")))
        day = date.today()
        name = client._day_cache_name("КСК-40-23", day)
        client._cache_write(name, {"lessons": [_lesson("Из кэша при сбое")]})
        client._mark_source_down(600)

        result = client.get_day("КСК-40-23", day)

        self.assertEqual(result["source"], SOURCE_CACHE)
        self.assertEqual(result["lessons"][0]["discipline"], "Из кэша при сбое")


if __name__ == "__main__":
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")
    # Ожидаемые предупреждения о недоступном портале в отчёте не нужны.
    logging.disable(logging.CRITICAL)
    unittest.main(verbosity=2)
