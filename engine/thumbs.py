"""Thumbnail layouts and click-through checks.

Four layouts, matching the patterns `de trends` finds in outlier thumbnails:
- split:   two frames side by side (glory vs ruins), divider, optional labels
- versus:  two frames with big price/number tags and a VS badge ($1 vs $1M)
- subject: one strong frame, 2-4 big words, optional arrow or circle placed
           on the most detailed part of the frame
- number:  one huge number over a dark frame

Every draft gets a mobile check: the text must stay readable when the
thumbnail is shrunk to the size it appears at in the feed and sidebar.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from pathlib import Path

from PIL import Image, ImageDraw, ImageEnhance, ImageFilter, ImageOps, ImageStat

from .cards import SANS_BOLD, font as find_font

W, H = 1280, 720
SMALL_W = 168  # sidebar / suggested-video width in px


@dataclass
class Draft:
    path: Path
    layout: str
    text: str
    title: str
    font_px: int
    checks: dict = field(default_factory=dict)


def _font(font_path: Path | None, size: int):
    from PIL import ImageFont

    if font_path and font_path.exists():
        f = ImageFont.truetype(str(font_path), size)
        try:
            f.set_variation_by_axes([900])
        except Exception:  # noqa: BLE001
            pass
        return f
    return find_font(SANS_BOLD, size)


def _cover(img: Image.Image, size: tuple[int, int], focus: tuple[float, float] = (0.5, 0.5)) -> Image.Image:
    return ImageOps.fit(img.convert("RGB"), size, Image.LANCZOS, centering=focus)


def _punch(img: Image.Image, faded: bool = False) -> Image.Image:
    img = img.filter(ImageFilter.UnsharpMask(radius=2, percent=120, threshold=2))
    img = ImageEnhance.Contrast(img).enhance(1.35)
    img = ImageEnhance.Color(img).enhance(0.35 if faded else 1.15)
    if faded:
        img = ImageEnhance.Brightness(img).enhance(0.8)
    return img


def _vignette(img: Image.Image, strength: int = 150) -> Image.Image:
    w, h = img.size
    mask = Image.new("L", (w, h), 0)
    ImageDraw.Draw(mask).ellipse((-w * 0.15, -h * 0.25, w * 1.15, h * 1.25), fill=255)
    mask = mask.filter(ImageFilter.GaussianBlur(min(w, h) // 5))
    dark = Image.new("RGB", (w, h), (0, 0, 0))
    return Image.composite(img, Image.blend(img, dark, strength / 255), mask)


def saliency_point(img: Image.Image) -> tuple[int, int]:
    """Centre of the most detailed region (edge density), used to aim arrows and circles."""
    small = img.convert("L").resize((32, 18)).filter(ImageFilter.FIND_EDGES)
    px = small.load()
    best, best_xy = -1.0, (16, 9)
    for y in range(2, 16):
        for x in range(2, 30):
            s = sum(px[x + dx, y + dy] for dx in (-1, 0, 1) for dy in (-1, 0, 1))
            if s > best:
                best, best_xy = s, (x, y)
    return int(best_xy[0] / 32 * img.width), int(best_xy[1] / 18 * img.height)


def _text_block(img: Image.Image, text: str, font_path: Path | None, box: tuple[int, int, int, int], colors: dict,
                max_px: int = 150, min_px: int = 80, align: str = "left") -> int:
    """Draw up to 3 lines of heavy text fitted to box; returns the font size used."""
    x0, y0, x1, y1 = box
    draw = ImageDraw.Draw(img)
    words = text.upper().split()
    size = max_px
    while True:
        f = _font(font_path, size)
        lines, line = [], ""
        for w in words:
            trial = f"{line} {w}".strip()
            if draw.textlength(trial, font=f) <= (x1 - x0) or not line:
                line = trial
            else:
                lines.append(line)
                line = w
        if line:
            lines.append(line)
        height = len(lines) * int(size * 1.02)
        if (height <= (y1 - y0) and len(lines) <= 3 and all(draw.textlength(l, font=f) <= x1 - x0 for l in lines)) or size <= min_px:
            break
        size -= 6
    y = y0 + ((y1 - y0) - height) // 2
    shadow = Image.new("RGBA", img.size, (0, 0, 0, 0))
    sd = ImageDraw.Draw(shadow)
    for line in lines:
        lw = draw.textlength(line, font=f)
        x = x0 if align == "left" else x0 + ((x1 - x0) - lw) // 2
        sd.text((x + 6, y + 10), line, font=f, fill=(0, 0, 0, 200))
        y += int(size * 1.02)
    img.paste(Image.new("RGB", img.size, (0, 0, 0)), (0, 0), shadow.filter(ImageFilter.GaussianBlur(10)).split()[3])
    y = y0 + ((y1 - y0) - height) // 2
    for i, line in enumerate(lines):
        lw = draw.textlength(line, font=f)
        x = x0 if align == "left" else x0 + ((x1 - x0) - lw) // 2
        fill = colors.get("accent", "#E8B33A") if (i == len(lines) - 1 and len(lines) > 1) else colors.get("text", "#FFFFFF")
        draw.text((x, y), line, font=f, fill=fill, stroke_width=max(4, size // 18), stroke_fill=colors.get("stroke", "#000000"))
        y += int(size * 1.02)
    return size


def _pill(img: Image.Image, center: tuple[int, int], label: str, font_path: Path | None, fill: str, size: int = 92) -> None:
    draw = ImageDraw.Draw(img)
    f = _font(font_path, size)
    tw = draw.textlength(label, font=f)
    while tw > img.width * 0.42 and size > 50:
        size -= 6
        f = _font(font_path, size)
        tw = draw.textlength(label, font=f)
    cx, cy = center
    pad_x, pad_y = 26, 14
    box = (cx - tw / 2 - pad_x, cy - size / 2 - pad_y, cx + tw / 2 + pad_x, cy + size / 2 + pad_y + 8)
    draw.rounded_rectangle(box, radius=18, fill=fill, outline="#000000", width=5)
    draw.text((cx - tw / 2, cy - size / 2 - 4), label, font=f, fill="#FFFFFF", stroke_width=3, stroke_fill="#000000")


def _arrow(img: Image.Image, target: tuple[int, int], color: str) -> None:
    draw = ImageDraw.Draw(img)
    tx, ty = target
    sx, sy = (tx - 260 if tx > W * 0.5 else tx + 260), max(60, ty - 200)
    ang = math.atan2(ty - sy, tx - sx)
    ex, ey = tx - 60 * math.cos(ang), ty - 60 * math.sin(ang)
    draw.line((sx, sy, ex, ey), fill="#000000", width=34)
    draw.line((sx, sy, ex, ey), fill=color, width=22)
    head = [(tx, ty), (ex - 55 * math.cos(ang - 0.6), ey - 55 * math.sin(ang - 0.6)), (ex - 55 * math.cos(ang + 0.6), ey - 55 * math.sin(ang + 0.6))]
    draw.polygon(head, fill=color, outline="#000000")


def _circle(img: Image.Image, target: tuple[int, int], color: str, r: int = 120) -> None:
    draw = ImageDraw.Draw(img)
    x, y = target
    draw.ellipse((x - r - 4, y - r - 4, x + r + 4, y + r + 4), outline="#000000", width=20)
    draw.ellipse((x - r, y - r, x + r, y + r), outline=color, width=12)


def render(layout: str, frames: list[Path], text: str, dest: Path, colors: dict, font_path: Path | None,
           labels: list[str] | None = None, subtext: str = "", device: str = "none") -> int:
    """Draw one thumbnail; returns the main text's font size in px."""
    labels = labels or []
    imgs = [Image.open(f) for f in frames]
    accent = colors.get("accent", "#E8B33A")
    if layout in {"split", "versus"} and len(imgs) >= 2:
        half = (W // 2, H)
        left = _punch(_cover(imgs[0], half))
        right = _punch(_cover(imgs[1], half), faded=(layout == "split"))
        canvas = Image.new("RGB", (W, H))
        canvas.paste(left, (0, 0))
        canvas.paste(right, (W // 2, 0))
        canvas = _vignette(canvas, 110)
        d = ImageDraw.Draw(canvas)
        d.rectangle((W // 2 - 7, 0, W // 2 + 7, H), fill="#000000")
        d.rectangle((W // 2 - 3, 0, W // 2 + 3, H), fill=accent)
        if layout == "versus":
            for i, lab in enumerate(labels[:2]):
                _pill(canvas, (W // 4 + i * W // 2, int(H * 0.78)), lab, font_path, "#2E9E4F" if i == 0 else "#C62828")
            d.ellipse((W // 2 - 70, H // 2 - 70, W // 2 + 70, H // 2 + 70), fill="#000000", outline=accent, width=8)
            f = _font(font_path, 64)
            d.text((W // 2 - d.textlength("VS", font=f) / 2, H // 2 - 40), "VS", font=f, fill="#FFFFFF")
            size = _text_block(canvas, text, font_path, (60, 30, W - 60, 230), colors, 120, 70, "center") if text else 0
        else:
            for i, lab in enumerate(labels[:2]):
                _pill(canvas, (W // 4 + i * W // 2, 90), lab, font_path, "#111111", 64)
            size = _text_block(canvas, text, font_path, (60, int(H * 0.60), W - 60, H - 30), colors, 130, 74, "center")
    elif layout == "number":
        base = _cover(imgs[0], (W, H)).filter(ImageFilter.GaussianBlur(3))
        canvas = ImageEnhance.Brightness(_punch(base, faded=True)).enhance(0.45)
        canvas = _vignette(canvas, 170)
        size = _text_block(canvas, text, font_path, (60, 120, W - 60, 480), {**colors, "text": accent}, 250, 120, "center")
        if subtext:
            _text_block(canvas, subtext, font_path, (120, 480, W - 120, 640), colors, 70, 44, "center")
    else:  # subject
        canvas = _vignette(_punch(_cover(imgs[0], (W, H))), 90)
        shade = Image.new("L", (W, H), 0)
        ImageDraw.Draw(shade).rectangle((0, 0, int(W * 0.55), H), fill=170)
        canvas.paste((0, 0, 0), (0, 0), shade.filter(ImageFilter.GaussianBlur(90)))
        target = saliency_point(canvas.crop((int(W * 0.45), 0, W, H)))
        # Keep the device fully inside the frame and clear of the edges.
        target = (min(max(target[0] + int(W * 0.45), int(W * 0.6)), W - 160), min(max(target[1], 160), H - 160))
        if device == "arrow":
            _arrow(canvas, target, "#E53935")
        elif device == "circle":
            _circle(canvas, target, "#E53935")
        size = _text_block(canvas, text, font_path, (50, 40, int(W * 0.56), H - 40), colors, 150, 80, "left")
    canvas.save(dest, quality=93)
    return size


def mobile_checks(path: Path, text: str, font_px: int) -> dict:
    """Is it readable at feed size? (text height, word count, overall contrast)"""
    img = Image.open(path).convert("L")
    small = img.resize((SMALL_W, round(SMALL_W * H / W)))
    text_px_small = round(font_px * 0.72 * SMALL_W / W, 1)  # approx cap height at sidebar size
    words = len(text.split())
    contrast = round(ImageStat.Stat(small).stddev[0], 1)
    checks = {
        "words": words,
        "words_ok": words <= 4,
        "text_px_at_sidebar": text_px_small,
        "readable_small": text_px_small >= 7.5 or words == 0,
        "contrast": contrast,
        "contrast_ok": contrast >= 45,
    }
    checks["score"] = 100 - 20 * sum(not checks[k] for k in ("words_ok", "readable_small", "contrast_ok"))
    return checks


def contact_sheet(drafts: list[Draft], dest: Path) -> Path:
    """Each draft at large and at feed size, numbered, for Claude to judge."""
    tile_w, tile_h, small_w = 480, 270, 168
    small_h = round(small_w * 9 / 16)
    rows = len(drafts)
    sheet = Image.new("RGB", (tile_w + small_w + 60, rows * (tile_h + 16) + 16), "white")
    d = ImageDraw.Draw(sheet)
    f = find_font(SANS_BOLD, 28)
    for i, dr in enumerate(drafts):
        y = 16 + i * (tile_h + 16)
        img = Image.open(dr.path).convert("RGB")
        sheet.paste(img.resize((tile_w, tile_h)), (40, y))
        sheet.paste(img.resize((small_w, small_h)), (40 + tile_w + 12, y + (tile_h - small_h) // 2))
        d.text((6, y + 4), str(i + 1), font=f, fill="black")
    sheet.save(dest, quality=88)
    return dest
