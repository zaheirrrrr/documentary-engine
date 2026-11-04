"""Stage: package. Everything you need at upload time, in upload_pack.md:
title options, thumbnail text, a description with chapters, sources and
footage credits, tags and a pinned comment."""

from __future__ import annotations

from ..scriptdoc import chapter_titles
from ..util import read_json, write_json, write_text

DESCRIPTION_LIMIT = 4900
TAGS_LIMIT = 480


def stamp(seconds: float) -> str:
    s = int(seconds)
    h, rem = divmod(s, 3600)
    m, s = divmod(rem, 60)
    return f"{h}:{m:02d}:{s:02d}" if h else f"{m}:{s:02d}"


def chapters(ctx) -> list[tuple[float, str]]:
    beats = read_json(ctx.dir / "shotlist.json")["beats"]
    timing = {t["id"]: t for t in read_json(ctx.dir / "timing.json")["beats"]}
    titles = dict(chapter_titles((ctx.dir / "script.md").read_text(encoding="utf-8")))
    marks: list[tuple[float, str]] = [(0.0, "Intro")]
    seen = {0}
    for b in beats:
        c = b["chapter"]
        if c not in seen:
            seen.add(c)
            marks.append((timing[b["id"]]["start"], titles.get(c) or f"Part {c}"))
    if marks and len(marks) > 1 and marks[1][0] < 10:   # no cold open: first chapter starts at 0
        marks = [(0.0, marks[1][1])] + marks[2:]
    # YouTube rules: each chapter at least 10 seconds apart.
    clean = [marks[0]]
    for t, title in marks[1:]:
        if t - clean[-1][0] >= 10:
            clean.append((t, title))
    return clean if len(clean) >= 3 else []


def run(ctx) -> None:
    script = (ctx.dir / "script.md").read_text(encoding="utf-8")
    dossier = read_json(ctx.dir / "dossier.json")
    data = ctx.llm.complete_json(
        ctx.pack.prompt("package", script=script, summary=dossier.get("summary", "")), tier="fast", max_tokens=4000
    )
    write_json(ctx.path("package.json"), data)

    credits = read_json(ctx.dir / "credits.json") if (ctx.dir / "credits.json").exists() else {}
    marks = chapters(ctx)

    parts = [data.get("description_hook", "").strip(), "", data.get("description_body", "").strip(), ""]
    if marks:
        parts += ["CHAPTERS"] + [f"{stamp(t)} {title}" for t, title in marks] + [""]
    sources = [s for s in dossier.get("source_shelf", []) if s.get("url")]
    if sources:
        parts += ["SOURCES"] + [f"- {s.get('title','')}: {s['url']}" for s in sources[:15]] + [""]
    if credits.get("footage"):
        parts += ["ARCHIVAL FOOTAGE"] + [f"- {c}" for c in credits["footage"]] + [""]
    if credits.get("music"):
        parts += ["MUSIC"] + [f"- {c}" for c in credits["music"]] + [""]
    footer = ctx.pack.get("package.footer", "")
    if footer:
        parts.append(footer)
    description = "\n".join(parts).strip()
    if len(description) > DESCRIPTION_LIMIT:
        description = description[:DESCRIPTION_LIMIT].rsplit("\n", 1)[0] + "\n(Full source list in the pinned comment.)"

    tags: list[str] = []
    for t in data.get("tags", []):
        if len(", ".join(tags + [t])) > TAGS_LIMIT:
            break
        tags.append(t)

    lines = [f"# Upload pack: {ctx.title}", "", "## Title options"]
    lines += [f"{i}. {t}  _({len(t)} chars)_" for i, t in enumerate(data.get("titles", []), start=1)]
    lines += ["", "## Thumbnail text options"] + [f"- {t}" for t in data.get("thumbnail_texts", [])]
    lines += ["", "Draft thumbnails are in `thumbnails/`.", "", "## Description (copy everything in the box)", "", "```", description, "```"]
    lines += ["", "## Tags", "", "```", ", ".join(tags), "```"]
    lines += ["", "## Pinned comment", "", data.get("pinned_comment", "")]
    lines += ["", "## Files", "- Video: `final.mp4`", "- Captions: `captions.srt` (upload under Subtitles)", ""]
    lines += [
        "## Before you press publish",
        "- [ ] Watched the whole video",
        "- [ ] Checked factcheck.md items marked 'Still needs your eyes'",
        "- [ ] Uploaded as Private first and waited for YouTube's copyright check",
        "- [ ] Answered YouTube's altered or synthetic content question honestly",
        "- [ ] Added the thumbnail, captions, chapters (in description) and end screen",
    ]
    write_text(ctx.path("upload_pack.md"), "\n".join(lines) + "\n")
    write_text(ctx.path("description.txt"), description + "\n")
