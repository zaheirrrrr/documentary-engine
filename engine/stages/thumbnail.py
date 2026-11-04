"""Stage: thumbnail. Builds thumbnails from the concept stage's designs.

For each thumbnail concept (from packaging.json):
1. Every panel gets its own frame: archive.org is searched with the panel's
   query, candidate frames are checked by Claude vision against the panel's
   brief, and the best one is taken at full resolution. If that fails, the
   sharpest frame from the video's own footage is used.
2. The layout is drawn (split, versus, subject or number).
3. A mobile check measures text size and contrast at sidebar size.

All drafts are then judged together by Claude (large and phone size side by
side) and the best {thumbnail_variants} different ones become thumb1..N for
YouTube's Test & Compare. thumbnails.md pairs each with its title.
"""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

from PIL import Image, ImageFilter, ImageStat

from .. import thumbs
from ..dossier import render as render_dossier
from ..util import read_json, write_json, write_text
from . import footage


def frame_score(path: Path) -> float:
    img = Image.open(path).convert("L").resize((320, 180))
    contrast = ImageStat.Stat(img).stddev[0]
    edges = ImageStat.Stat(img.filter(ImageFilter.FIND_EDGES)).mean[0]
    brightness = ImageStat.Stat(img).mean[0]
    return contrast + edges * 1.5 - (0 if 40 < brightness < 200 else 25)


def own_frames(ctx, out: Path) -> list[Path]:
    """Sharpest frames from the video's own cut footage, one per film."""
    data = read_json(ctx.dir / "footage.json") if (ctx.dir / "footage.json").exists() else {}
    scored: list[tuple[float, str, Path]] = []
    for key, entry in data.items():
        for k, shot in enumerate(entry.get("shots", [])):
            clip = Path(shot["path"])
            frame = out / f"own-b{int(key):03d}-{k}.jpg"
            if clip.exists() and not frame.exists():
                subprocess.run(["ffmpeg", "-y", "-v", "error", "-ss", f"{shot['duration'] / 2:.2f}", "-i", str(clip),
                                "-frames:v", "1", str(frame)], check=False)
            if frame.exists():
                scored.append((frame_score(frame), shot["identifier"], frame))
    picked, films = [], set()
    for _, film, frame in sorted(scored, reverse=True):
        if film not in films:
            films.add(film)
            picked.append(frame)
    if not picked:
        cards_dir = ctx.dir / "render" / "cards"
        picked = sorted(cards_dir.glob("*.jpg")) if cards_dir.exists() else []
    return picked


def concept_frame(ctx, archive, panel: dict, tag: str, work: Path, used: dict[str, int]) -> Path | None:
    """Search archive.org for a frame matching one panel's brief."""
    query = str(panel.get("query", "")).strip()
    if not query:
        return None
    try:
        cands = footage.find_candidates(ctx, archive, query, 2.0, abs(hash(tag)) % 100000, used, 4, work)
    except Exception as exc:  # noqa: BLE001
        ctx.log.info("thumbnail: search '%s' failed: %s", query, exc)
        return None
    beat = {"text": panel.get("look_for", query),
            "visual": {"look_for": panel.get("look_for", query) + " It is for a thumbnail: one clear subject, strong contrast.",
                       "avoid": "text, title cards, cartoons, blur, black frames"}}
    best = footage.judge(ctx, beat, cands)
    if not best:
        return None
    c = best[0]
    used[c.film.identifier] = used.get(c.film.identifier, 0) + 1
    dest = work / f"{tag}.jpg"
    t = c.start + c.length / 2
    ok = subprocess.run(["ffmpeg", "-y", "-v", "error", "-ss", f"{t:.2f}", "-i", c.film.video_url, "-frames:v", "1",
                         "-vf", "scale='max(1280,iw)':-2", str(dest)], capture_output=True).returncode == 0
    return dest if ok and dest.exists() else None


def default_concepts(ctx) -> list[dict]:
    """No concept stage output: simple subject thumbnails from the package texts."""
    pkg = read_json(ctx.dir / "package.json") if (ctx.dir / "package.json").exists() else {}
    title = (pkg.get("titles") or [ctx.title])[0]
    return [{"layout": "subject", "text": t, "title": title, "panels": [], "device": "none"}
            for t in (pkg.get("thumbnail_texts") or [ctx.title])[:3]]


def run(ctx) -> None:
    out_dir = ctx.dir / "thumbnails"
    drafts_dir, work = out_dir / "drafts", out_dir / "frames"
    drafts_dir.mkdir(parents=True, exist_ok=True)
    work.mkdir(parents=True, exist_ok=True)

    packaging = read_json(ctx.dir / "packaging.json") if (ctx.dir / "packaging.json").exists() else {}
    concepts = packaging.get("thumbnail_concepts") or default_concepts(ctx)
    colors = ctx.pack.get("thumbnail.colors", {}) or {}
    font_path = ctx.pack.path / "fonts" / str(ctx.pack.get("shorts.captions.font", "Montserrat-VariableFont_wght.ttf"))
    keep = int(ctx.pack.get("packaging.thumbnail_variants", 3))

    fallback = own_frames(ctx, work)
    archive = footage.make_archive(ctx)
    used: dict[str, int] = {}
    drafts: list[thumbs.Draft] = []
    fb_i = 0
    for ci, concept in enumerate(concepts):
        layout = concept.get("layout", "subject")
        need = 2 if layout in {"split", "versus"} else 1
        panels = (concept.get("panels") or [])[:need]
        frames: list[Path] = []
        for pi in range(need):
            frame = concept_frame(ctx, archive, panels[pi], f"c{ci}-p{pi}", work, used) if pi < len(panels) else None
            if frame is None and fallback:
                frame = fallback[fb_i % len(fallback)]
                fb_i += 1
            if frame is not None:
                frames.append(frame)
        if len(frames) < need:
            if not frames:
                ctx.log.warning("thumbnail: no frame for concept %d", ci)
                continue
            layout = "subject"
        dest = drafts_dir / f"d{ci + 1:02d}-{layout}.jpg"
        labels = [p.get("label", "") for p in panels if p.get("label")]
        size = thumbs.render(layout, frames, concept.get("text", ""), dest, colors, font_path, labels,
                             concept.get("subtext", ""), concept.get("device", "none"))
        d = thumbs.Draft(dest, layout, concept.get("text", ""), concept.get("title", ctx.title), size)
        d.checks = thumbs.mobile_checks(dest, d.text, size)
        drafts.append(d)
    if not drafts:
        raise RuntimeError("No thumbnail drafts could be made")

    order = sorted(range(len(drafts)), key=lambda i: -drafts[i].checks["score"])
    reasons: dict[int, str] = {}
    if ctx.settings.vision_footage_check and len(drafts) > 1:
        sheet = thumbs.contact_sheet(drafts, out_dir / "judge_sheet.jpg")
        pairs = "\n".join(f"{i + 1}. title \"{d.title}\" · thumbnail text \"{d.text}\" · {d.layout}" for i, d in enumerate(drafts))
        from ..trends import load_library

        rules = "\n".join(f"- {r}" for r in load_library(ctx.settings).get("thumbnail_rules", [])) or "(none)"
        try:
            verdict = ctx.llm.complete_json(ctx.pack.prompt("thumb_judge", keep=str(keep), count=str(len(drafts)),
                                                            pairs=pairs, rules=rules),
                                            tier="deep", max_tokens=3000, images=[sheet])
            picks = [int(n) - 1 for n in verdict.get("pick", []) if 1 <= int(n) <= len(drafts)]
            ranked = [int(r["n"]) - 1 for r in verdict.get("ranking", []) if 1 <= int(r.get("n", 0)) <= len(drafts)]
            reasons = {int(r["n"]) - 1: f"{r.get('score', '')}: {r.get('why', '')} Fix: {r.get('fix', '')}"
                       for r in verdict.get("ranking", []) if 1 <= int(r.get("n", 0)) <= len(drafts)}
            order = list(dict.fromkeys(picks + ranked + order))
        except Exception as exc:  # noqa: BLE001
            ctx.log.warning("thumbnail: vision judging failed (%s); ranking by mobile checks", exc)

    for old in out_dir.glob("thumb*.jpg"):
        old.unlink()
    lines = [f"# Thumbnails: {ctx.title}", "", f"Test these {min(keep, len(order))} in YouTube's Test & Compare.", ""]
    for rank, i in enumerate(order[:keep], start=1):
        d = drafts[i]
        shutil.copy2(d.path, out_dir / f"thumb{rank}.jpg")
        lines.append(f"## thumb{rank}.jpg · `{d.layout}` · \"{d.text}\"")
        lines.append(f"- Pair with title: **{d.title}**")
        lines.append(f"- Phone-size check: {d.checks['score']}/100 (text ≈{d.checks['text_px_at_sidebar']}px in the sidebar, "
                     f"{d.checks['words']} words, contrast {d.checks['contrast']})")
        if i in reasons:
            lines.append(f"- Judge: {reasons[i]}")
        lines.append("")
    lines += ["## All drafts", ""] + [f"- drafts/{d.path.name}: `{d.layout}` \"{d.text}\" · phone check {d.checks['score']}" for d in drafts]
    write_text(out_dir / "thumbnails.md", "\n".join(lines) + "\n")
    write_json(out_dir / "thumbnails.json", [{"file": d.path.name, "layout": d.layout, "text": d.text, "title": d.title,
                                               "checks": d.checks} for d in drafts])
    render_dossier(ctx.dir, ctx.title, ctx.angle)
