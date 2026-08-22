#!/usr/bin/env python3
"""Generate the Music Library Optimizer app icon (app_icon.ico + PNGs).

Draws a rounded square with an indigo->violet diagonal gradient, a white
eighth-note glyph and small sparkles, supersampled 4x for crisp edges.
Re-run after changing the design:  python tools/make_icon.py
"""
import os
import sys

from PIL import Image, ImageDraw, ImageFilter, ImageFont

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
ASSETS = os.path.join(ROOT, "assets")
S = 4                       # supersampling factor
SIZE = 1024                 # final master size


def lerp(a, b, t):
    return tuple(round(a[i] + (b[i] - a[i]) * t) for i in range(3))


def diagonal_gradient(size, c1, c2):
    """Smooth diagonal gradient via a tiny bilinear-upscaled raster."""
    small = Image.new("RGB", (64, 64))
    px = small.load()
    for y in range(64):
        for x in range(64):
            px[x, y] = lerp(c1, c2, (x + y) / 126.0)
    return small.resize((size, size), Image.BILINEAR)


def rounded_mask(size, radius):
    m = Image.new("L", (size, size), 0)
    d = ImageDraw.Draw(m)
    d.rounded_rectangle([0, 0, size - 1, size - 1], radius=radius, fill=255)
    return m


def sparkle(draw, cx, cy, r, color):
    w = r * 0.24
    pts = [
        (cx, cy - r), (cx + w, cy - w), (cx + r, cy), (cx + w, cy + w),
        (cx, cy + r), (cx - w, cy + w), (cx - r, cy), (cx - w, cy - w),
    ]
    draw.polygon(pts, fill=color)


def build_master():
    big = SIZE * S

    # --- background ---------------------------------------------------
    grad = diagonal_gradient(big, (79, 70, 229), (168, 85, 247))  # indigo->violet
    img = Image.new("RGBA", (big, big), (0, 0, 0, 0))

    mask = rounded_mask(big, int(big * 0.225))
    img.paste(grad, (0, 0), mask)

    # subtle top sheen for depth
    sheen = Image.new("L", (big, big), 0)
    sd = ImageDraw.Draw(sheen)
    sd.rounded_rectangle([0, 0, big - 1, int(big * 0.55)], radius=int(big * 0.225),
                         fill=42)
    sheen = sheen.filter(ImageFilter.GaussianBlur(big * 0.06))
    sheen_img = Image.new("RGBA", (big, big), (255, 255, 255, 0))
    sheen_img.putalpha(sheen)
    img = Image.alpha_composite(img, sheen_img)

    # soft radial glow behind the note
    glow = Image.new("L", (big, big), 0)
    gd = ImageDraw.Draw(glow)
    gd.ellipse([int(big * 0.20), int(big * 0.16), int(big * 0.86), int(big * 0.82)],
               fill=80)
    glow = glow.filter(ImageFilter.GaussianBlur(big * 0.075))
    glow_img = Image.new("RGBA", (big, big), (255, 255, 255, 0))
    glow_img.putalpha(glow)
    img = Image.alpha_composite(img, glow_img)

    # --- beamed pair of eighth notes (hand-drawn geometry) --------------
    layer = Image.new("RGBA", (big, big), (0, 0, 0, 0))
    ld = ImageDraw.Draw(layer)
    white = (255, 255, 255, 255)
    stem_w = big * 0.048
    lean = big * 0.035          # rightward lean over the stem height

    def stem(x, y_head, y_top):
        ld.polygon([
            (x, y_head),
            (x + stem_w, y_head),
            (x + stem_w + lean, y_top),
            (x + lean, y_top),
        ], fill=white)

    # note heads (slanted ellipses) with stems rising to the beam
    r1x, r1y = big * 0.118, big * 0.088
    c1 = (big * 0.265, big * 0.680)
    r2x, r2y = big * 0.108, big * 0.082
    c2 = (big * 0.635, big * 0.632)
    head1 = Image.new("RGBA", (int(r1x * 2 * 1.6), int(r1y * 2 * 1.6)), (0, 0, 0, 0))
    ImageDraw.Draw(head1).ellipse(
        [0, 0, head1.width - 1, head1.height - 1], fill=white)
    head1 = head1.rotate(-22, expand=True, resample=Image.BICUBIC)
    layer.alpha_composite(head1, (int(c1[0] - head1.width / 2),
                                  int(c1[1] - head1.height / 2)))
    head2 = Image.new("RGBA", (int(r2x * 2 * 1.6), int(r2y * 2 * 1.6)), (0, 0, 0, 0))
    ImageDraw.Draw(head2).ellipse(
        [0, 0, head2.width - 1, head2.height - 1], fill=white)
    head2 = head2.rotate(-22, expand=True, resample=Image.BICUBIC)
    layer.alpha_composite(head2, (int(c2[0] - head2.width / 2),
                                  int(c2[1] - head2.height / 2)))

    top1, top2 = big * 0.295, big * 0.250
    stem(c1[0] + r1x * 0.86, c1[1] + r1y * 0.30, top1)
    stem(c2[0] + r2x * 0.86, c2[1] + r2y * 0.30, top2)

    # thick beam across the stem tops (slab, slightly rising)
    beam_t = big * 0.105
    ld.polygon([
        (c1[0] + lean, top1),
        (c2[0] + stem_w + lean, top2),
        (c2[0] + stem_w + lean, top2 + beam_t),
        (c1[0] + lean, top1 + beam_t),
    ], fill=white)
    img = Image.alpha_composite(img, layer)

    # --- sparkles -------------------------------------------------------
    sp = Image.new("RGBA", (big, big), (0, 0, 0, 0))
    spd = ImageDraw.Draw(sp)
    sparkle(spd, int(big * 0.78), int(big * 0.225), int(big * 0.105),
            (255, 255, 255, 255))
    sparkle(spd, int(big * 0.665), int(big * 0.135), int(big * 0.048),
            (255, 255, 255, 235))
    sparkle(spd, int(big * 0.885), int(big * 0.36), int(big * 0.036),
            (255, 255, 255, 225))
    img = Image.alpha_composite(img, sp)

    # soft drop shadow of the rounded square onto the icon edge itself
    img = img.convert("RGB")  # ico wants opaque
    return img.resize((SIZE, SIZE), Image.LANCZOS)


def main():
    os.makedirs(ASSETS, exist_ok=True)
    master = build_master()

    ico_path = os.path.join(ROOT, "app_icon.ico")
    sizes = [(16, 16), (24, 24), (32, 32), (48, 48), (64, 64),
             (128, 128), (256, 256)]
    frames = [master.resize(s, Image.LANCZOS) for s in sizes]
    frames[-1].save(ico_path, format="ICO", sizes=sizes, append_images=frames[:-1])

    master.resize((256, 256), Image.LANCZOS).save(
        os.path.join(ASSETS, "icon_256.png"))
    master.resize((64, 64), Image.LANCZOS).save(
        os.path.join(ASSETS, "icon_64.png"))

    print(f"wrote {ico_path}")
    print(f"wrote {ASSETS}" + os.sep + "icon_256.png / icon_64.png")


if __name__ == "__main__":
    sys.exit(main())
