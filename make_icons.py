# -*- coding: utf-8 -*-
"""Генерация иконок приложения (PWA и ярлык на домашнем экране iPhone).

Запуск::

    python make_icons.py

Результат — файлы в ``static/icons/``:

    icon-192.png          иконка для манифеста
    icon-512.png          иконка для манифеста (крупная)
    apple-touch-icon.png  иконка ярлыка iOS (180x180)
    favicon.svg           иконка вкладки браузера

Иконки рисуются кодом, а не берутся готовыми: так их можно пересобрать
в любой момент и не хранить бинарники неизвестного происхождения.
"""

from __future__ import annotations

import sys
from pathlib import Path

from PIL import Image, ImageDraw

PROJECT_ROOT = Path(__file__).resolve().parent
OUT_DIR = PROJECT_ROOT / "static" / "icons"

BRAND = (2, 132, 199)          # небесно-синий, как кнопки интерфейса
BRAND_DARK = (3, 105, 161)
PAPER = (255, 255, 255)
ACCENT = (56, 189, 248)        # «сегодня» на календаре
GRID = (203, 213, 225)
RING = (224, 242, 254)


def draw_icon(size: int, padding_ratio: float = 0.0) -> Image.Image:
    """Рисует иконку-календарь размером ``size`` x ``size``."""
    # Рисуем в четырёхкратном размере и уменьшаем — так края получаются гладкими.
    scale = 4
    canvas = size * scale
    img = Image.new("RGBA", (canvas, canvas), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)

    pad = int(canvas * padding_ratio)
    body = canvas - pad * 2
    radius = int(body * 0.22)

    # Фон
    draw.rounded_rectangle(
        [pad, pad, pad + body, pad + body],
        radius=radius,
        fill=BRAND,
    )
    # Мягкий блик сверху
    draw.rounded_rectangle(
        [pad, pad, pad + body, pad + int(body * 0.5)],
        radius=radius,
        fill=BRAND_DARK,
    )

    # Лист календаря
    sheet_w = int(body * 0.66)
    sheet_h = int(body * 0.62)
    sheet_x = pad + (body - sheet_w) // 2
    sheet_y = pad + int(body * 0.26)
    sheet_r = int(sheet_w * 0.10)
    draw.rounded_rectangle(
        [sheet_x, sheet_y, sheet_x + sheet_w, sheet_y + sheet_h],
        radius=sheet_r,
        fill=PAPER,
    )

    # Шапка листа
    header_h = int(sheet_h * 0.24)
    draw.rounded_rectangle(
        [sheet_x, sheet_y, sheet_x + sheet_w, sheet_y + header_h + sheet_r],
        radius=sheet_r,
        fill=ACCENT,
    )
    draw.rectangle(
        [sheet_x, sheet_y + header_h, sheet_x + sheet_w, sheet_y + header_h + sheet_r],
        fill=ACCENT,
    )

    # Кольца-пружинки сверху
    ring_w = int(sheet_w * 0.10)
    ring_h = int(sheet_h * 0.20)
    for offset in (0.22, 0.78):
        cx = sheet_x + int(sheet_w * offset)
        draw.rounded_rectangle(
            [cx - ring_w // 2, sheet_y - int(ring_h * 0.55),
             cx + ring_w // 2, sheet_y + int(ring_h * 0.45)],
            radius=ring_w // 2,
            fill=BRAND_DARK,
        )

    # Сетка дней: 3 столбца x 2 строки, одна клетка «сегодня»
    grid_top = sheet_y + header_h + int(sheet_h * 0.14)
    cell = int(sheet_w * 0.17)
    gap_x = int(sheet_w * 0.11)
    gap_y = int(sheet_h * 0.16)
    total_w = cell * 3 + gap_x * 2
    start_x = sheet_x + (sheet_w - total_w) // 2
    for row in range(2):
        for col in range(3):
            x = start_x + col * (cell + gap_x)
            y = grid_top + row * (cell + gap_y)
            color = BRAND if (row == 0 and col == 1) else GRID
            draw.rounded_rectangle([x, y, x + cell, y + cell],
                                   radius=int(cell * 0.28), fill=color)

    return img.resize((size, size), Image.LANCZOS)


FAVICON_SVG = """<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 64 64">
  <rect width="64" height="64" rx="14" fill="#0284c7"/>
  <rect x="11" y="18" width="42" height="34" rx="5" fill="#ffffff"/>
  <path d="M11 23a5 5 0 0 1 5-5h32a5 5 0 0 1 5 5v6H11z" fill="#38bdf8"/>
  <rect x="17" y="13" width="5" height="11" rx="2.5" fill="#0369a1"/>
  <rect x="42" y="13" width="5" height="11" rx="2.5" fill="#0369a1"/>
  <rect x="19" y="34" width="7" height="7" rx="2" fill="#cbd5e1"/>
  <rect x="28.5" y="34" width="7" height="7" rx="2" fill="#0284c7"/>
  <rect x="38" y="34" width="7" height="7" rx="2" fill="#cbd5e1"/>
  <rect x="19" y="44" width="7" height="7" rx="2" fill="#cbd5e1"/>
  <rect x="28.5" y="44" width="7" height="7" rx="2" fill="#cbd5e1"/>
  <rect x="38" y="44" width="7" height="7" rx="2" fill="#cbd5e1"/>
</svg>
"""


def main() -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")

    OUT_DIR.mkdir(parents=True, exist_ok=True)

    # Ярлык iOS не любит прозрачность и скругления — рисуем квадрат,
    # iOS сам скруглит углы.
    draw_icon(180, padding_ratio=0.0).convert("RGB").save(
        OUT_DIR / "apple-touch-icon.png", "PNG", optimize=True)

    for size in (192, 512):
        draw_icon(size, padding_ratio=0.0).convert("RGB").save(
            OUT_DIR / f"icon-{size}.png", "PNG", optimize=True)

    # Маска для Android: иконка с отступом
    draw_icon(512, padding_ratio=0.10).convert("RGB").save(
        OUT_DIR / "icon-maskable-512.png", "PNG", optimize=True)

    (OUT_DIR / "favicon.svg").write_text(FAVICON_SVG, encoding="utf-8", newline="\n")

    for path in sorted(OUT_DIR.iterdir()):
        print(f"  {path.name:26} {path.stat().st_size:>8} байт")
    print(f"\n  Каталог: {OUT_DIR}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
