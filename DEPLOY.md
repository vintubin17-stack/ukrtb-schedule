# Публикация расписания УКРТБ в интернете

> ## ⚠️ Прочитайте это первым
>
> **Зарубежный хостинг для этого приложения не подходит.** Проверка
> доступности портала `study.ukrtb.ru` из 17 стран мира: американские узлы
> отвечают за 0.6 с, а Германия, Нидерланды, Польша, Канада, Япония, Турция
> и другие получают `Connection timed out`. Развёрнутый на Render (Франкфурт)
> экземпляр поэтому отдаёт только демонстрационные данные.
>
> **Рабочий вариант — статическая версия на GitHub Pages** (раздел ниже):
> расписание забирается на вашем компьютере, где портал открыт, и
> публикуется готовой страницей. Она раздаётся по всему миру и от
> геоблокировки не зависит. Публичный адрес:
> **<https://vintubin17-stack.github.io/ukrtb-schedule/>**

---

## Рабочий вариант: статика на GitHub Pages

Уже настроено, от вас ничего не требуется — но полезно знать, как это
устроено и как обновлять.

```
компьютер (портал доступен)      GitHub              посетители
  build_static.py   ──push──▶  docs/  ──Pages──▶  https://…github.io/ukrtb-schedule/
  refresh.ps1
```

* **Сборка:** `build_static.py` забирает 18 дней (7 назад, 10 вперёд) и
  складывает страницу и `data.json` в каталог `docs/`.
* **Публикация:** `refresh.ps1` собирает и отправляет результат на GitHub.
  Pages подхватывает изменения за минуту.
* **Автоматизация:** задание планировщика Windows
  **«Расписание УКРТБ (обновление)»** запускает `refresh.ps1` раз в 3 часа,
  пока компьютер включён. Коммит появляется только при реальном изменении
  расписания.

Ручное обновление и управление заданием:

```powershell
powershell -ExecutionPolicy Bypass -File refresh.ps1            # обновить сейчас
powershell -ExecutionPolicy Bypass -File refresh.ps1 -Back 14 -Ahead 21
powershell -ExecutionPolicy Bypass -File refresh.ps1 -NoPush    # только собрать

Get-ScheduledTask -TaskName "Расписание УКРТБ (обновление)"      # состояние
Unregister-ScheduledTask -TaskName "Расписание УКРТБ (обновление)" -Confirm:$false  # выключить
```

Ограничение варианта: страница обновляется, только когда включён компьютер.
На странице всегда видно, когда данные собраны.

---

## Вариант с сервером (только если портал вам доступен)

Всё для этого в проекте есть (`Dockerfile`, `render.yaml`, `fly.toml`),
но помните про геоблокировку: сервер должен стоять там, откуда портал
открывается. Для проверки прямо с хостинга есть эндпоинт `/api/diagnose` —
он покажет, на каком шаге рвётся связь: DNS, TCP или HTTPS.

Пошаговая инструкция для варианта **Docker-хостинг + GitHub**. Файлы
`Dockerfile`, `render.yaml` и `fly.toml` уже лежат в проекте — дописывать
ничего не нужно.

Коротко: загружаете проект на GitHub, подключаете репозиторий к хостингу,
получаете HTTPS-адрес вида `https://ukrtb-schedule.onrender.com`, при желании
привязываете свой домен.

---

## Шаг 0. Что понадобится

* аккаунт на <https://github.com> (бесплатно);
* аккаунт на хостинге: <https://render.com> (бесплатно) — вариант по умолчанию;
* *необязательно*: свой домен (~200–800 ₽/год), если не хотите адрес
  вида `*.onrender.com`.

Знать Docker не нужно: хостинг соберёт образ сам из `Dockerfile`.

---

## Шаг 1. Загрузить проект на GitHub

### Самый быстрый путь: скрипт `publish.ps1`

В проекте лежит готовый скрипт — он сам войдёт в аккаунт (если нужно),
создаст репозиторий и отправит туда коммиты:

```powershell
# из каталога проекта
powershell -ExecutionPolicy Bypass -File publish.ps1
```

Если Git и GitHub CLI ещё не установлены:

```powershell
winget install --id Git.Git -e
winget install --id GitHub.cli -e
gh auth login --hostname github.com --git-protocol https --web
```

В конце скрипт напечатает ссылку на репозиторий и подскажет шаги для Render.

### Вручную

На этом компьютере **Git и GitHub Desktop не установлены**, поэтому выберите
любой из трёх способов.

#### Вариант А. Установить Git (рекомендуется)

```powershell
winget install --id Git.Git -e
```

После установки **откройте новое окно терминала** (PATH обновится) и в каталоге
проекта выполните:

```bash
git init
git add .
git commit -m "Расписание УКРТБ: локальный просмотр + публикация"
git branch -M main
```

Создайте на GitHub пустой репозиторий (без README и .gitignore) и свяжите его:

```bash
git remote add origin https://github.com/ВАШ_ЛОГИН/ukrtb-schedule.git
git push -u origin main
```

`.gitignore` уже исключает `.venv/`, `__pycache__/` и `data/cache/`, поэтому
в репозиторий не попадут ни кэш, ни виртуальное окружение.

### Вариант Б. GitHub Desktop

```powershell
winget install --id GitHub.GitHubDesktop -e
```

Затем: **File → Add local repository** → укажите каталог `ukrtb-schedule` →
**Publish repository**. Git внутри GitHub Desktop уже есть, ставить отдельно
не нужно.

### Вариант В. Загрузить через сайт GitHub

Без установки программ: создайте на GitHub пустой репозиторий, нажмите
**Add file → Upload files** и перетащите файлы проекта.

⚠️ При этом `.gitignore` **не действует**: не перетаскивайте каталоги
`.venv/`, `__pycache__/` и `data/cache/` — это сотни мегабайт мусора.
Загружать нужно только: `app.py`, `wsgi.py`, `runner.py`, `schedule_client.py`,
`requirements.txt`, `requirements-prod.txt`, `Dockerfile`, `.dockerignore`,
`render.yaml`, `fly.toml`, каталоги `templates/`, `static/`, `data/sample_schedule.json`.

Проверка, что всё попало: в репозитории должны быть видны `Dockerfile` и
`requirements-prod.txt` — именно по `Dockerfile` хостинг поймёт, как собрать
приложение.

---

## Шаг 2А. Render (рекомендуемый вариант)

1. Зарегистрируйтесь на <https://render.com> через GitHub.
2. **New → Blueprint** → выберите свой репозиторий.
3. Render сам прочитает `render.yaml` и создаст сервис с нужными переменными.
4. Дождитесь сборки (первая занимает 2–4 минуты).
5. Откройте выданный адрес — расписание уже работает.

Бесплатный тариф «засыпает» после 15 минут без посетителей. Первый запрос
после паузы поднимает контейнер: 20–50 секунд. Это нормально для расписания.

Привязка своего домена: **Settings → Custom Domain → Add Custom Domain**.
Render выдаст CNAME-запись, которую нужно прописать у регистратора домена,
и сам выпустит бесплатный сертификат Let's Encrypt.

## Шаг 2Б. Railway

1. <https://railway.app> → **New Project → Deploy from GitHub repo**.
2. Railway сам найдёт `Dockerfile`. Порт подставляется через переменную `PORT`,
   контейнер её читает — настраивать ничего не нужно.
3. **Settings → Networking → Generate Domain** для публичного адреса.

## Шаг 2В. Fly.io

```bash
# установите flyctl: https://fly.io/docs/flyctl/install/
fly auth login
fly launch --no-deploy --copy-config   # подхватит Dockerfile и fly.toml
fly deploy
fly open
```

## Шаг 2Г. Свой VPS с Docker

```bash
git clone https://github.com/ВАШ_ЛОГИН/ukrtb-schedule.git /opt/ukrtb-schedule
cd /opt/ukrtb-schedule
docker build -t ukrtb-schedule .
docker run -d --name ukrtb --restart unless-stopped \
  -p 127.0.0.1:8000:8000 \
  -e UKRTB_CACHE_TTL=900 \
  -e UKRTB_REFRESH_COOLDOWN=60 \
  -v ukrtb-cache:/app/data/cache \
  ukrtb-schedule
```

Дальше ставим nginx как обратный прокси и получаем сертификат:

```bash
sudo apt install -y nginx certbot python3-certbot-nginx
```

```nginx
# /etc/nginx/sites-available/ukrtb
server {
    listen 80;
    server_name schedule.example.ru;

    location / {
        proxy_pass http://127.0.0.1:8000;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
    }
}
```

```bash
sudo ln -s /etc/nginx/sites-available/ukrtb /etc/nginx/sites-enabled/
sudo nginx -t && sudo systemctl reload nginx
sudo certbot --nginx -d schedule.example.ru
```

---

## Шаг 3. Настроить под публичный доступ

Переменные окружения (задаются в панели хостинга):

| Переменная | Значение для публикации | Зачем |
| --- | --- | --- |
| `UKRTB_CACHE_TTL` | `900` | кэш 15 минут: сотня посетителей = одно обращение к порталу |
| `UKRTB_REFRESH_COOLDOWN` | `60` | кнопка «Обновить» не чаще раза в минуту на группу |
| `UKRTB_GROUP` | `КСК-40-23` | группа по умолчанию |
| `UKRTB_TIMEOUT` | `20` | запас на медленный ответ портала |
| `UKRTB_CACHE_DIR` | `/app/data/cache` | каталог кэша внутри контейнера |

Том для кэша (`-v ukrtb-cache:/app/data/cache`, в `fly.toml` — `[mounts]`,
в Render — диск в платном тарифе) важен: без него кэш теряется при каждом
перезапуске и портал опрашивается заново.

---

## Шаг 4. Проверить, что всё живо

```bash
curl https://ваш-адрес/api/health
# {"ok":true,"service":"ukrtb-schedule","group":"КСК-40-23"}

curl "https://ваш-адрес/api/schedule?group=КСК-40&days=3"
```

Если в ответе `"source": "live"` — данные идут с портала. `"cache"` — из кэша,
`"sample"` — портал недоступен и показаны демонстрационные данные (проверьте
`warnings`).

---

## Частые проблемы при деплое

| Симптом | Причина и решение |
| --- | --- |
| Сборка падает на `pip install` | проверьте, что `requirements.txt` и `requirements-prod.txt` попали в репозиторий |
| Сервис поднимается, но «Application failed to respond» | приложение слушает не тот порт: контейнер читает `$PORT`, не задавайте порт жёстко в настройках хостинга |
| Страница открывается, но данных нет | портал недоступен с хостинга или изменилось API — смотрите `/api/schedule`, поле `warnings` |
| Первый запрос идёт 30+ секунд | бесплатный тариф «спит»; это ожидаемо, помогает платный план или пинг раз в 10 минут |
| После перезапуска пошли запросы к порталу | не подключён том для `/app/data/cache` |
| Хочется убрать страницу из поиска | добавьте в `app.py` маршрут `/robots.txt` с `Disallow: /` |

---

## Не забыть

* Расписание принадлежит колледжу. Пометка «не официальный сервис» уже есть
  в подвале страницы — не убирайте её.
* Не уменьшайте `UKRTB_CACHE_TTL` ниже ~600 секунд на публичном адресе:
  кэш — это то, что защищает портал колледжа от потока посетителей.
* Ключ API портала публичный (колледж сам публикует его в своей
  postman-коллекции), поэтому в секретах он не нужен.
