# -*- coding: utf-8 -*-
"""Сборка статической версии расписания для GitHub Pages.

Зачем это нужно
---------------
Портал ``study.ukrtb.ru`` открывается не отовсюду: проверка из 17 стран
показала, что американские узлы получают ответ за 0.6 с, а Германия,
Нидерланды, Польша, Канада, Япония, Турция и другие — таймаут соединения.
Поэтому зарубежный хостинг (например, Render во Франкфурте) живых данных
не получит.

Решение: забирать расписание там, где портал доступен — на этом
компьютере, — и публиковать уже готовую страницу на GitHub Pages. Статика
раздаётся по всему миру, сервер не нужен, геоблокировка не мешает.

Запуск::

    python build_static.py                     # 7 дней назад, 10 вперёд
    python build_static.py --back 14 --ahead 21
    python build_static.py --group КСК-40 --out docs

Результат — каталог ``docs/``::

    docs/index.html          готовая страница
    docs/app.js              тот же интерфейс, но в режиме static
    docs/styles.css
    docs/sw.js               service worker: работа без сети
    docs/manifest.webmanifest   описание приложения для ярлыка на экране
    docs/icons/              иконки (apple-touch-icon и прочие)
    docs/data.json           расписание за весь собранный диапазон дат
"""

from __future__ import annotations

import argparse
import hashlib
import json
import logging
import shutil
import sys
from datetime import date, datetime, timedelta
from pathlib import Path

from jinja2 import Environment, FileSystemLoader, select_autoescape

from schedule_client import DEFAULT_GROUP, ScheduleClient, ScheduleError

PROJECT_ROOT = Path(__file__).resolve().parent
DEFAULT_OUT = PROJECT_ROOT / "docs"
SOURCE_URL = "https://study.ukrtb.ru/schedule"

LOGGER = logging.getLogger("ukrtb.static")


def schedule_signature(payload: dict) -> str:
    """Отпечаток расписания без отметки времени сборки.

    Нужен, чтобы понять, изменилось ли расписание: зашифрованный файл при
    каждой сборке получается разным (случайные соль и вектор), поэтому
    сравнивать байты бессмысленно, а отметка времени меняется всегда.
    """
    canonical = {key: value for key, value in payload.items() if key != "generated_at"}
    raw = json.dumps(canonical, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def build(group: str, back: int, ahead: int, out_dir: Path,
          days_shown: int = 3, force: bool = False) -> dict:
    """Собирает статическую страницу. Возвращает сводку."""
    client = ScheduleClient()
    resolved = client.resolve_group(group)
    today = date.today()

    dates = [today + timedelta(days=offset) for offset in range(-back, ahead + 1)]
    LOGGER.info("Собираю %s дней для группы %s (%s .. %s)",
                len(dates), resolved, dates[0], dates[-1])

    days: dict[str, dict] = {}
    sources: set[str] = set()
    warnings: list[str] = []
    failures = 0

    for index, day in enumerate(dates, start=1):
        payload = client.get_day(resolved, day, force=force)
        days[day.isoformat()] = payload
        sources.add(payload["source"])
        if payload.get("note"):
            warnings.append(payload["note"])
        if payload["source"] == "error":
            failures += 1
        LOGGER.info("  [%s/%s] %s — пар: %s (%s)",
                    index, len(dates), day, payload["lessons_count"], payload["source"])

    if sources == {"live"}:
        overall = "live"
    elif "error" in sources and len(sources) == 1:
        overall = "error"
    elif "sample" in sources:
        overall = "sample"
    elif "cache" in sources:
        overall = "cache"
    else:
        overall = "mixed"

    payload = {
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "group": resolved,
        "group_query": group,
        "source": overall,
        "days_count": len(dates),
        "range_from": dates[0].isoformat(),
        "range_to": dates[-1].isoformat(),
        "range_label": f"{dates[0].strftime('%d.%m.%Y')} — {dates[-1].strftime('%d.%m.%Y')}",
        "published_range": client.get_published_range(),
        "warnings": list(dict.fromkeys(warnings)),
        "days": days,
    }

    out_dir.mkdir(parents=True, exist_ok=True)

    # 0. Отпечаток расписания: по нему refresh.ps1 решает, нужно ли
    #    вообще публиковать (иначе каждые 3 часа был бы пустой коммит).
    signature = schedule_signature(payload)
    (out_dir / "data.sig").write_text(signature + "\n", encoding="utf-8", newline="\n")

    # 1. Данные
    (out_dir / "data.json").write_text(
        json.dumps(payload, ensure_ascii=False, separators=(",", ":")),
        encoding="utf-8",
        newline="\n",  # без CRLF: файл уезжает в Linux-ориентированный репозиторий
    )

    # 2. Статика интерфейса (тот же app.js и styles.css, что и у Flask-версии)
    #    плюс всё для ярлыка на домашнем экране: манифест, иконки, service worker.
    for name in ("app.js", "styles.css", "sw.js", "manifest.webmanifest"):
        shutil.copyfile(PROJECT_ROOT / "static" / name, out_dir / name)

    icons_src = PROJECT_ROOT / "static" / "icons"
    icons_dst = out_dir / "icons"
    if icons_dst.exists():
        shutil.rmtree(icons_dst)
    shutil.copytree(icons_src, icons_dst)

    # 3. Страница: тот же шаблон, но в режиме static
    env = Environment(
        loader=FileSystemLoader(str(PROJECT_ROOT / "templates")),
        autoescape=select_autoescape(["html"]),
    )
    template = env.get_template("index.html")
    html = template.render(
        mode="static",
        default_group=resolved,
        default_days=days_shown,
        source_url=SOURCE_URL,
        # В шаблоне используется Flask-хелпер url_for: в статике файлы
        # лежат рядом, поэтому достаточно имени файла.
        url_for=lambda endpoint, **kwargs: kwargs.get("filename", ""),
    )
    (out_dir / "index.html").write_text(html, encoding="utf-8", newline="\n")

    # 4. Заглушка, чтобы GitHub Pages не пытался исполнять Jekyll
    (out_dir / ".nojekyll").write_text("", encoding="utf-8", newline="\n")

    LOGGER.info("Готово: %s (источник: %s, дней: %s, ошибок: %s)",
                out_dir, overall, len(dates), failures)
    return payload


def main(argv: list[str] | None = None) -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")

    parser = argparse.ArgumentParser(
        description="Сборка статической версии расписания для GitHub Pages."
    )
    parser.add_argument("--group", default=DEFAULT_GROUP, help="группа (например, КСК-40)")
    parser.add_argument("--back", type=int, default=7, help="сколько дней назад собрать")
    parser.add_argument("--ahead", type=int, default=10, help="сколько дней вперёд собрать")
    parser.add_argument("--days", type=int, default=3, help="сколько дней показывать по умолчанию")
    parser.add_argument("--out", default=str(DEFAULT_OUT), help="каталог результата")
    parser.add_argument(
        "--force", dest="force", action="store_true", default=True,
        help="запрашивать данные заново (включено по умолчанию: это скрипт обновления)",
    )
    parser.add_argument(
        "--use-cache", dest="force", action="store_false",
        help="разрешить брать дни из локального кэша (до 10 минут)",
    )
    parser.add_argument("-q", "--quiet", action="store_true", help="меньше вывода")
    args = parser.parse_args(argv)

    logging.basicConfig(
        level=logging.WARNING if args.quiet else logging.INFO,
        format="%(levelname)-7s %(message)s",
    )

    try:
        payload = build(
            group=args.group,
            back=max(0, args.back),
            ahead=max(0, args.ahead),
            out_dir=Path(args.out),
            days_shown=max(1, args.days),
            force=args.force,
        )
    except ScheduleError as exc:
        print(f"Ошибка: {exc}", file=sys.stderr)
        return 1

    live = sum(1 for d in payload["days"].values() if d["source"] == "live")
    empty = sum(1 for d in payload["days"].values() if not d["has_lessons"])
    print(f"\n  Группа:       {payload['group']}")
    print(f"  Диапазон:     {payload['range_label']} ({payload['days_count']} дней)")
    print(f"  Источник:     {payload['source']}")
    print(f"  Живых дней:   {live}")
    print(f"  Без занятий:  {empty}")
    print(f"  Каталог:      {args.out}")
    print(f"  Собрано:      {payload['generated_at']}\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
