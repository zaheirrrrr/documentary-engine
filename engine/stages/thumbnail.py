"""Stage: thumbnail. Picks the strongest frames from the cut footage and
lays the best thumbnail text options over them (three drafts)."""

from __future__ import annotations

import subprocess
from pathlib import Path

from PIL import Image, ImageFilter, ImageStat

from .. import cards
from ..dossier import render
from ..util import read_json


def frame_score(path: Path) -> float:
    img = Image.open(path).convert("L").resize((320, 180))
    contrast = ImageStat.Stat(img).stddev[0]
    edges = ImageStat.Stat(img.filter(ImageFilter.FIND_EDGES)).mean[0]
    brightness = ImageStat.Stat(img).mean[0]
    penalty = 0 if 40 < brightness < 200 else 25
    return contrast + edges * 1.5 - penalty


def run(ctx) -> None:
    out_dir = ctx.dir / "thumbnails"
    frames_dir = out_dir / "frames"
    frames_dir.mkdir(parents=True, exist_ok=True)

    footage = read_json(ctx.dir / "footage.json") if (ctx.dir / "footage.json").exists() else {}
    candidates: list[tuple[float, str, Path]] = []
    for key, entry in footage.items():
        for k, shot in enumerate(entry.get("shots", [])):
            clip = Path(shot["path"])
            if not clip.exists():
                continue
            frame = frames_dir / f"b{int(key):03d}-{k}.jpg"
            if not frame.exists():
                subprocess.run(["ffmpeg", "-y", "-v", "error", "-ss", f"{shot['duration'] / 2:.2f}", "-i", str(clip),
                                "-frames:v", "1", str(frame)], check=False)
            if frame.exists():
                candidates.append((frame_score(frame), shot["identifier"], frame))

    picked: list[Path] = []
    films: set[str] = set()
    for score, film, frame in sorted(candidates, reverse=True):
        if film in films:
            continue
        films.add(film)
        picked.append(frame)
        if len(picked) == 3:
            break
    if not picked:
        cards_dir = ctx.dir / "render" / "cards"
        picked = sorted(cards_dir.glob("*.jpg"))[:3] if cards_dir.exists() else []
    if not picked:
        raise RuntimeError("No frames or cards available for thumbnails")

    package = read_json(ctx.dir / "package.json") if (ctx.dir / "package.json").exists() else {}
    texts = package.get("thumbnail_texts") or [ctx.title]
    colors = ctx.pack.get("thumbnail.colors", {}) or {}
    for i, frame in enumerate(picked):
        cards.thumbnail(frame, texts[i % len(texts)], out_dir / f"thumb{i + 1}.jpg", colors, [ctx.pack.path / "fonts"])
    render(ctx.dir, ctx.title, ctx.angle)
