"""Generates assets/icon.png and assets/icon.ico (run once; outputs are committed)."""
import os
from PIL import Image, ImageDraw, ImageFilter

S = 2048          # supersampled canvas
OUT = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "assets")


def lerp(a, b, t):
    return tuple(int(a[i] + (b[i] - a[i]) * t) for i in range(3))


def gradient(size, c1, c2):
    g = Image.new("RGB", (size, size))
    px = g.load()
    for y in range(size):
        for x in range(size):
            px[x, y] = lerp(c1, c2, (x + y) / (2 * size - 2))
    return g


def rounded_mask(size, radius):
    m = Image.new("L", (size, size), 0)
    ImageDraw.Draw(m).rounded_rectangle([0, 0, size - 1, size - 1], radius=radius, fill=255)
    return m


def main():
    os.makedirs(OUT, exist_ok=True)
    pad = int(S * 0.04)
    inner = S - 2 * pad
    tile = gradient(inner, (108, 92, 255), (20, 212, 196))        # violet -> teal
    tile.putalpha(rounded_mask(inner, int(inner * 0.23)))

    # soft top highlight
    hl = Image.new("RGBA", (inner, inner), (255, 255, 255, 0))
    ImageDraw.Draw(hl).ellipse([-inner * 0.2, -inner * 0.75, inner * 1.2, inner * 0.45], fill=(255, 255, 255, 38))
    hl = hl.filter(ImageFilter.GaussianBlur(inner * 0.03))
    hl.putalpha(Image.composite(hl.split()[3], Image.new("L", (inner, inner), 0), rounded_mask(inner, int(inner * 0.23))))
    tile = Image.alpha_composite(tile, hl)

    # glyph: rounded play triangle + 3 voice bars
    glyph = Image.new("RGBA", (inner, inner), (0, 0, 0, 0))
    d = ImageDraw.Draw(glyph)
    cx, cy = inner * 0.40, inner * 0.50
    r = inner * 0.20
    tri = [(cx - r * 0.75, cy - r * 1.05), (cx - r * 0.75, cy + r * 1.05), (cx + r * 1.05, cy)]
    d.polygon(tri, fill=(255, 255, 255, 255))
    d.line(tri + [tri[0], tri[1]], fill=(255, 255, 255, 255), width=int(inner * 0.045), joint="curve")
    for p in tri:
        rr = inner * 0.0225
        d.ellipse([p[0] - rr, p[1] - rr, p[0] + rr, p[1] + rr], fill=(255, 255, 255, 255))
    bw = inner * 0.052
    for i, h in enumerate((0.20, 0.34, 0.14)):
        x = inner * (0.66 + i * 0.087)
        hh = inner * h
        d.rounded_rectangle([x - bw / 2, cy - hh / 2, x + bw / 2, cy + hh / 2], radius=bw / 2,
                            fill=(255, 255, 255, 235 - i * 25))
    # subtle shadow under glyph
    sh = glyph.filter(ImageFilter.GaussianBlur(inner * 0.012))
    sh = Image.merge("RGBA", (Image.new("L", sh.size, 20), Image.new("L", sh.size, 20), Image.new("L", sh.size, 60), sh.split()[3].point(lambda v: int(v * 0.45))))
    tile = Image.alpha_composite(tile, Image.new("RGBA", tile.size, (0, 0, 0, 0)).copy())
    shifted = Image.new("RGBA", tile.size, (0, 0, 0, 0))
    shifted.paste(sh, (0, int(inner * 0.012)))
    tile = Image.alpha_composite(tile, shifted)
    tile = Image.alpha_composite(tile, glyph)

    canvas = Image.new("RGBA", (S, S), (0, 0, 0, 0))
    canvas.paste(tile, (pad, pad), tile)
    png = canvas.resize((512, 512), Image.LANCZOS)
    png.save(os.path.join(OUT, "icon.png"))
    canvas.resize((256, 256), Image.LANCZOS).save(
        os.path.join(OUT, "icon.ico"), sizes=[(16, 16), (24, 24), (32, 32), (48, 48), (64, 64), (128, 128), (256, 256)])
    # small preview strip to eyeball legibility
    strip = Image.new("RGBA", (512 + 130 + 70 + 40, 512), (30, 32, 48, 255))
    strip.paste(png, (0, 0), png)
    x = 530
    for sz in (128, 64, 32):
        im = canvas.resize((sz, sz), Image.LANCZOS)
        strip.paste(im, (x, 20), im)
        x += sz + 12
    strip.save("/tmp/icon_preview.png")


if __name__ == "__main__":
    main()
