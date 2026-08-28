#!/usr/bin/env python3
"""Generate the Tauri desktop icon set (spectrum bars, matching v1 branding).

Writes desktop/src-tauri/icons/{32x32.png,128x128.png,128x128@2x.png,
icon.icns,icon.ico} and a 512 source PNG.
"""
import os
from PIL import Image, ImageDraw

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
ICON_DIR = os.path.join(ROOT, "desktop", "src-tauri", "icons")
os.makedirs(ICON_DIR, exist_ok=True)

BG = (10, 10, 12)
HEIGHTS = (0.30, 0.36, 0.44, 0.58, 0.74, 0.88, 0.97)
COLORS = [(139, 92, 246), (124, 58, 237), (99, 102, 241), (79, 70, 229),
          (67, 56, 202), (55, 48, 163), (49, 46, 129)]


def draw(size):
    img = Image.new("RGBA", (size, size), BG + (255,))
    d = ImageDraw.Draw(img)
    n = len(HEIGHTS)
    margin = size * 0.12
    gap = size * 0.03
    bar_w = (size - 2 * margin - (n - 1) * gap) / n
    base_y = size - margin
    for i, (h, c) in enumerate(zip(HEIGHTS, COLORS)):
        x0 = margin + i * (bar_w + gap)
        bar_h = h * (size - 2 * margin)
        d.rectangle([x0, base_y - bar_h, x0 + bar_w, base_y], fill=c + (255,))
    return img


src = draw(512)
src.save(os.path.join(ICON_DIR, "icon.png"))

sizes = [(32, "32x32.png"), (128, "128x128.png"), (256, "128x128@2x.png")]
for s, name in sizes:
    draw(s).save(os.path.join(ICON_DIR, name))

ico = Image.new("RGBA", (256, 256), (0, 0, 0, 0))
ico.paste(draw(256), (0, 0))
ico.save(os.path.join(ICON_DIR, "icon.ico"), format="ICO", sizes=[(16, 16), (32, 32), (48, 48), (64, 64), (128, 128), (256, 256)])

try:
    src.save(os.path.join(ICON_DIR, "icon.icns"), format="ICNS")
except Exception as e:
    print(f"[make_tauri_icons] ICNS skipped ({e})")

print(f"[make_tauri_icons] icons written to {ICON_DIR}")