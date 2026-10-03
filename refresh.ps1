<#
    Обновление статической версии расписания на GitHub Pages.

    Запуск из каталога проекта:

        powershell -ExecutionPolicy Bypass -File refresh.ps1
        powershell -ExecutionPolicy Bypass -File refresh.ps1 -Back 14 -Ahead 21
        powershell -ExecutionPolicy Bypass -File refresh.ps1 -NoPush

    Что делает:
      1. забирает расписание с портала колледжа (это работает только
         с российских IP, поэтому и запускается на вашем компьютере, а не
         на зарубежном хостинге);
      2. собирает каталог docs/ — готовую страницу и data.json;
      3. коммитит и отправляет на GitHub, после чего GitHub Pages
         обновляет сайт сам (обычно за минуту).

    Автоматизация: задание в планировщике Windows (запускать от текущего пользователя).
        schtasks /create /tn "Расписание УКРТБ" /sc hourly /mo 3 /tr "powershell -ExecutionPolicy Bypass -File refresh.ps1 -Quiet"
#>
[CmdletBinding()]
param(
    [string]$Group = "КСК-40",
    [int]$Back = 7,
    [int]$Ahead = 10,
    [int]$Days = 3,
    [switch]$NoPush,
    [switch]$Quiet
)

$ErrorActionPreference = "Continue"
Set-Location -LiteralPath $PSScriptRoot

function Find-Tool {
    param([string]$Name, [string[]]$Fallbacks)
    $cmd = Get-Command $Name -ErrorAction SilentlyContinue
    if ($cmd) { return $cmd.Source }
    foreach ($path in $Fallbacks) {
        if (Test-Path -LiteralPath $path) { return $path }
    }
    return $null
}

# Python ищем в таком порядке: виртуальное окружение проекта, затем системный.
$python = $null
foreach ($candidate in @(
    (Join-Path $PSScriptRoot ".venv\Scripts\python.exe"),
    "C:\Python314\python.exe",
    "C:\Python313\python.exe",
    "C:\Python312\python.exe"
)) {
    if (Test-Path -LiteralPath $candidate) { $python = $candidate; break }
}
if (-not $python) { $python = Find-Tool -Name "python" -Fallbacks @() }
if (-not $python) {
    Write-Host "Не найден Python. Установите: winget install --id Python.Python.3.12 -e" -ForegroundColor Red
    exit 1
}

$git = Find-Tool -Name "git" -Fallbacks @("C:\Program Files\Git\cmd\git.exe")

if (-not $Quiet) { Write-Host "python: $python" }

# --- 1-2. Сборка статики ---------------------------------------------------

$buildArgs = @(
    (Join-Path $PSScriptRoot "build_static.py"),
    "--group", $Group,
    "--back", $Back,
    "--ahead", $Ahead,
    "--days", $Days
)
if ($Quiet) { $buildArgs += "-q" }

& $python @buildArgs
if ($LASTEXITCODE -ne 0) {
    Write-Host "Сборка не удалась — на GitHub ничего не отправлено." -ForegroundColor Red
    exit 1
}

if ($NoPush) {
    Write-Host "Готово (без публикации): $PSScriptRoot\docs" -ForegroundColor Green
    exit 0
}

# --- 3. Публикация ---------------------------------------------------------
#
# Сравниваем отпечаток расписания (docs/data.sig), а не сами файлы: отметка
# времени сборки меняется при каждом запуске, и по ней одной публиковать
# новый коммит смысла нет.

if (-not $git) {
    Write-Host "Не найден git — не могу опубликовать. Установите: winget install --id Git.Git -e" -ForegroundColor Red
    exit 1
}

$sigFile = Join-Path $PSScriptRoot "docs\data.sig"
$newSig = if (Test-Path -LiteralPath $sigFile) {
    (Get-Content -LiteralPath $sigFile -Raw -Encoding UTF8).Trim()
} else { "" }
$oldSig = (((& $git show "HEAD:docs/data.sig" 2>$null) -join "`n")).Trim()

if ($newSig -and $newSig -eq $oldSig) {
    # Расписание не изменилось: возвращаем файлы данных к версии из git,
    # чтобы в дереве не осталось изменений только из-за отметки времени.
    $dataFiles = @("docs/data.sig", "docs/data.json") |
        Where-Object { Test-Path -LiteralPath (Join-Path $PSScriptRoot $_) }
    & $git checkout -- $dataFiles 2>$null
    if (-not $Quiet) { Write-Host "Расписание не изменилось — публикация не нужна." }
    exit 0
}

& $git add docs
& $git diff --cached --quiet
if ($LASTEXITCODE -eq 0) {
    if (-not $Quiet) { Write-Host "Изменений в расписании нет — публиковать нечего." }
    exit 0
}

& $git add docs
& $git diff --cached --quiet
if ($LASTEXITCODE -eq 0) {
    if (-not $Quiet) { Write-Host "Изменений в расписании нет — публиковать нечего." }
    exit 0
}

$stamp = Get-Date -Format "dd.MM.yyyy HH:mm"
& $git -c user.name="vintubin17-stack" -c user.email="238513235+vintubin17-stack@users.noreply.github.com" `
    commit -q -m "Обновление расписания: $stamp"
if ($LASTEXITCODE -ne 0) {
    Write-Host "Не удалось создать коммит." -ForegroundColor Red
    exit 1
}

& $git push -q
if ($LASTEXITCODE -ne 0) {
    Write-Host "Не удалось отправить на GitHub." -ForegroundColor Red
    exit 1
}

Write-Host "Опубликовано: https://vintubin17-stack.github.io/ukrtb-schedule/" -ForegroundColor Green
Write-Host "GitHub Pages обновит страницу в течение минуты."
