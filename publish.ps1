<#
    Публикация проекта на GitHub одной командой.

    Запуск из каталога проекта:

        powershell -ExecutionPolicy Bypass -File publish.ps1
        powershell -ExecutionPolicy Bypass -File publish.ps1 -RepoName другое-имя
        powershell -ExecutionPolicy Bypass -File publish.ps1 -Private

    Что делает скрипт:
      1. находит git и gh (в PATH или в стандартных местах установки);
      2. проверяет, что вы вошли в GitHub (иначе подскажет, как войти);
      3. создаёт репозиторий и отправляет туда коммиты;
      4. печатает, что осталось сделать в Render для публичного адреса.

    Скрипт можно запускать повторно: если репозиторий уже есть, он просто
    отправит в него новые коммиты.
#>
[CmdletBinding()]
param(
    [string]$RepoName = "ukrtb-schedule",
    [string]$Description = "Просмотр расписания группы КСК-40 (УКРТБ): Flask + публичный API портала",
    [switch]$Private
)

$ErrorActionPreference = "Continue"
Set-Location -LiteralPath $PSScriptRoot

# Важно: git и gh пишут прогресс в stderr. При $ErrorActionPreference = "Stop"
# PowerShell превращает любой такой вывод в исключение, и скрипт падает на
# ровном месте. Поэтому ошибки разбираем сами — по $LASTEXITCODE.

function Find-Tool {
    param([string]$Name, [string[]]$Fallbacks)
    $cmd = Get-Command $Name -ErrorAction SilentlyContinue
    if ($cmd) { return $cmd.Source }
    foreach ($path in $Fallbacks) {
        if (Test-Path -LiteralPath $path) { return $path }
    }
    return $null
}

$git = Find-Tool -Name "git" -Fallbacks @(
    "C:\Program Files\Git\cmd\git.exe",
    "$env:LOCALAPPDATA\Programs\Git\cmd\git.exe"
)
$gh = Find-Tool -Name "gh" -Fallbacks @(
    "C:\Program Files\GitHub CLI\gh.exe",
    "$env:LOCALAPPDATA\Programs\GitHub CLI\gh.exe"
)

if (-not $git) {
    Write-Host "Не найден git. Установите: winget install --id Git.Git -e" -ForegroundColor Red
    exit 1
}
if (-not $gh) {
    Write-Host "Не найден gh. Установите: winget install --id GitHub.cli -e" -ForegroundColor Red
    exit 1
}

Write-Host "git: $(& $git --version)"
Write-Host "gh : $(& $gh --version | Select-Object -First 1)"

# --- 1. Проверяем вход в GitHub -------------------------------------------

& $gh auth status 2>$null | Out-Null
if ($LASTEXITCODE -ne 0) {
    Write-Host ""
    Write-Host "Вы не вошли в GitHub. Выполните и подтвердите вход в браузере:" -ForegroundColor Yellow
    Write-Host "    gh auth login --hostname github.com --git-protocol https --web"
    Write-Host ""
    Write-Host "После подтверждения запустите этот скрипт снова."
    exit 2
}

$login = (& $gh api user --jq ".login").Trim()
$userId = (& $gh api user --jq ".id").Trim()
Write-Host "аккаунт: $login" -ForegroundColor Green

# --- 2. Локальный репозиторий и коммит ------------------------------------

if (-not (Test-Path -LiteralPath ".git")) {
    Write-Host "Инициализирую репозиторий..."
    & $git init -b main | Out-Null
}
# Канонический noreply-адрес GitHub: коммиты привяжутся к вашему аккаунту.
& $git config user.name  $login | Out-Null
& $git config user.email "$userId+$login@users.noreply.github.com" | Out-Null
& $git config core.quotepath false | Out-Null
& $git config core.autocrlf false | Out-Null

& $git add -A
& $git diff --cached --quiet
if ($LASTEXITCODE -ne 0) {
    & $git commit -q -m "Обновление расписания УКРТБ"
    Write-Host "Создан коммит с изменениями."
} else {
    Write-Host "Незакоммиченных изменений нет."
}

# --- 3. Репозиторий на GitHub и отправка ----------------------------------

$visibility = if ($Private) { "--private" } else { "--public" }

& $gh repo view "$login/$RepoName" 2>$null | Out-Null
if ($LASTEXITCODE -eq 0) {
    Write-Host "Репозиторий $login/$RepoName уже существует — отправляю коммиты."
    & $git remote get-url origin 2>$null | Out-Null
    if ($LASTEXITCODE -ne 0) {
        & $git remote add origin "https://github.com/$login/$RepoName.git"
    }
    & $git push -u origin main
    if ($LASTEXITCODE -ne 0) { Write-Host "Не удалось отправить коммиты." -ForegroundColor Red; exit 1 }
} else {
    Write-Host "Создаю репозиторий $login/$RepoName ..."
    & $gh repo create $RepoName $visibility --source . --remote origin --push --description $Description
    if ($LASTEXITCODE -ne 0) { Write-Host "Не удалось создать репозиторий." -ForegroundColor Red; exit 1 }
}

$repoUrl = "https://github.com/$login/$RepoName"
Write-Host ""
Write-Host "Готово: $repoUrl" -ForegroundColor Green

# --- 4. Что осталось сделать руками ---------------------------------------

Write-Host ""
Write-Host "Осталось получить публичный адрес (2 минуты, нужен вход в Render):" -ForegroundColor Cyan
Write-Host "  1. https://render.com -> войти через GitHub"
Write-Host "  2. New -> Blueprint -> выбрать репозиторий $RepoName"
Write-Host "  3. Render прочитает render.yaml и соберёт сервис (2-4 минуты)"
Write-Host "  4. Адрес будет вида https://$RepoName.onrender.com"
Write-Host ""
Write-Host "Свой домен: Render -> Settings -> Custom Domain, затем CNAME у регистратора."
Write-Host "Подробности — в DEPLOY.md"
