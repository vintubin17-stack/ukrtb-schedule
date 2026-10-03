# iOS-приложение: сборка и TestFlight

Приложение — нативная оболочка (SwiftUI + WKWebView) вокруг той же страницы
расписания. Иконка, запуск без адресной строки, работа без сети, обновление
жестом вниз.

## Что нужно, а что нет

| | |
| --- | --- |
| **Mac** | **не нужен** — сборка идёт на бесплатном macOS-раннере GitHub Actions |
| **Xcode** | не нужен локально |
| **Apple Developer Program** | **нужен, $99/год** — без него TestFlight недоступен никак |
| Аккаунт GitHub | уже есть |

> ⚠️ Проверить сборку заранее не получилось: у автора проекта Windows,
> Xcode и аккаунта Apple Developer нет. Все файлы написаны по официальной
> схеме, но первый запуск CI — это первая настоящая проверка. Если что-то
> не соберётся, журнал сохранится в артефактах запуска (`build-logs`).

## Почему без $99 никак

TestFlight — это сервис Apple для разработчиков. Чтобы в него попасть, нужно:

1. аккаунт Apple Developer Program ($99/год);
2. приложение, зарегистрированное в App Store Connect;
3. подпись сборки сертификатом Apple.

Ни обойти, ни заменить это нельзя. Все «бесплатные» способы (AltStore,
Sideloadly, личная команда Xcode) работают 7 дней, требуют компьютер рядом
с телефоном и не дают ссылку, которую можно просто отправить другу.

**Что можно сделать бесплатно прямо сейчас** — установить сайт как
приложение: <https://vintubin17-stack.github.io/ukrtb-schedule/install.html>.
На iPhone это «Поделиться» → «На экран Домой»: своя иконка, полноэкранный
режим, работа без интернета. Для расписания этого достаточно, и любой
одногруппник справится за 10 секунд. См. также `../DEPLOY.md`.

---

## Путь А: сборка в облаке GitHub (Mac не нужен)

### Шаг 1. Apple Developer Program

Зарегистрируйтесь на <https://developer.apple.com/programs/> (нужны паспортные
данные для физлица, оплата $99/год). Активация занимает от нескольких часов
до двух суток.

### Шаг 2. Приложение в App Store Connect

<https://appstoreconnect.apple.com> → **My Apps** → **+** → **New App**:

* Platform: iOS
* Name: `Расписание КСК-40`
* Primary Language: Russian
* Bundle ID: `ru.ukrtb.schedule` (если такого нет в списке — сначала создайте
  его в <https://developer.apple.com/account/resources/identifiers>)
* SKU: любой, например `ukrtb-schedule`

### Шаг 3. Ключ App Store Connect API

**Users and Access** → **Integrations** → **App Store Connect API** → **+**

* Name: `github-actions`
* Access: **App Manager**

Нажмите **Generate**, скачайте файл `AuthKey_XXXXXXXXXX.p8` — **скачать его
можно только один раз**. Запомните рядом:

* **Key ID** — например `2X9R4HXF34`
* **Issuer ID** — длинный UUID на той же странице
* **Team ID** — 10 символов, видно в <https://developer.apple.com/account>
  (Membership details)

### Шаг 4. Секреты в GitHub

Репозиторий → **Settings** → **Secrets and variables** → **Actions** →
**New repository secret**. Добавьте четыре:

| Имя | Значение |
| --- | --- |
| `ASC_KEY_ID` | Key ID ключа |
| `ASC_ISSUER_ID` | Issuer ID |
| `ASC_KEY_P8` | **всё содержимое** файла `.p8`, вместе со строками `-----BEGIN PRIVATE KEY-----` и `-----END PRIVATE KEY-----` |
| `APPLE_TEAM_ID` | Team ID (10 символов) |

### Шаг 5. Запуск

**Actions** → **iOS → TestFlight** → **Run workflow**.
Либо отправьте тег: `git tag ios-v1.0.0 && git push origin ios-v1.0.0`.

Что произойдёт: GitHub поднимет macOS-раннер, поставит XcodeGen, соберёт
проект, подпишет его (сертификат и профиль Xcode получит сам по ключу API)
и загрузит сборку в TestFlight. Первый запуск: 10–20 минут, плюс Apple
обрабатывает сборку до получаса.

### Шаг 6. Тестировщики

App Store Connect → ваше приложение → **TestFlight**:

* **Internal Testing** — до 100 человек из вашей команды, доступ сразу;
* **External Testing** — до 10 000 человек по публичной ссылке, но первая
  сборка проходит короткую проверку Apple (обычно сутки).

Внутренним тестировщикам достаточно добавить их Apple ID в
**Users and Access**. Внешним — собрать группу и отправить ссылку.

---

## Путь Б: сборка на Mac

Если Mac появится:

```bash
brew install xcodegen
cd ios
xcodegen generate
open Schedule.xcodeproj
```

Дальше в Xcode: выбрать свою команду в **Signing & Capabilities**,
подключить iPhone, нажать Run. Для TestFlight: **Product → Archive →
Distribute App → TestFlight & App Store**.

---

## Что внутри

```
ios/
├── App/
│   ├── ScheduleApp.swift              точка входа
│   ├── ContentView.swift              экран: прогресс, ошибка, «Повторить»
│   ├── WebView.swift                  обёртка WKWebView + pull-to-refresh
│   ├── Info.plist                     имя, ориентации, экспортная лицензия
│   └── Assets.xcassets/AppIcon...     иконка 1024×1024 (без прозрачности)
├── project.yml                        описание проекта для XcodeGen
├── ExportOptions.plist                настройки экспорта в TestFlight
└── README.md                          этот файл
```

Иконка рисуется скриптом `../make_icons.py` (тот же календарь, что у сайта,
в размере 1024×1024) — можно пересобрать в любой момент.

## Честно о рисках

* **Правило 4.2 App Review.** Приложение-обёртка вокруг сайта Apple может
  отклонить как «недостаточную функциональность». Чтобы снизить риск, стоит
  добавить настоящую нативную ценность: локальные уведомления перед парой,
  виджет с расписанием на сегодня, полноценный офлайн-режим в нативном
  интерфейсе. Обёртка для TestFlight проходит всегда, для App Store — как
  повезёт.
* **Данные принадлежат колледжу**, в описании приложения стоит указать, что
  это не официальный сервис.
* **Обновления расписания** подтягиваются с той же страницы, поэтому
  приложение никогда не показывает устаревшие данные дольше, чем сайт.
