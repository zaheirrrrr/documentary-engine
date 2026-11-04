"""Render the project's dossier.md from everything the pipeline has produced.

The dossier is regenerated after each writing stage, so it always shows the
current state of the topic. Your own notes go in notes.md (never
overwritten) and are included at the end.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from .util import read_json, write_text


def _load(path: Path) -> Any:
    return read_json(path) if path.exists() else None


def _bullets(items: list[str]) -> str:
    return "\n".join(f"- {i}" for i in items) if items else "_None yet._"


def render(project_dir: Path, title: str, angle: str) -> Path:
    d = _load(project_dir / "dossier.json") or {}
    outline = _load(project_dir / "outline.json") or {}
    factcheck = _load(project_dir / "factcheck.json") or {}
    credits = _load(project_dir / "credits.json") or {}
    package = _load(project_dir / "package.json") or {}
    script_path = project_dir / "script.md"
    notes_path = project_dir / "notes.md"

    out: list[str] = [f"# {title}", "", f"_{angle}_", ""]
    if d.get("summary"):
        out += ["## Summary", d["summary"], ""]
    arc = d.get("arc") or {}
    if arc:
        out += ["## Story arc"] + [f"- **{k.title()}**: {v}" for k, v in arc.items() if v] + [""]

    # 1. Discoveries, grouped by theme
    out.append("## 1. Discoveries")
    by_theme: dict[str, list[dict]] = {}
    for item in d.get("discoveries", []):
        by_theme.setdefault(item.get("theme") or "General", []).append(item)
    if not by_theme:
        out.append("_None yet._")
    for theme, items in by_theme.items():
        out.append(f"\n**{theme.title()}**")
        for i in items:
            flag = "" if i.get("verified", True) else " (verify)"
            out.append(f"- {i.get('fact', '')}{flag} [{i.get('source', '')}]")
    out.append("")

    out.append("## 2. Key numbers")
    nums = d.get("key_numbers", [])
    if nums:
        out.append("| What | Value | Today | Source |\n|---|---|---|---|")
        for n in nums:
            out.append(f"| {n.get('what','')} | {n.get('value','')} | {n.get('modern_equivalent','')} | {n.get('source','')} |")
    else:
        out.append("_None yet._")
    out.append("")

    out.append("## 3. Cast")
    for p in d.get("cast", []) or []:
        out.append(f"- **{p.get('name','')}** ({p.get('years','')}), {p.get('role','')}. {p.get('detail','')} _Why:_ {p.get('why','')}")
    out.append("")

    out.append("## 4. Timeline")
    for t in d.get("timeline", []) or []:
        out.append(f"- **{t.get('date','')}**: {t.get('event','')} [{t.get('source','')}]")
    out.append("")

    out.append("## 5. Quotes on record")
    for q in d.get("quotes", []) or []:
        flag = "" if q.get("verified") else " **(verify: not matched in fetched source text)**"
        who = ", ".join(x for x in (q.get("speaker"), q.get("publication"), q.get("date")) if x)
        out.append(f"> {q.get('text','')}\n\n— {who} [{q.get('source','')}]{flag}\n")
    out.append("")

    out.append("## 6. Source shelf")
    out.append(_bullets([f"[{s.get('title','')}]({s.get('url','')}) {s.get('note','')}" for s in d.get("source_shelf", []) or []]))
    out.append("")

    out.append("## 7. Visual plan")
    out.append(_bullets(d.get("visual_plan", []) or []))
    out.append("")

    out.append("## 8. Credits")
    out.append(_bullets(credits.get("footage", []) + credits.get("music", [])) if credits else "_Filled in by the footage stage._")
    out.append("")

    out.append("## 9. Open questions")
    out.append(_bullets(d.get("open_questions", []) or []))
    out.append("")

    out.append("## 10. Must-include")
    out.append(_bullets(d.get("must_include", []) or []))
    out.append("")

    out.append("## 11. Cutting room")
    cut: list[str] = []
    hooks = outline.get("hooks", [])
    chosen = outline.get("chosen_hook", 0)
    for i, h in enumerate(hooks):
        if i != chosen:
            cut.append(f"Unused cold open ({h.get('entry_point','')}, score {h.get('score','')}): {h.get('text','')}")
    for p in factcheck.get("problems", []) or []:
        cut.append(f"Fact-check removed/changed: \"{p.get('sentence','')}\" ({p.get('issue','')})")
    out.append(_bullets(cut))
    out.append("")

    out.append("## 12. Thumbnail")
    thumbs = sorted((project_dir / "thumbnails").glob("*.jpg")) if (project_dir / "thumbnails").exists() else []
    if thumbs:
        out.append("\n".join(f"![{t.name}](thumbnails/{t.name})" for t in thumbs))
    elif package.get("thumbnail_texts"):
        out.append(_bullets(package["thumbnail_texts"]))
    else:
        out.append("_Made by the thumbnail stage._")
    out.append("")

    out.append("## 13. Script")
    out.append(script_path.read_text(encoding="utf-8") if script_path.exists() else "_Written by the script stage._")
    out.append("")

    out.append("## 14. Post-release notes")
    out.append(notes_path.read_text(encoding="utf-8") if notes_path.exists() else "_Add notes with: de notes <id> \"...\"_")
    out.append("")

    path = project_dir / "dossier.md"
    write_text(path, "\n".join(out))
    return path
