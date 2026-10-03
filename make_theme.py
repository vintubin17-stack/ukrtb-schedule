# -*- coding: utf-8 -*-
"""Генерация палитры тем (светлая и тёмная) в ``static/theme.css``.

Зачем скрипт, а не готовый CSS: цвета берутся из самого Tailwind, поэтому
светлая тема гарантированно совпадает с той, что рисует CDN, а тёмная —
её аккуратная инверсия, а не подобранные на глаз значения.

Как это работает
----------------
Интерфейс свёрстан утилитами вида ``bg-slate-100`` / ``text-slate-900``.
Мы не переписываем разметку, а подменяем сами цвета палитры на CSS-переменные
(см. ``tailwind.config`` в шаблоне). Тогда переключение одной переменной
перекрашивает весь интерфейс.

Правило инверсии для цветных оттенков: светлый фон становится тёмным
(50 → 950, 100 → 900, 200 → 800, 300 → 700), а тёмный текст — светлым
(700 → 300, 800 → 200, 900 → 100). Насыщенные 500/600 остаются на месте:
это кнопки и точки-индикаторы, они одинаково хороши в обеих темах.

Запуск::

    python make_theme.py
"""

from __future__ import annotations

import re
import sys
import urllib.request
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent
OUT_FILE = PROJECT_ROOT / "static" / "theme.css"

TAILWIND_CDN = "https://cdn.tailwindcss.com/3.4.16"

#: Оттенки, которые встречаются в разметке.
TINTED_HUES = ["sky", "rose", "amber", "emerald", "violet", "indigo", "blue"]

SHADES = [50, 100, 200, 300, 400, 500, 600, 700, 800, 900, 950]

#: Инверсия для цветных оттенков.
TINTED_INVERSION = {
    50: 950, 100: 900, 200: 800, 300: 700, 400: 600,
    500: 500, 600: 600,
    700: 300, 800: 200, 900: 100, 950: 50,
}

#: Для серого инверсия своя: он отвечает за поверхности и текст,
#: и важна не симметрия, а читаемость.
SLATE_INVERSION = {
    50: 700,    # мягкие подложки и наведение — светлее карточки
    100: 900,   # фон страницы — темнее карточки
    200: 700,   # границы и разделители
    300: 600,
    400: 400,   # приглушённый текст
    500: 400,
    600: 300,   # вторичный текст
    700: 200,
    800: 100,
    900: 50,    # заголовки
    950: 950,
}


def fetch_palette() -> dict[str, dict[int, str]]:
    """Скачивает Tailwind и достаёт из него значения по умолчанию."""
    print(f"  скачиваю {TAILWIND_CDN} ...")
    # CDN отвечает 403 на запросы без браузерного User-Agent.
    request = urllib.request.Request(
        TAILWIND_CDN,
        headers={
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                          "AppleWebKit/537.36 (KHTML, like Gecko) "
                          "Chrome/124.0 Safari/537.36",
            "Accept": "*/*",
        },
    )
    with urllib.request.urlopen(request, timeout=60) as response:
        js = response.read().decode("utf-8", errors="replace")
    print(f"  получено {len(js) // 1024} КБ")

    palette: dict[str, dict[int, str]] = {}
    for hue in ["slate"] + TINTED_HUES:
        match = re.search(rf"\b{hue}:\{{([^{{}}]*)\}}", js)
        if not match:
            raise SystemExit(f"не нашёл палитру для «{hue}» в Tailwind")
        pairs = dict(re.findall(r"(\d{2,3}):\"(#[0-9a-fA-F]{6})\"", match.group(1)))
        if not pairs:
            raise SystemExit(f"пустая палитра для «{hue}»")
        palette[hue] = {int(k): v for k, v in pairs.items()}
        print(f"    {hue}: {len(palette[hue])} оттенков")

    return palette


def rgb(hex_value: str) -> str:
    """#f8fafc → «248 250 252»: так Tailwind умеет применять прозрачность."""
    value = hex_value.lstrip("#")
    return " ".join(str(int(value[i:i + 2], 16)) for i in (0, 2, 4))


def build_css(palette: dict[str, dict[int, str]]) -> str:
    light_lines: list[str] = []
    dark_lines: list[str] = []

    # Карточки: в светлой теме белые, в тёмной — приподнятая поверхность.
    light_lines.append(f"  --c-card: {rgb('#ffffff')};")
    dark_lines.append(f"  --c-card: {rgb(palette['slate'][800])};")

    for shade in SHADES:
        value = palette["slate"].get(shade)
        if not value:
            continue
        light_lines.append(f"  --c-slate-{shade}: {rgb(value)};")

    for shade, source in SLATE_INVERSION.items():
        value = palette["slate"].get(source)
        if not value:
            continue
        dark_lines.append(f"  --c-slate-{shade}: {rgb(value)};")

    for hue in TINTED_HUES:
        for shade in SHADES:
            value = palette[hue].get(shade)
            if not value:
                continue
            light_lines.append(f"  --c-{hue}-{shade}: {rgb(value)};")
            target = palette[hue].get(TINTED_INVERSION[shade])
            dark_lines.append(f"  --c-{hue}-{shade}: {rgb(target or value)};")

    return (
        "/* ------------------------------------------------------------------\n"
        "   Палитра тем. Файл генерируется скриптом make_theme.py —\n"
        "   правьте его, а не этот CSS.\n"
        "\n"
        "   Значения — это каналы RGB, а не hex: так Tailwind применяет\n"
        "   прозрачность (bg-slate-50/70 и подобные).\n"
        "   ------------------------------------------------------------------ */\n"
        "\n"
        ":root {\n"
        "  color-scheme: light;\n"
        + "\n".join(light_lines) + "\n"
        "}\n"
        "\n"
        "html.dark {\n"
        "  color-scheme: dark;\n"
        + "\n".join(dark_lines) + "\n"
        "}\n"
    )


def main() -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")

    palette = fetch_palette()
    css = build_css(palette)
    OUT_FILE.write_text(css, encoding="utf-8", newline="\n")

    print(f"\n  записано: {OUT_FILE}")
    print(f"  строк: {css.count(chr(10))}")
    print(f"  переменных: {css.count('--c-')}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
