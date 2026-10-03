# -*- coding: utf-8 -*-
"""Точка входа для production-WSGI-сервера (её указывают хостинги).

Запуск::

    python wsgi.py                     # порт из PORT, по умолчанию 8000
    PORT=9000 python wsgi.py

Альтернатива для любых WSGI-инструментов (без штатной обработки SIGTERM)::

    waitress-serve --host=0.0.0.0 --port=8000 --threads=8 wsgi:application
    gunicorn --workers 2 --threads 4 --bind 0.0.0.0:8000 wsgi:application

Логика запуска живёт в ``runner.py`` — см. комментарий там о том, почему
``waitress-serve`` напрямую не подходит для контейнеров.
"""

from __future__ import annotations

import os

from app import app as application
from runner import serve_forever

#: WSGI-совместимое имя приложения (его ищут waitress/gunicorn).
wsgi_app = application


def main() -> int:
    return serve_forever(
        application,
        host=os.getenv("HOST", "0.0.0.0"),
        port=int(os.getenv("PORT", "8000")),
        threads=int(os.getenv("UKRTB_THREADS", "8")),
    )


if __name__ == "__main__":
    raise SystemExit(main())
