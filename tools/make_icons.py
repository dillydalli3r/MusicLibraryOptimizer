#!/usr/bin/env python3
"""Regenerate every app icon from the gato source image.

- Square center-crop of C:\\Users\\dillydallier\\Pictures\\Icons\\gato.jpg
- web/public/icon.png (favicon + in-app logo, 512x512)
- desktop/src-tauri/icons/**/*.png regenerated at each file's existing size
- icons/icon.ico (16..256) and icons/icon.icns (PNG-embedded, hand-rolled)
"""
import os
import struct
import sys

from PIL import Image

SRC = r"C:\Users\dillydallier\Pictures\Icons\gato.jpg"
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
ICONS = os.path.join(ROOT, "desktop", "src-tauri", "icons")
WEB_PUBLIC = os.path.join(ROOT, "web", "public")

im = Image.open(SRC).convert("RGB")
w, h = im.size
side = min(w, h)
im = im.crop(((w - side) // 2, (h - side) // 2, (w + side) // 2, (h + side) // 2))


def at(size):
    return im.resize((size, size), Image.LANCZOS)


# --- web: favicon + header logo ---
os.makedirs(WEB_PUBLIC, exist_ok=True)
at(512).save(os.path.join(WEB_PUBLIC, "icon.png"))
print("web/public/icon.png (512)")

# --- tauri: every PNG at its existing dimensions ---
count = 0
for dirpath, _dirs, files in os.walk(ICONS):
    for f in files:
        if not f.lower().endswith(".png"):
            continue
        p = os.path.join(dirpath, f)
        try:
            with Image.open(p) as old:
                size = old.size  # (w, h)
        except Exception as e:
            print("skip (unreadable):", p, e)
            continue
        if size[0] != size[1]:
            # non-square (none expected) — pad onto a square canvas
            canvas = Image.new("RGB", size, (10, 10, 12))
            s = min(size)
            canvas.paste(at(s), ((size[0] - s) // 2, (size[1] - s) // 2))
            canvas.save(p)
        else:
            at(size[0]).save(p)
        count += 1
print(f"{count} tauri PNGs regenerated")

# --- icon.ico with the full size range ---
ico_path = os.path.join(ICONS, "icon.ico")
at(256).save(ico_path, format="ICO", sizes=[(s, s) for s in (16, 24, 32, 48, 64, 128, 256)])
print("icon.ico")

# --- icon.icns: hand-rolled PNG-embedded container ---
def icns_entry(typecode, img):
    data = img.export() if hasattr(img, "export") else None
    return typecode, data


entries = [
    ("icp4", at(16)),    # 16x16
    ("icp5", at(32)),    # 32x32
    ("ic11", at(32)),    # 32x32 @2x
    ("ic12", at(64)),    # 64x64 @2x
    ("ic07", at(128)),   # 128x128
    ("ic08", at(256)),   # 256x256
    ("ic09", at(512)),   # 512x512
    ("ic10", at(1024)),  # 1024x1024
]
blob = b""
for typecode, img in entries:
    import io
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    png = buf.getvalue()
    blob += typecode.encode("ascii") + struct.pack(">I", len(png) + 8) + png
icns = b"icns" + struct.pack(">I", len(blob) + 8) + blob
with open(os.path.join(ICONS, "icon.icns"), "wb") as fh:
    fh.write(icns)
print("icon.icns")
print("done")
