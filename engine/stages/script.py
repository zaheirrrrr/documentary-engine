"""Stage: script. Writes script.md from the outline, within the word budget."""

from __future__ import annotations

import json
import re

from ..dossier import render
from ..scriptdoc import narration_text
from ..util import read_json, words, write_text
from .research import dossier_for_prompt


def clean(text: str) -> str:
    text = re.sub(r"^```[a-z]*\s*|\s*```$", "", text.strip())
    text = re.sub(r"</?script>", "", text)
    return text.strip() + "\n"


def write(ctx, revision_notes: str = "") -> str:
    v = ctx.pack.get("video", {})
    outline = read_json(ctx.dir / "outline.json")
    hook = outline["hooks"][outline.get("chosen_hook", 0)]["text"]
    outline_for_prompt = dict(outline)
    outline_for_prompt["hooks"] = [{"text": hook}]
    prompt = ctx.pack.prompt(
        "script",
        dossier=dossier_for_prompt(ctx),
        outline=json.dumps(outline_for_prompt, indent=1, ensure_ascii=False),
        target_words=str(v.get("target_words", 2000)),
        min_words=str(v.get("min_words", 1700)),
        max_words=str(v.get("max_words", 2600)),
        revision_notes=revision_notes,
    )
    return clean(ctx.llm.complete(prompt, tier="deep", max_tokens=16000))


def run(ctx) -> None:
    v = ctx.pack.get("video", {})
    lo, hi = int(v.get("min_words", 1700)), int(v.get("max_words", 2600))

    script = write(ctx)
    count = words(narration_text(script))
    if not lo <= count <= hi:
        direction = "longer" if count < lo else "shorter"
        ctx.log.info("script: %d words, outside %d-%d; rewriting %s", count, lo, hi, direction)
        previous = f"\n\nYour previous draft was {count} words. Make this version {direction}, within {lo}-{hi} words, keeping the same structure.\n<previous_draft>\n{script}\n</previous_draft>"
        script = write(ctx, revision_notes=previous)
        count = words(narration_text(script))

    if "## " not in script:
        raise RuntimeError("Script has no chapter headings; the format was not followed")
    write_text(ctx.path("script.md"), script)
    ctx.log.info("script: %d words (~%.1f min)", count, count / float(v.get("words_per_minute", 150)))
    render(ctx.dir, ctx.title, ctx.angle)
