"""Still graphics drawn with Pillow: quote cards, number cards, fallback
cards, chapter-title overlays and thumbnail text."""

from __future__ import annotations

import textwrap
from pathlib import Path

from PIL import Image, ImageDraw, ImageFilter, ImageFont

SERIF = ["DejaVuSerif.ttf", "Georgia.ttf", "georgia.ttf", "Times New Roman.ttf", "LiberationSerif-Regular.ttf"]
SERIF_BOLD = ["DejaVuSerif-Bold.ttf", "Georgia Bold.ttf", "georgiab.ttf", "LiberationSerif-Bold.ttf"]
SANS_BOLD = ["DejaVuSans-Bold.ttf", "Arial Bold.ttf", "arialbd.ttf", "LiberationSans-Bold.ttf", "Helvetica.ttc"]
FONT_DIRS = [
    Path("/usr/share/fonts/truetype/dejavu"), Path("/usr/share/fonts/truetype/liberation"),
    Path("/usr/share/fonts"), Path("/Library/Fonts"), Path("/System/Library/Fonts"),
    Path("/System/Library/Fonts/Supplemental"), Path("C:/Windows/Fonts"),
]

PAPER = (233, 224, 204)
INK = (38, 32, 26)
DARK = (18, 17, 16)


def font(names: list[str], size: int, extra_dirs: list[Path] | None = None) -> ImageFont.FreeTypeFont:
    for d in (extra_dirs or []) + FONT_DIRS:
        for n in names:
            p = d / n
            if p.exists():
                return ImageFont.truetype(str(p), size)
        if d.exists():
            for n in names:
                found = next(d.rglob(n), None)
                if found:
                    return ImageFont.truetype(str(found), size)
    return ImageFont.load_default(size=size)


def _wrap(draw: ImageDraw.ImageDraw, text: str, fnt, max_width: int) -> list[str]:
    avg = max(1, int(draw.textlength("abcdefghijklmnopqrstuvwxyz", font=fnt) / 26))
    width = max(10, max_width // avg)
    lines = textwrap.wrap(text, width=width)
    while lines and max(draw.textlength(l, font=fnt) for l in lines) > max_width and width > 10:
        width -= 2
        lines = textwrap.wrap(text, width=width)
    return lines


def _paper(size: tuple[int, int]) -> Image.Image:
    w, h = size
    img = Image.new("RGB", size, PAPER)
    noise = Image.effect_noise((w // 4, h // 4), 18).resize(size).convert("RGB")
    img = Image.blend(img, noise, 0.06)
    vignette = Image.new("L", size, 0)
    ImageDraw.Draw(vignette).ellipse((-w * 0.2, -h * 0.3, w * 1.2, h * 1.3), fill=255)
    vignette = vignette.filter(ImageFilter.GaussianBlur(min(w, h) // 6))
    return Image.composite(img, Image.new("RGB", size, (150, 135, 110)), vignette)


def quote_card(text: str, attribution: str, dest: Path, size=(1920, 1080), fonts: list[Path] | None = None) -> Path:
    img = _paper(size)
    d = ImageDraw.Draw(img)
    w, h = size
    n = len(text)
    body_size = 80 if n < 120 else 68 if n < 220 else 56 if n < 360 else 46
    body = font(SERIF, body_size, fonts)
    lines = _wrap(d, f"“{text}”", body, int(w * 0.72))
    line_h = int(body_size * 1.38)
    attr_font = font(SERIF_BOLD, int(body_size * 0.62), fonts)
    block_h = len(lines) * line_h + (int(body_size * 1.6) if attribution else 0)
    y = (h - block_h) // 2
    for line in lines:
        d.text(((w - d.textlength(line, font=body)) // 2, y), line, font=body, fill=INK)
        y += line_h
    if attribution:
        y += int(body_size * 0.6)
        a = f"— {attribution}"
        d.text(((w - d.textlength(a, font=attr_font)) // 2, y), a, font=attr_font, fill=(92, 60, 30))
    img.save(dest, quality=92)
    return dest


def number_card(big: str, small: str, dest: Path, size=(1920, 1080), accent="#E8B33A", fonts: list[Path] | None = None) -> Path:
    w, h = size
    img = Image.new("RGB", size, DARK)
    noise = Image.effect_noise((w // 4, h // 4), 24).resize(size).convert("RGB")
    img = Image.blend(img, noise, 0.05)
    d = ImageDraw.Draw(img)
    bf = font(SERIF_BOLD, 190 if len(big) < 10 else 140, fonts)
    sf = font(SERIF, 54, fonts)
    bw = d.textlength(big, font=bf)
    d.text(((w - bw) // 2, h // 2 - 170), big, font=bf, fill=accent)
    if small:
        for i, line in enumerate(_wrap(d, small, sf, int(w * 0.7))):
            d.text(((w - d.textlength(line, font=sf)) // 2, h // 2 + 80 + i * 70), line, font=sf, fill=(225, 220, 210))
    img.save(dest, quality=92)
    return dest


def _scrim(size: tuple[int, int], alpha: int) -> Image.Image:
    """Transparent canvas darkened evenly, and more in a soft band across the middle
    where the text sits, so it reads over bright footage without darkening the edges."""
    w, h = size
    img = Image.new("RGBA", size, (0, 0, 0, alpha))
    band = Image.new("L", size, 0)
    ImageDraw.Draw(band).rectangle((int(w * 0.12), int(h * 0.28), int(w * 0.88), int(h * 0.72)), fill=255)
    band = band.filter(ImageFilter.GaussianBlur(min(w, h) // 9))
    img.paste((0, 0, 0, min(255, alpha + 90)), (0, 0), band)
    return img


def _shadowed(img: Image.Image, xy: tuple[float, float], text: str, fnt, fill) -> None:
    shadow = Image.new("RGBA", img.size, (0, 0, 0, 0))
    ImageDraw.Draw(shadow).text((xy[0] + 3, xy[1] + 4), text, font=fnt, fill=(0, 0, 0, 230),
                                stroke_width=4, stroke_fill=(0, 0, 0, 230))
    img.alpha_composite(shadow.filter(ImageFilter.GaussianBlur(7)))
    ImageDraw.Draw(img).text(xy, text, font=fnt, fill=fill)


def number_overlay(big: str, small: str, dest: Path, size=(1920, 1080), accent="#F2F0EA",
                   fonts: list[Path] | None = None) -> Path:
    """Transparent PNG: a number card's text, to lay over moving footage."""
    w, h = size
    img = _scrim(size, 120)
    d = ImageDraw.Draw(img)
    bf = font(SERIF_BOLD, 190 if len(big) < 10 else 140, fonts)
    sf = font(SERIF, 54, fonts)
    _shadowed(img, ((w - d.textlength(big, font=bf)) // 2, h // 2 - 170), big, bf, accent)
    if small:
        for i, line in enumerate(_wrap(d, small, sf, int(w * 0.7))):
            _shadowed(img, ((w - d.textlength(line, font=sf)) // 2, h // 2 + 80 + i * 70), line, sf, (235, 232, 225, 255))
    img.save(dest)
    return dest


def quote_overlay(text: str, attribution: str, dest: Path, size=(1920, 1080), fonts: list[Path] | None = None) -> Path:
    """Transparent PNG: a quote card's text, to lay over moving footage."""
    w, h = size
    img = _scrim(size, 150)
    d = ImageDraw.Draw(img)
    n = len(text)
    body_size = 76 if n < 120 else 64 if n < 220 else 54 if n < 360 else 44
    body = font(SERIF, body_size, fonts)
    lines = _wrap(d, f"“{text}”", body, int(w * 0.72))
    line_h = int(body_size * 1.38)
    attr_font = font(SERIF_BOLD, int(body_size * 0.62), fonts)
    y = (h - len(lines) * line_h - (int(body_size * 1.6) if attribution else 0)) // 2
    for line in lines:
        _shadowed(img, ((w - d.textlength(line, font=body)) // 2, y), line, body, (245, 242, 235, 255))
        y += line_h
    if attribution:
        a = f"— {attribution}"
        _shadowed(img, ((w - d.textlength(a, font=attr_font)) // 2, y + int(body_size * 0.6)), a, attr_font,
                  (205, 200, 190, 255))
    img.save(dest)
    return dest


def fallback_card(title: str, dest: Path, size=(1920, 1080), fonts: list[Path] | None = None) -> Path:
    w, h = size
    img = _paper(size).convert("L").convert("RGB")
    d = ImageDraw.Draw(img)
    f = font(SERIF_BOLD, 72, fonts)
    for i, line in enumerate(_wrap(d, title, f, int(w * 0.7))):
        d.text(((w - d.textlength(line, font=f)) // 2, h // 2 - 60 + i * 90), line, font=f, fill=INK)
    img.save(dest, quality=92)
    return dest


def chapter_overlay(title: str, dest: Path, size=(1920, 1080), fonts: list[Path] | None = None) -> Path:
    """Transparent PNG: chapter title in the lower left over a soft shade."""
    w, h = size
    img = Image.new("RGBA", size, (0, 0, 0, 0))
    shade = Image.new("L", size, 0)
    ImageDraw.Draw(shade).rectangle((0, int(h * 0.70), int(w * 0.62), h), fill=150)
    shade = shade.filter(ImageFilter.GaussianBlur(70))
    img.paste((0, 0, 0, 255), (0, 0), shade)
    d = ImageDraw.Draw(img)
    f = font(SERIF_BOLD, 64, fonts)
    d.line((110, int(h * 0.80) - 24, 230, int(h * 0.80) - 24), fill=(232, 179, 58, 255), width=5)
    d.text((110, int(h * 0.80)), title, font=f, fill=(245, 240, 230, 255))
    img.save(dest)
    return dest


def thumbnail(frame: Path, text: str, dest: Path, colors: dict, fonts: list[Path] | None = None,
              size=(1280, 720)) -> Path:
    base = Image.open(frame).convert("RGB")
    bw, bh = base.size
    scale = max(size[0] / bw, size[1] / bh)
    base = base.resize((int(bw * scale), int(bh * scale)))
    left, top = (base.width - size[0]) // 2, (base.height - size[1]) // 2
    base = base.crop((left, top, left + size[0], top + size[1]))
    from PIL import ImageEnhance

    base = ImageEnhance.Contrast(base).enhance(1.35)
    base = ImageEnhance.Color(base).enhance(0.75)
    shade = Image.new("L", size, 0)
    ImageDraw.Draw(shade).rectangle((0, 0, int(size[0] * 0.58), size[1]), fill=170)
    shade = shade.filter(ImageFilter.GaussianBlur(80))
    base.paste((0, 0, 0), (0, 0), shade)

    d = ImageDraw.Draw(base)
    fsize = 118
    f = font(SANS_BOLD, fsize, fonts)
    lines = _wrap(d, text.upper(), f, int(size[0] * 0.55))
    while len(lines) > 3 and fsize > 70:
        fsize -= 8
        f = font(SANS_BOLD, fsize, fonts)
        lines = _wrap(d, text.upper(), f, int(size[0] * 0.55))
    y = (size[1] - len(lines) * int(fsize * 1.08)) // 2
    for i, line in enumerate(lines):
        fill = colors.get("accent", "#E8B33A") if i == len(lines) - 1 else colors.get("text", "#FFFFFF")
        d.text((60, y), line, font=f, fill=fill, stroke_width=6, stroke_fill=colors.get("stroke", "#000000"))
        y += int(fsize * 1.08)
    base.save(dest, quality=92)
    return dest
