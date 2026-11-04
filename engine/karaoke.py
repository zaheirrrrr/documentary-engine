"""One-word karaoke captions and on-screen hook text for vertical Shorts.

Caption style adapted from the famous-reel-editor skill: Montserrat Black,
white, UPPERCASE, one word at a time, no trailing punctuation, no hard outline
but a soft blurred shadow (readable over bright footage, invisible on dark).

Instead of rendering a PNG for every video frame, each caption state (one word,
or nothing) becomes one PNG with a duration, joined by FFmpeg's concat demuxer.
That is a few hundred small images instead of thousands.
"""

from __future__ import annotations

import textwrap
from pathlib import Path

from PIL import Image, ImageDraw, ImageFilter, ImageFont

from .cards import SANS_BOLD, font as find_font


def _font(path: Path | None, size: int) -> ImageFont.FreeTypeFont:
    if path and path.exists():
        f = ImageFont.truetype(str(path), size)
        try:
            f.set_variation_by_axes([900])  # Black weight
        except Exception:  # noqa: BLE001 - static fonts have no axes
            pass
        return f
    return find_font(SANS_BOLD, size)


def _shadowed_text(canvas: Image.Image, xy_center: tuple[int, int], lines: list[str], fnt, fill="#FFFFFF",
                   line_gap: float = 1.08, shadow_alpha: int = 190) -> None:
    w, _ = canvas.size
    draw = ImageDraw.Draw(canvas)
    heights = [draw.textbbox((0, 0), l, font=fnt)[3] for l in lines]
    step = int(max(heights) * line_gap) if heights else 0
    y = xy_center[1] - (step * len(lines)) // 2
    shadow = Image.new("RGBA", canvas.size, (0, 0, 0, 0))
    sd = ImageDraw.Draw(shadow)
    for line in lines:
        tw = draw.textlength(line, font=fnt)
        x = (w - tw) // 2
        sd.text((x + 3, y + 6), line, font=fnt, fill=(0, 0, 0, shadow_alpha))
        y += step
    shadow = shadow.filter(ImageFilter.GaussianBlur(9))
    canvas.alpha_composite(shadow)
    y = xy_center[1] - (step * len(lines)) // 2
    for line in lines:
        tw = draw.textlength(line, font=fnt)
        draw.text(((w - tw) // 2, y), line, font=fnt, fill=fill)
        y += step


def caption_states(words: list[tuple[str, float, float]], total: float, max_hold: float = 1.0) -> list[tuple[float, float, str]]:
    """(start, end, WORD) runs covering 0..total, with "" for no caption."""
    states: list[tuple[float, float, str]] = []
    t = 0.0
    for i, (text, start, _end) in enumerate(words):
        nxt = words[i + 1][1] if i + 1 < len(words) else start + 0.6
        stop = max(start + 0.12, min(nxt, start + max_hold))
        word = text.strip().upper().rstrip(",.;:!?").strip("\"“”'‘’")
        if start > t + 0.02:
            states.append((t, start, ""))
        states.append((max(start, t), stop, word))
        t = stop
    if t < total:
        states.append((t, total, ""))
    return [(a, b, w) for a, b, w in states if b - a > 0.01]


def build_overlay(words: list[tuple[str, float, float]], total: float, hook_text: str, hook_seconds: float,
                  out_dir: Path, size: tuple[int, int], font_path: Path | None, caption_size: int = 92,
                  caption_y: int = 1340, accent: str = "#E8B33A") -> Path:
    """Write caption PNGs and a concat list; returns the concat list path."""
    out_dir.mkdir(parents=True, exist_ok=True)
    w, h = size
    cap_font = _font(font_path, caption_size)
    hook_font = _font(font_path, 78)
    hook_lines = textwrap.wrap(hook_text.upper(), width=16)[:3] if hook_text else []

    # Split states at the hook boundary so the hook shows only in the first seconds.
    states: list[tuple[float, float, str, bool]] = []
    for a, b, word in caption_states(words, total):
        if hook_lines and a < hook_seconds < b:
            states.append((a, hook_seconds, word, True))
            states.append((hook_seconds, b, word, False))
        else:
            states.append((a, b, word, bool(hook_lines) and a < hook_seconds))

    cache: dict[tuple[str, bool], Path] = {}
    entries: list[tuple[Path, float]] = []
    for a, b, word, show_hook in states:
        key = (word, show_hook)
        if key not in cache:
            img = Image.new("RGBA", (w, h), (0, 0, 0, 0))
            if show_hook:
                _shadowed_text(img, (w // 2, int(h * 0.17)), hook_lines, hook_font, fill="#FFFFFF")
            if word:
                fnt = cap_font
                while ImageDraw.Draw(img).textlength(word, font=fnt) > w * 0.9 and fnt.size > 40:
                    fnt = _font(font_path, fnt.size - 8)
                _shadowed_text(img, (w // 2, caption_y), [word], fnt)
            path = out_dir / f"c{len(cache):04d}.png"
            img.save(path)
            cache[key] = path
        entries.append((cache[key], b - a))

    listing = out_dir / "captions.txt"
    lines = []
    for path, dur in entries:
        lines += [f"file '{path.resolve()}'", f"duration {dur:.3f}"]
    lines.append(f"file '{entries[-1][0].resolve()}'")  # concat demuxer needs the last file twice
    listing.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return listing
