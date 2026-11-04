"""Packaging research: what makes people click, reverse-engineered for this
channel. Run with `de trends`; refresh every couple of weeks.

1. Pull recent videos from leading channels across niches and from channels
   in our niche, and keep the outliers (videos that beat their own channel's
   median by min_outlier or more).
2. Titles: Claude extracts reusable title formulas from the outlier titles.
   Each formula's strength is then measured in code from the real outlier
   multiples of the example titles it cites, so the evidence is not invented.
3. Thumbnails: the top outlier thumbnails are tiled into numbered grids;
   Claude vision tags each one (layout, words, devices, emotion, contrast);
   the tags are counted, weighted by outlier multiple, and turned into
   thumbnail patterns this channel can build from period footage.
4. Topics: niche outliers are grouped into currently over-performing themes
   with topic ideas for this channel (fed into `de discover`).

Output: workspace/research/library.json (used by the concept and thumbnail
stages and by discover) plus a readable library.md and the thumbnail grids.
"""

from __future__ import annotations

import json
import statistics
from collections import Counter, defaultdict
from datetime import date, datetime
from pathlib import Path
from typing import Callable

from PIL import Image, ImageDraw

from .cards import SANS_BOLD, font
from .config import Pack, Settings
from .llm import LLM
from .sources import youtube
from .state import State
from .util import http_download, http_session, log, read_json, write_json, write_text


def library_path(settings: Settings) -> Path:
    return settings.research_dir / "library.json"


def load_library(settings: Settings) -> dict:
    path = library_path(settings)
    return read_json(path) if path.exists() else {}


def library_age_days(settings: Settings) -> int | None:
    lib = load_library(settings)
    if not lib.get("created"):
        return None
    return (date.today() - datetime.fromisoformat(lib["created"]).date()).days


def _title_lines(videos: list[youtube.Video], limit: int) -> str:
    return "\n".join(f"- [{v.outlier:.1f}x | {v.views:,} views | {v.channel}] {v.title}" for v in videos[:limit])


def formula_evidence(formulas: list[dict], videos: list[youtube.Video]) -> list[dict]:
    """Attach real outlier stats to each formula from the example titles it cites."""
    by_title = {v.title.strip().lower(): v for v in videos}
    for f in formulas:
        hits = [by_title[e.strip().lower()] for e in f.get("examples", []) if e.strip().lower() in by_title]
        f["evidence_count"] = len(hits)
        f["evidence_median_outlier"] = round(statistics.median(v.outlier for v in hits), 1) if hits else 0.0
        f["evidence"] = [{"title": v.title, "channel": v.channel, "outlier": v.outlier, "url": v.url} for v in hits]
        # Strength blends proof and fit; formulas with no matched evidence sink.
        f["strength"] = round(min(10.0, f["evidence_median_outlier"]) * 0.6 + float(f.get("fit", 5)) * 0.4, 2) if hits else 0.0
    return sorted(formulas, key=lambda f: f["strength"], reverse=True)


def thumb_grids(videos: list[youtube.Video], out_dir: Path, session, per_grid: int = 12) -> list[tuple[Path, list[youtube.Video]]]:
    """Download thumbnails and tile them into numbered 4x3 grids."""
    out_dir.mkdir(parents=True, exist_ok=True)
    ok: list[tuple[youtube.Video, Path]] = []
    for v in videos:
        dest = out_dir / "thumbs" / f"{v.id}.jpg"
        try:
            http_download(session, v.thumb, dest, timeout=30)
            ok.append((v, dest))
        except Exception as exc:  # noqa: BLE001
            log.info("trends: thumbnail %s failed: %s", v.id, exc)
    grids = []
    label_font = font(SANS_BOLD, 30)
    for g in range(0, len(ok), per_grid):
        chunk = ok[g:g + per_grid]
        cols, tw, th, pad = 4, 320, 180, 6
        rows = (len(chunk) + cols - 1) // cols
        sheet = Image.new("RGB", (cols * (tw + pad) + pad, rows * (th + pad) + pad), "white")
        for i, (v, path) in enumerate(chunk):
            img = Image.open(path).convert("RGB").resize((tw, th))
            x, y = pad + (i % cols) * (tw + pad), pad + (i // cols) * (th + pad)
            sheet.paste(img, (x, y))
            d = ImageDraw.Draw(sheet)
            d.rectangle((x, y, x + 44, y + 38), fill="black")
            d.text((x + 8, y + 2), str(i + 1), font=label_font, fill="yellow")
        path = out_dir / f"grid{g // per_grid + 1:02d}.jpg"
        sheet.save(path, quality=88)
        grids.append((path, [v for v, _ in chunk]))
    return grids


def thumb_stats(tags: list[dict]) -> dict:
    """Count features, weighting each thumbnail by its outlier multiple."""
    stats: dict[str, Counter] = defaultdict(Counter)
    total = sum(t.get("_outlier", 1.0) for t in tags) or 1.0
    for t in tags:
        w = t.get("_outlier", 1.0)
        for key in ("layout", "emotion", "contrast", "title_relation", "focal_points"):
            stats[key][str(t.get(key, ""))] += w
        stats["face"][str(bool(t.get("face")))] += w
        words = int(t.get("text_words", 0) or 0)
        stats["text_words"]["0" if words == 0 else "1-3" if words <= 3 else "4-5" if words <= 5 else "6+"] += w
        for dev in t.get("devices", []) or []:
            stats["devices"][dev] += w
    return {k: {kk: round(vv / total * 100, 1) for kk, vv in c.most_common(8)} for k, c in stats.items()}


def run(settings: Settings, state: State, pack: Pack, echo: Callable[[str], None] = print) -> Path:
    cfg = pack.get("packaging", {}) or {}
    session = http_session(settings.user_agent)
    yt = youtube.client(session, settings.youtube_api_key)
    llm = LLM(settings, usage_hook=lambda s, u, unit, d: state.log_usage(None, s, u, unit, d))
    limit, min_x = int(cfg.get("videos_per_channel", 60)), float(cfg.get("min_outlier", 2.0))

    stamp = date.today().isoformat()
    out = settings.research_dir / stamp
    out.mkdir(parents=True, exist_ok=True)

    echo("Reference channels (across niches):")
    ref, ref_failed = youtube.outliers_for(yt, cfg.get("reference_channels", []), limit, min_x, echo)
    echo("Niche channels:")
    niche, niche_failed = youtube.outliers_for(yt, cfg.get("niche_channels", []), limit, min_x, echo)
    everything = sorted(ref + niche, key=lambda v: v.outlier, reverse=True)
    write_json(out / "outliers.json", {"reference": [v.to_dict() for v in ref], "niche": [v.to_dict() for v in niche]})
    if len(everything) < 10:
        raise RuntimeError(f"Only {len(everything)} outliers found; check the channel handles and your YouTube access")

    echo(f"Studying {len(everything)} outlier titles...")
    titles = llm.complete_json(pack.prompt("trends_titles", titles=_title_lines(everything, 220)),
                               tier="deep", max_tokens=12000)
    formulas = formula_evidence(titles.get("formulas", []), everything)

    n_thumbs = int(cfg.get("max_thumbnails_studied", 48))
    echo(f"Studying the top {n_thumbs} thumbnails...")
    tags: list[dict] = []
    for grid, vids in thumb_grids(everything[:n_thumbs], out, session):
        listing = "\n".join(f"{i + 1}. {v.title} ({v.outlier:.1f}x)" for i, v in enumerate(vids))
        try:
            data = llm.complete_json(pack.prompt("trends_thumbs", count=str(len(vids)), titles=listing),
                                     tier="deep", max_tokens=8000, images=[grid])
        except Exception as exc:  # noqa: BLE001
            echo(f"  ! {grid.name}: {exc}")
            continue
        for t in data.get("thumbnails", []):
            idx = int(t.get("n", 0)) - 1
            if 0 <= idx < len(vids):
                t.update(_outlier=vids[idx].outlier, _title=vids[idx].title, _id=vids[idx].id, _grid=grid.name)
                tags.append(t)
    stats = thumb_stats(tags)
    examples = "\n".join(f"- {t['_outlier']:.1f}x \"{t['_title']}\": {t.get('layout')}, text \"{t.get('text','')}\", "
                         f"{t.get('emotion')}, devices {t.get('devices', [])}. {t.get('why','')}"
                         for t in sorted(tags, key=lambda t: -t["_outlier"])[:25])
    thumbs = llm.complete_json(pack.prompt("trends_thumb_patterns", stats=json.dumps(stats, indent=1), examples=examples),
                               tier="deep", max_tokens=8000) if tags else {}

    echo("Finding over-performing topic themes in our niche...")
    recent = [v for v in niche if v.published >= f"{date.today().year - 1}-{date.today():%m-%d}"] or niche
    topics = llm.complete_json(pack.prompt("trends_topics", titles=_title_lines(recent, 120)),
                               tier="deep", max_tokens=8000, web_search=False) if niche else {"themes": []}

    library = {
        "created": stamp,
        "counts": {"reference_outliers": len(ref), "niche_outliers": len(niche), "thumbnails_tagged": len(tags)},
        "failed_channels": ref_failed + niche_failed,
        "title_formulas": formulas,
        "title_principles": titles.get("principles", []),
        "title_avoid": titles.get("avoid", []),
        "thumbnail_stats": stats,
        "thumbnail_patterns": thumbs.get("patterns", []),
        "thumbnail_rules": thumbs.get("rules", []),
        "thumbnail_avoid": thumbs.get("avoid", []),
        "topic_themes": topics.get("themes", []),
        "top_outliers": [v.to_dict() for v in everything[:40]],
    }
    write_json(out / "thumbnail_tags.json", tags)
    write_json(out / "library.json", library)
    write_json(library_path(settings), library)
    write_text(out / "library.md", render_md(library))
    write_text(settings.research_dir / "library.md", render_md(library))
    return settings.research_dir / "library.md"


def render_md(lib: dict) -> str:
    c = lib.get("counts", {})
    out = [f"# Packaging library ({lib.get('created')})", "",
           f"{c.get('reference_outliers', 0)} cross-niche outliers, {c.get('niche_outliers', 0)} niche outliers, "
           f"{c.get('thumbnails_tagged', 0)} thumbnails tagged.", ""]
    if lib.get("failed_channels"):
        out += [f"Channels not found (fix in pack.yaml): {', '.join(lib['failed_channels'])}", ""]
    out += ["## Title formulas (strongest first)", ""]
    for f in lib.get("title_formulas", []):
        out += [f"### `{f.get('template')}`  · strength {f.get('strength')} · median {f.get('evidence_median_outlier')}x over {f.get('evidence_count')} proven titles",
                f"_{f.get('mechanism', '')}_", ""]
        out += [f"- Proven: \"{e['title']}\" ({e['channel']}, {e['outlier']}x)" for e in f.get("evidence", [])]
        out += [f"- For us: {a}" for a in f.get("adaptations", [])] + [""]
    out += ["## Title principles"] + [f"- {p}" for p in lib.get("title_principles", [])]
    out += ["", "## Titles to avoid"] + [f"- {p}" for p in lib.get("title_avoid", [])]
    out += ["", "## Thumbnail patterns", ""]
    for p in lib.get("thumbnail_patterns", []):
        out += [f"### {p.get('name')} (`{p.get('layout')}`)", f"{p.get('why_it_works', '')}",
                f"- Use when: {p.get('when_to_use', '')}", f"- Text: {p.get('text_rule', '')} (e.g. \"{p.get('example_text', '')}\")",
                f"- Frame: {p.get('frame_brief', '')}", ""]
    out += ["## Thumbnail rules"] + [f"- {r}" for r in lib.get("thumbnail_rules", [])]
    out += ["", "## What top thumbnails have in common (% of outlier-weighted sample)", "", "```",
            json.dumps(lib.get("thumbnail_stats", {}), indent=1), "```", ""]
    out += ["## Over-performing topic themes in our niche", ""]
    for t in lib.get("topic_themes", []):
        out += [f"### {t.get('theme')}", t.get("why_now", ""), ""]
        out += [f"- Evidence: {e}" for e in t.get("evidence", [])]
        out += [f"- Idea: {i}" for i in t.get("topic_ideas", [])] + [""]
    out += ["## Top outliers", ""]
    out += [f"- {v['outlier']}x · {v['channel']} · [{v['title']}]({v['url']})" for v in lib.get("top_outliers", [])]
    return "\n".join(out) + "\n"
