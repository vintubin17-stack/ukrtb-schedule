# Образ для публикации расписания УКРТБ.
#
# Сборка и запуск:
#   docker build -t ukrtb-schedule .
#   docker run -d --name ukrtb -p 8000:8000 -v ukrtb-cache:/app/data/cache ukrtb-schedule
#
# Готовый образ самодостаточен: подходит для Render, Railway, Fly.io,
# Timeweb Cloud, Selectel и любого VPS с Docker.

FROM python:3.12-slim

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    UKRTB_CACHE_DIR=/app/data/cache \
    UKRTB_CACHE_TTL=900 \
    UKRTB_REFRESH_COOLDOWN=60 \
    PORT=8000

WORKDIR /app

# Сначала зависимости — так слой кэшируется и пересборка идёт быстрее.
COPY requirements.txt requirements-prod.txt ./
RUN pip install --no-cache-dir -r requirements-prod.txt

COPY . .

# Каталог кэша создаём и отдаём пользователю ДО объявления VOLUME:
# всё, что меняется после VOLUME, в образ не попадает и том получит
# root-овые права, а приложение работает под uid 1000.
RUN mkdir -p /app/data/cache && chown -R 1000:1000 /app

# Кэш расписания живёт в томе: данные переживают перезапуск контейнера.
VOLUME ["/app/data/cache"]

# Работаем от непривилегированного пользователя (числовой uid надёжнее
# useradd: не зависит от наличия пакета passwd в базовом образе).
USER 1000:1000

EXPOSE 8000

# Проверка живости без curl: в slim-образе его нет. Порт берём из PORT.
HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
    CMD python -c "import os,sys,urllib.request; sys.exit(0 if urllib.request.urlopen('http://127.0.0.1:' + os.getenv('PORT', '8000') + '/api/health', timeout=4).status == 200 else 1)"

# Порт 8000 по умолчанию; Render и Railway подставляют свой через $PORT.
# Запускаем через wsgi.py, а не через CLI waitress-serve: только так
# обрабатывается SIGTERM, который платформы шлют при перезапуске.
CMD ["python", "wsgi.py"]
