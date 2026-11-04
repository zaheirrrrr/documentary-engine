"""Stage: outline. Five cold-open hooks (best one chosen) and the chapter plan."""

from __future__ import annotations

import json

from ..dossier import render
from ..util import write_json
from .research import dossier_for_prompt


def run(ctx) -> None:
    v = ctx.pack.get("video", {})
    prompt = ctx.pack.prompt(
        "outline",
        dossier=dossier_for_prompt(ctx),
        target_words=str(v.get("target_words", 2000)),
        chapters_min=str(v.get("chapters_min", 5)),
        chapters_max=str(v.get("chapters_max", 8)),
    )
    outline = ctx.llm.complete_json(prompt, tier="deep", max_tokens=12000)

    hooks = outline.get("hooks") or []
    if not hooks or not outline.get("chapters"):
        raise RuntimeError("Outline is missing hooks or chapters")
    # Trust the scores over the model's own pick if they disagree.
    best = max(range(len(hooks)), key=lambda i: hooks[i].get("score", 0))
    outline["chosen_hook"] = best

    write_json(ctx.path("outline.json"), outline)
    lines = ["# Hooks (best first)", ""]
    for i in sorted(range(len(hooks)), key=lambda i: -hooks[i].get("score", 0)):
        mark = " ← chosen" if i == best else ""
        lines += [f"## Hook {i + 1}, score {hooks[i].get('score')}{mark}", hooks[i].get("text", ""), f"_{hooks[i].get('why', '')}_", ""]
    lines += ["# Chapters", "", "```json", json.dumps(outline["chapters"], indent=2, ensure_ascii=False), "```"]
    ctx.path("outline.md").write_text("\n".join(lines), encoding="utf-8")
    render(ctx.dir, ctx.title, ctx.angle)
