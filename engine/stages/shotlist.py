"""Stage: shotlist. Splits the approved script into beats and picks a visual
for each one.

The split is done in code, never by the model, so the beats always contain
the script's exact words in order. Claude only chooses the visuals.
"""

from __future__ import annotations

import json

from ..scriptdoc import build_beats
from ..util import write_json

GENERIC_QUERIES = ["city street", "factory workers", "crowd", "industry", "railroad", "office"]


def run(ctx) -> None:
    script = (ctx.dir / "script.md").read_text(encoding="utf-8")
    beats = build_beats(script, max_words=int(ctx.setting("max_beat_words", 24)))
    if not beats:
        raise RuntimeError("Script produced no beats")

    listing = json.dumps(
        [{"id": b.id, "kind": b.kind, "chapter": b.chapter_title, "text": b.text} for b in beats],
        indent=1, ensure_ascii=False,
    )
    data = ctx.llm.complete_json(ctx.pack.prompt("shotlist", title=ctx.title, beats=listing),
                                 tier="fast", max_tokens=16000)
    visuals = {int(v["id"]): v for v in data.get("beats", []) if "id" in v}

    out = []
    missing = 0
    for b in beats:
        entry = b.to_dict()
        if b.kind == "quote":
            entry["visual"] = {"visual": "quote"}
        else:
            v = visuals.get(b.id)
            if not v or v.get("visual") not in {"archival", "number"} or (v.get("visual") == "archival" and not v.get("query")):
                missing += 1
                v = {"visual": "archival", "query": GENERIC_QUERIES[b.id % len(GENERIC_QUERIES)],
                     "alt_query": "america", "look_for": "period footage matching the narration", "avoid": "text, cartoons"}
            entry["visual"] = v
        out.append(entry)

    write_json(ctx.path("shotlist.json"), {"beats": out})
    ctx.log.info("shotlist: %d beats (%d quotes, %d given generic visuals)",
                 len(out), sum(1 for b in beats if b.kind == "quote"), missing)
