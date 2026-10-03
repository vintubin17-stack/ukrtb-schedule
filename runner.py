# -*- coding: utf-8 -*-
"""Запуск Flask-приложения под production-WSGI-сервером waitress.

Модуль вынесен отдельно, чтобы одним и тем же кодом пользовались и
``python app.py --prod``, и ``python wsgi.py`` (точка входа для хостингов).
Если бы логику запуска содержал ``wsgi.py``, то ``app.py --prod`` при импорте
создал бы второй экземпляр приложения: при запуске ``python app.py`` модуль
называется ``__main__``, и ``from app import app`` выполнил бы файл заново.

Почему не CLI ``waitress-serve``: в исходниках waitress нет обработчиков
сигналов, поэтому SIGTERM она игнорирует. Docker, Render, Railway и systemd
шлют именно SIGTERM — без своего обработчика процесс ждёт таймаут и получает
SIGKILL, обрывая незавершённые запросы.
"""

from __future__ import annotations

import logging
import signal
import threading

LOGGER = logging.getLogger("ukrtb.runner")


def serve_forever(application, host: str = "0.0.0.0", port: int = 8000,
                  threads: int = 8) -> int:
    """Поднимает waitress и корректно останавливается по SIGTERM/SIGINT.

    Возвращает код возврата процесса: 0 — штатная остановка, 1 — нет waitress.
    """
    try:
        from waitress import create_server
    except ImportError:
        LOGGER.error(
            "Не установлен waitress. Выполните: pip install -r requirements-prod.txt"
        )
        return 1

    server = create_server(application, host=host, port=port, threads=threads)
    stop = threading.Event()

    def handle_signal(signum, _frame):
        LOGGER.info("Получен сигнал %s — останавливаю сервер", signum)
        stop.set()

    # Обработчики сигналов можно ставить только из главного потока.
    for sig in (signal.SIGTERM, signal.SIGINT):
        try:
            signal.signal(sig, handle_signal)
        except (ValueError, OSError):  # pragma: no cover - экзотические платформы
            LOGGER.warning("Не удалось подписаться на сигнал %s", sig)

    worker = threading.Thread(target=server.run, name="waitress", daemon=True)
    worker.start()

    print(f"  Сервер запущен на http://{host}:{port}/ (потоков: {threads})")
    print("  Остановка — Ctrl+C или SIGTERM.\n")

    try:
        while not stop.is_set():
            stop.wait(0.5)
    except KeyboardInterrupt:  # pragma: no cover - подстраховка
        pass
    finally:
        server.close()
        worker.join(timeout=5)

    print("  Сервер остановлен.")
    return 0
