#!/usr/bin/env python3
"""Render site/og.png, the 1200x630 social card.

The three numbers are the piece, so they are the card rather than the sentence:
a headline set at this size is unreadable in a Slack unfurl, three numerals are
not. Palette and the teal-to-pink dot field match the site's own map colours.

  python3 make_og.py
"""
import pathlib, random
from PIL import Image, ImageDraw, ImageFont

ROOT = pathlib.Path(__file__).resolve().parent.parent
OUT  = ROOT / "site" / "og.png"
W, H = 1200, 630
BG        = (18, 18, 17)
TEXT      = (246, 246, 244)
SECONDARY = (195, 194, 183)
MUTED     = (138, 137, 127)
TEAL      = (31, 199, 212)      # --map-blue
PINK      = (255, 63, 168)      # --map-pink
PAD       = 80

F = "/usr/share/fonts/truetype/dejavu/DejaVuSans%s.ttf"
font = lambda sz, b=False: ImageFont.truetype(F % ("-Bold" if b else ""), sz)

# the three facts, each one directly measured
FACTS = [("32K", "open ollamas"), ("256", "honeypots"), ("365", "failed ransoms")]
TAGLINE = "eighteen months of unsecured Ollama servers"
URL = "day50.dev/woahllama"


def mix(a, b, t):
    return tuple(round(x + (y - x) * t) for x, y in zip(a, b))


def dotfield(d, y0, y1, n=230, seed=20260910):
    """Scattered dots, teal on the left through pink on the right.

    Same device as the previous card, so the piece stays recognisable in a feed
    even though the wording changed. The band stays clear of the numerals: a dot
    landing on a digit is the one thing that costs legibility at unfurl size.
    """
    rnd = random.Random(seed)
    for _ in range(n):
        x = rnd.uniform(PAD * 0.4, W - PAD * 0.4)
        # density falls off toward the bottom of the band
        y = y0 + (y1 - y0) * rnd.random() ** 0.65
        r = rnd.choice([2, 2, 3, 3, 4, 5, 7, 9])
        col = mix(TEAL, PINK, (x / W) ** 0.9)
        a = rnd.randint(70, 235) - int(120 * (y - y0) / (y1 - y0))
        d.ellipse([x - r, y - r, x + r, y + r], fill=col + (max(a, 25),))


def main():
    img = Image.new("RGB", (W, H), BG)
    layer = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    dotfield(ImageDraw.Draw(layer), 38, 182)
    img = Image.alpha_composite(img.convert("RGBA"), layer).convert("RGB")
    d = ImageDraw.Draw(img)

    # ---- the three numbers, evenly placed across the width
    fnum, flab = font(104, True), font(27)
    col_w = (W - PAD * 2) / 3
    for i, (num, lab) in enumerate(FACTS):
        cx = PAD + col_w * (i + 0.5)
        col = mix(TEAL, PINK, i / (len(FACTS) - 1))
        d.text((cx, 288), num, font=fnum, fill=TEXT, anchor="mm")
        d.text((cx, 360), lab, font=flab, fill=col, anchor="mm")

    # ---- gradient rule
    y = 428
    for x in range(PAD, W - PAD):
        t = (x - PAD) / (W - PAD * 2)
        d.line([(x, y), (x, y + 7)], fill=mix(TEAL, PINK, t))

    d.text((PAD, 474), TAGLINE, font=font(30), fill=SECONDARY)
    d.text((PAD, 518), "what is running where, and who is hunting the people looking",
           font=font(24), fill=MUTED)
    d.text((PAD, 566), URL, font=font(24, True), fill=TEAL)

    img.save(OUT, "PNG", optimize=True)
    print(f"  {OUT.relative_to(ROOT)}  {W}x{H}  {OUT.stat().st_size/1024:.0f} KB")


if __name__ == "__main__":
    main()
