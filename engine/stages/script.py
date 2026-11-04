"""Stage: script. Writes script.md, then scores it and rewrites until it passes.

The loop (from the viral-video-writing skill): draft, run the checker,
rewrite with every failed check listed, score again. Up to MAX_PASSES
rewrites; the best-scoring draft is kept. The checker report is saved to
script_check.md for your review.

Long videos follow the outline. Shorts (format "short") are written from the
parent video's dossier around one angle, and also produce the on-screen hook
text shown in the first seconds.
"""

from __future__ import annotations

import json
import re

from ..dossier import render
from ..scriptcheck import check, profile_for
from ..util import read_json, write_text
from .research import dossier_for_prompt

MAX_PASSES = 3
ON_SCREEN = re.compile(r"^\s*ON-SCREEN:\s*(.+)$", re.MULTILINE)


def clean(text: str) -> str:
    text = re.sub(r"^```[a-z]*\s*|\s*```$", "", text.strip())
    text = re.sub(r"</?script>", "", text)
    return text.strip() + "\n"


def _long_prompt(ctx, revision_notes: str) -> str:
    outline = read_json(ctx.dir / "outline.json")
    hook = outline["hooks"][outline.get("chosen_hook", 0)]["text"]
    outline_for_prompt = dict(outline)
    outline_for_prompt["hooks"] = [{"text": hook}]
    return ctx.pack.prompt(
        "script",
        dossier=dossier_for_prompt(ctx),
        outline=json.dumps(outline_for_prompt, indent=1, ensure_ascii=False),
        target_words=str(ctx.setting("target_words", 2000)),
        min_words=str(ctx.setting("min_words", 1700)),
        max_words=str(ctx.setting("max_words", 2600)),
        revision_notes=revision_notes,
    )


def _short_prompt(ctx, revision_notes: str) -> str:
    topic = read_json(ctx.dir / "topic.json") if (ctx.dir / "topic.json").exists() else {}
    return ctx.pack.prompt(
        "short_script",
        dossier=dossier_for_prompt(ctx),
        title=ctx.title,
        angle=ctx.angle,
        parent_title=str(topic.get("parent_title", "")),
        target_words=str(ctx.setting("target_words", 130)),
        min_words=str(ctx.setting("min_words", 100)),
        max_words=str(ctx.setting("max_words", 160)),
        revision_notes=revision_notes,
    )


def write(ctx, revision_notes: str = "") -> str:
    prompt = _short_prompt(ctx, revision_notes) if ctx.is_short else _long_prompt(ctx, revision_notes)
    return clean(ctx.llm.complete(prompt, tier="deep", max_tokens=16000))


def split_on_screen(text: str) -> tuple[str, str]:
    m = ON_SCREEN.search(text)
    if not m:
        return "", text
    return m.group(1).strip().strip('"'), (text[: m.start()] + text[m.end():]).strip() + "\n"


def run(ctx) -> None:
    profile = profile_for(ctx.pack, ctx.fmt)
    drafts: list[tuple[int, str, str, object]] = []

    notes = ""
    for attempt in range(MAX_PASSES + 1):
        on_screen, script = split_on_screen(write(ctx, notes))
        result = check(script, profile)
        drafts.append((result.score - (0 if result.passed else 1), script, on_screen, result))
        ctx.log.info("script pass %d: %s", attempt + 1, result.report().splitlines()[0])
        if result.passed:
            break
        notes = (
            "\n\nREWRITE. Your previous draft failed these checks. Fix every one, keep the structure, the facts "
            "and the quotes, and change nothing that already works.\n"
            + result.report()
            + f"\n<previous_draft>\n{script}\n</previous_draft>"
        )

    best_score, script, on_screen, result = max(drafts, key=lambda d: d[0])
    if not ctx.is_short and "## " not in script:
        raise RuntimeError("Script has no chapter headings; the format was not followed")

    write_text(ctx.path("script.md"), script)
    if ctx.is_short:
        write_text(ctx.path("on_screen.txt"), (on_screen or ctx.title) + "\n")
    report = [f"# Script check ({len(drafts)} draft{'s' if len(drafts) > 1 else ''})", ""]
    for i, (_, _, _, r) in enumerate(drafts, start=1):
        report += [f"## Draft {i}", r.report(), ""]
    write_text(ctx.path("script_check.md"), "\n".join(report))
    ctx.log.info("script: kept draft scoring %d (%d words)", result.score, result.words)
    if not ctx.is_short:
        render(ctx.dir, ctx.title, ctx.angle)
