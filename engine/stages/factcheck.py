"""Stage: factcheck. Every claim in the script is checked against the dossier.

Problems are fixed automatically where the fix is an exact sentence swap, the
script is checked again, and anything left is listed in factcheck.md for you
to settle at the script review.
"""

from __future__ import annotations

import re

from ..dossier import render
from ..scriptdoc import parse_blocks
from ..util import normalise_for_match, read_json, write_json, write_text
from .research import dossier_for_prompt


def _check(ctx, script: str) -> dict:
    prompt = ctx.pack.prompt("factcheck", dossier=dossier_for_prompt(ctx), script=script)
    result = ctx.llm.complete_json(prompt, tier="deep", max_tokens=10000)
    result.setdefault("problems", [])
    return result


def quote_report(ctx, script: str) -> list[str]:
    """Script quotes must match a dossier quote; unverified ones are flagged."""
    dossier = read_json(ctx.dir / "dossier.json")
    known = [(normalise_for_match(q.get("text", "")), q) for q in dossier.get("quotes", [])]
    notes = []
    for block in parse_blocks(script):
        if block.kind != "quote":
            continue
        text = normalise_for_match(block.text.replace("...", " ").replace("…", " "))
        match = next((q for k, q in known if text[:60] in k or k[:60] in text), None)
        if match is None:
            notes.append(f"Quote not found in dossier: \"{block.text[:90]}...\"")
        elif not match.get("verified"):
            notes.append(f"Quote not matched word for word in a fetched source; check it: \"{block.text[:90]}...\" [{match.get('source','')}]")
    return notes


INSTRUCTION = re.compile(r"(remove|delete|cut|drop|omit)\b.*\b(sentence|line|claim)\b", re.I)


def run(ctx) -> None:
    script_path = ctx.dir / "script.md"
    script = script_path.read_text(encoding="utf-8")

    first = _check(ctx, script)
    applied, unresolved = [], []
    for p in first["problems"]:
        sentence, fix = p.get("sentence", "").strip(), p.get("fix", "").strip()
        if INSTRUCTION.match(fix):
            fix = ""  # "Remove the sentence..." is an editor's note, not narration
        if sentence and sentence in script:
            script = script.replace(sentence, fix, 1)
            if not fix:
                script = re.sub(r"[ \t]{2,}", " ", script)
            applied.append(p)
        else:
            unresolved.append(p)

    second = _check(ctx, script) if applied else first
    write_text(script_path, script)
    write_json(ctx.path("factcheck.json"), {"round1": first, "applied": applied, "final": second, "problems": applied + second["problems"]})

    quote_notes = quote_report(ctx, script)
    lines = ["# Fact-check report", "", f"Supported claims (final pass): {second.get('supported_count', '?')}", ""]
    lines.append("## Fixed automatically")
    lines += [f"- ~~{p['sentence']}~~ → {p['fix']} _({p.get('issue','')})_" for p in applied] or ["- None"]
    lines += ["", "## Still needs your eyes"]
    remaining = second["problems"] if applied else unresolved
    lines += [f"- **{p.get('status')}**: \"{p.get('sentence','')}\" ({p.get('issue','')}). Suggested: {p.get('fix','')}" for p in remaining] or ["- None"]
    lines += ["", "## Quotes"]
    lines += [f"- {n}" for n in quote_notes] or ["- All script quotes match verified dossier quotes."]
    write_text(ctx.path("factcheck.md"), "\n".join(lines) + "\n")
    render(ctx.dir, ctx.title, ctx.angle)
