# -*- coding: utf-8 -*-
"""Веб-приложение: расписание группы КСК-40 на ближайшие 3 дня.

Запуск::

    python app.py                # http://127.0.0.1:5000
    python app.py --port 8000 --open

Бэкенд отдаёт два эндпоинта:

* ``GET /api/schedule?group=КСК-40&days=3&refresh=1`` — расписание;
* ``GET /api/groups?q=КСК`` — список групп портала (для подсказок в поиске).
"""

from __future__ import annotations

import argparse
import logging
import os
import sys
import threading
import webbrowser
from typing import Any
from urllib.parse import urlparse

from flask import Flask, jsonify, render_template, request

from schedule_client import (
    DEFAULT_DAYS,
    DEFAULT_GROUP,
    MAX_DAYS,
    GroupNotFoundError,
    ScheduleClient,
    ScheduleError,
    ScheduleSourceError,
    parse_iso_date,
)

LOGGER = logging.getLogger("ukrtb.web")

app = Flask(__name__)
app.config["JSON_AS_ASCII"] = False
app.config["TEMPLATES_AUTO_RELOAD"] = True
app.config["DEFAULT_GROUP"] = DEFAULT_GROUP

_client_lock = threading.Lock()
_client: ScheduleClient | None = None


def default_group() -> str:
    """Группа по умолчанию (меняется флагом --group или переменной UKRTB_GROUP)."""
    return app.config.get("DEFAULT_GROUP") or DEFAULT_GROUP


def get_client() -> ScheduleClient:
    """Ленивая инициализация клиента (чтобы импорт не ходил в сеть)."""
    global _client
    with _client_lock:
        if _client is None:
            _client = ScheduleClient()
        return _client


# --- Страницы --------------------------------------------------------------


@app.get("/")
def index() -> str:
    return render_template(
        "index.html",
        default_group=default_group(),
        default_days=DEFAULT_DAYS,
        source_url="https://study.ukrtb.ru/schedule",
    )


# --- API -------------------------------------------------------------------


@app.get("/api/schedule")
def api_schedule():
    """Расписание группы на N дней от выбранной даты (по умолчанию 3 дня от сегодня)."""
    group = (request.args.get("group") or default_group()).strip() or default_group()
    refresh = (request.args.get("refresh") or "").lower() in {"1", "true", "yes", "on"}

    raw_date = (request.args.get("date") or "").strip()
    start = None
    if raw_date:
        start = parse_iso_date(raw_date)
        if start is None:
            return jsonify({
                "error": "Параметр date должен быть датой в формате ГГГГ-ММ-ДД, "
                         "например 2026-10-07.",
                "code": "bad_request",
            }), 400

    raw_days = request.args.get("days")
    try:
        days = int(raw_days) if raw_days else DEFAULT_DAYS
    except ValueError:
        return jsonify({
            "error": "Параметр days должен быть целым числом.",
            "code": "bad_request",
        }), 400
    days = max(1, min(days, MAX_DAYS))

    try:
        data = get_client().get_schedule(group, days=days, force=refresh, start=start)
    except GroupNotFoundError as exc:
        return jsonify({
            "error": str(exc),
            "code": "group_not_found",
            "suggestions": exc.suggestions,
        }), 404
    except ScheduleSourceError as exc:
        LOGGER.error("Источник недоступен: %s", exc)
        return jsonify({
            "error": "Сайт колледжа недоступен, и сохранённых данных тоже нет. "
                     "Проверьте подключение к интернету и попробуйте ещё раз.",
            "details": str(exc),
            "code": "source_unavailable",
        }), 502
    except ScheduleError as exc:
        LOGGER.error("Ошибка расписания: %s", exc)
        return jsonify({"error": str(exc), "code": "schedule_error"}), 500

    payload: dict[str, Any] = dict(data)
    payload["ok"] = True
    response = jsonify(payload)
    response.headers["Cache-Control"] = "no-store"
    return response


@app.get("/api/groups")
def api_groups():
    """Список групп портала; ``?q=`` — фильтр по подстроке."""
    query = (request.args.get("q") or "").strip().casefold()
    force = (request.args.get("refresh") or "").lower() in {"1", "true", "yes", "on"}
    try:
        groups = get_client().get_groups(force=force)
    except ScheduleError as exc:
        LOGGER.warning("Не удалось получить список групп: %s", exc)
        return jsonify({"error": str(exc), "code": "source_unavailable", "groups": []}), 502

    titles = sorted({(g.get("title") or "").strip() for g in groups if g.get("title")})
    if query:
        titles = [t for t in titles if query in t.casefold()]
    return jsonify({"ok": True, "count": len(titles), "groups": titles})


@app.get("/api/range")
def api_range():
    """Границы периода, за который портал публикует расписание."""
    published = get_client().get_published_range()
    return jsonify({"ok": bool(published), "range": published})


@app.get("/api/diagnose")
def api_diagnose():
    """Проверка, дотягивается ли этот сервер до портала колледжа.

    Нужна, когда приложение развёрнуто на хостинге: у некоторых хостеров
    исходящие запросы к порталу не проходят (например, регион Франкфурт
    у Render). Эндпоинт показывает, на каком шаге всё ломается: DNS,
    TCP-соединение или сам HTTP-запрос.
    """
    import socket
    import time as _time

    from schedule_client import BASE_URL

    host = urlparse(BASE_URL).hostname or "study.ukrtb.ru"
    report: dict[str, Any] = {"host": host, "steps": []}

    # 1. DNS
    started = _time.perf_counter()
    try:
        addrs = socket.getaddrinfo(host, 443, proto=socket.IPPROTO_TCP)
        ips = sorted({item[4][0] for item in addrs})
        report["steps"].append({
            "step": "dns",
            "ok": True,
            "seconds": round(_time.perf_counter() - started, 2),
            "addresses": ips,
        })
    except OSError as exc:
        report["steps"].append({
            "step": "dns",
            "ok": False,
            "seconds": round(_time.perf_counter() - started, 2),
            "error": f"{type(exc).__name__}: {exc}",
        })
        report["ok"] = False
        report["verdict"] = "Имя портала не разрешается в IP — проблема с DNS хостинга."
        return jsonify(report)

    # 2. TCP-соединение
    started = _time.perf_counter()
    try:
        with socket.create_connection((host, 443), timeout=8):
            report["steps"].append({
                "step": "tcp",
                "ok": True,
                "seconds": round(_time.perf_counter() - started, 2),
            })
    except OSError as exc:
        report["steps"].append({
            "step": "tcp",
            "ok": False,
            "seconds": round(_time.perf_counter() - started, 2),
            "error": f"{type(exc).__name__}: {exc}",
        })
        report["ok"] = False
        report["verdict"] = (
            "TCP-соединение с порталом не устанавливается: похоже, портал "
            "недоступен из сети этого хостинга. Помогает смена региона "
            "(например, у Render — на американский) или запуск приложения "
            "там, где портал открывается."
        )
        return jsonify(report)

    # 3. HTTPS-запрос
    started = _time.perf_counter()
    try:
        import requests
        response = requests.get(
            f"https://{host}/schedule",
            timeout=10,
            verify=os.getenv("UKRTB_VERIFY_TLS", "1") not in {"0", "false", "False"},
            headers={"User-Agent": "ukrtb-schedule/1.0 (diagnose)"},
        )
        report["steps"].append({
            "step": "https",
            "ok": response.status_code < 500,
            "seconds": round(_time.perf_counter() - started, 2),
            "status": response.status_code,
        })
        report["ok"] = response.status_code < 500
        report["verdict"] = (
            "Портал отвечает — приложение должно получать живые данные."
            if report["ok"] else
            f"Портал вернул HTTP {response.status_code}."
        )
    except Exception as exc:  # requests.RequestException и прочее
        report["steps"].append({
            "step": "https",
            "ok": False,
            "seconds": round(_time.perf_counter() - started, 2),
            "error": f"{type(exc).__name__}: {exc}",
        })
        report["ok"] = False
        report["verdict"] = (
            "TCP-соединение проходит, но HTTPS-запрос не завершается: "
            "похоже, соединение режет промежуточный фильтр."
        )

    return jsonify(report)


@app.get("/api/health")
def api_health():
    return jsonify({"ok": True, "service": "ukrtb-schedule", "group": default_group()})


# --- Обработчики ошибок ----------------------------------------------------


@app.errorhandler(404)
def handle_404(error):
    if request.path.startswith("/api/"):
        return jsonify({"error": "Эндпоинт не найден.", "code": "not_found"}), 404
    return render_template("index.html", default_group=default_group(),
                           default_days=DEFAULT_DAYS,
                           source_url="https://study.ukrtb.ru/schedule"), 404


@app.errorhandler(500)
def handle_500(error):  # pragma: no cover - защитная сетка
    LOGGER.exception("Внутренняя ошибка: %s", error)
    if request.path.startswith("/api/"):
        return jsonify({"error": "Внутренняя ошибка сервера.", "code": "internal"}), 500
    return "Внутренняя ошибка сервера", 500


@app.after_request
def add_headers(response):
    if request.path.startswith("/api/"):
        response.headers.setdefault("Cache-Control", "no-store")
    return response


# --- Точка входа -----------------------------------------------------------


def main(argv: list[str] | None = None) -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")

    parser = argparse.ArgumentParser(description="Локальный просмотр расписания УКРТБ.")
    parser.add_argument("--host", default=os.getenv("HOST", "127.0.0.1"))
    parser.add_argument("--port", type=int, default=int(os.getenv("PORT", "5000")))
    parser.add_argument("--group", default=DEFAULT_GROUP, help="группа по умолчанию")
    parser.add_argument("--open", action="store_true", help="открыть браузер")
    parser.add_argument("--debug", action="store_true", help="режим отладки Flask")
    parser.add_argument("--prod", action="store_true",
                        help="production-сервер waitress вместо сервера разработки "
                             "(нужен pip install -r requirements-prod.txt)")
    args = parser.parse_args(argv)

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s  %(levelname)-7s %(name)s: %(message)s",
        datefmt="%H:%M:%S",
    )

    # Группа из --group имеет приоритет над переменной окружения.
    if args.group:
        app.config["DEFAULT_GROUP"] = args.group

    url = f"http://{'127.0.0.1' if args.host in {'0.0.0.0', '::'} else args.host}:{args.port}/"
    print("\n  Расписание УКРТБ — локальный просмотр")
    print(f"  Группа по умолчанию: {args.group}")
    print(f"  Откройте в браузере: {url}\n")

    if args.open:
        threading.Timer(1.2, lambda: webbrowser.open(url)).start()

    if args.prod:
        # Для публичного доступа: сервер разработки Flask для этого не годится.
        print("  Режим публикации: waitress (см. также python wsgi.py)\n")
        from runner import serve_forever
        return serve_forever(app, host=args.host, port=args.port, threads=8)

    app.run(host=args.host, port=args.port, debug=args.debug, threaded=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
