"""Stage: concept. Title and thumbnail first, script second.

1. Claude writes many title candidates by adapting the proven formulas from
   the packaging library (`de trends`) to this story.
2. The title checker drops anything with a hard fail (too long, ALL CAPS,
   clickbait, emoji).
3. Claude judges the survivors like a viewer scrolling the home feed
   (clarity, curiosity, specificity, stakes, truth, fit). Final rank blends
   the judge (70%), the checker (15%) and the proven strength of the formula
   it came from (15%). Titles that oversell the story (truth below 7) are out.
4. Thumbnail concepts are designed for the top titles from the library's
   thumbnail patterns, each with the footage searches its frames need.

The outline and script are then written to deliver the chosen title's
promise. You can change the chosen title in packaging.json at the script
review.
"""

from __future__ import annotations

import json

from ..titles import check_title
from ..trends import load_library
from ..util import read_json, write_json, write_text


def story_brief(ctx) -> str:
    d = read_json(ctx.dir / "dossier.json")
    keep = {k: d.get(k) for k in ("summary", "arc", "key_numbers", "cast", "timeline") if d.get(k)}
    keep["quotes"] = [q.get("text", "")[:200] for q in d.get("quotes", [])[:6]]
    return json.dumps(keep, indent=1, ensure_ascii=False)


def run(ctx) -> None:
    lib = load_library(ctx.settings)
    cfg = ctx.pack.get("packaging", {}) or {}
    story = story_brief(ctx)
    if not lib:
        ctx.log.warning("concept: no packaging library yet; run `de trends` for formulas backed by real outliers")

    formulas = lib.get("title_formulas", [])[:16]
    formula_text = "\n".join(
        f"- id {f['id']} | strength {f.get('strength', 0)} | median {f.get('evidence_median_outlier', 0)}x: "
        f"{f.get('template')} ({f.get('mechanism', '')}). Proven: "
        + "; ".join(f"\"{e['title']}\" {e['outlier']}x" for e in f.get("evidence", [])[:3])
        for f in formulas
    ) or "(No library yet. Use the title formulas you know to be proven on YouTube documentaries.)"

    data = ctx.llm.complete_json(ctx.pack.prompt(
        "concept_titles", story=story, formulas=formula_text,
        principles="\n".join(f"- {p}" for p in lib.get("title_principles", [])) or "(none yet)",
        avoid="\n".join(f"- {p}" for p in lib.get("title_avoid", [])) or "(none yet)",
        count=str(int(cfg.get("titles_generated", 24))),
    ), tier="deep", max_tokens=8000)

    candidates = []
    rejected = []
    seen = set()
    for c in data.get("titles", []):
        title = str(c.get("title", "")).strip()
        if not title or title.lower() in seen:
            continue
        seen.add(title.lower())
        chk = check_title(title)
        c["check"] = {"score": chk.score, "hard": chk.hard, "soft": chk.soft}
        (candidates if chk.ok else rejected).append(c)
    if not candidates:
        raise RuntimeError("Every title candidate failed the title checker")

    listing = "\n".join(f"{i}. {c['title']}  (promise: {c.get('promise', '')})" for i, c in enumerate(candidates, start=1))
    judged = ctx.llm.complete_json(ctx.pack.prompt("concept_judge", story=story, candidates=listing),
                                   tier="deep", max_tokens=8000)
    strength = {f["id"]: float(f.get("strength", 0)) for f in formulas}
    for s in judged.get("scores", []):
        i = int(s.get("i", 0)) - 1
        if 0 <= i < len(candidates):
            candidates[i]["judge"] = s
    for c in candidates:
        j = c.get("judge", {})
        truthful = float(j.get("truth", 0)) >= 7
        c["rank_score"] = round(
            (float(j.get("overall", 0)) * 0.7 + c["check"]["score"] / 10 * 0.15
             + strength.get(c.get("formula_id", ""), 5.0) * 0.15) if truthful else 0.0, 2)
    candidates.sort(key=lambda c: c["rank_score"], reverse=True)
    kept = [c for c in candidates if c["rank_score"] > 0][: int(cfg.get("titles_kept", 6))] or candidates[:3]

    top = kept[:3]
    titles_for_thumbs = "\n".join(f"{i}. {c['title']} (promise: {c.get('promise', '')})" for i, c in enumerate(top, start=1))
    patterns = lib.get("thumbnail_patterns", [])
    thumbs = ctx.llm.complete_json(ctx.pack.prompt(
        "concept_thumbs", story=story, titles=titles_for_thumbs,
        patterns=json.dumps(patterns, indent=1, ensure_ascii=False) if patterns else "(No library yet. Use the four layouts below.)",
        rules="\n".join(f"- {r}" for r in lib.get("thumbnail_rules", [])) or "(none yet)",
        count=str(max(4, int(cfg.get("thumbnail_variants", 3)) + 2)),
    ), tier="deep", max_tokens=6000)
    concepts = [c for c in thumbs.get("concepts", []) if c.get("layout") in {"split", "versus", "subject", "number"} and c.get("panels")]
    for c in concepts:
        idx = int(c.get("for_title", 1)) - 1
        c["title"] = top[idx]["title"] if 0 <= idx < len(top) else top[0]["title"]

    packaging = {"chosen_title": kept[0]["title"], "promise": kept[0].get("promise", ""),
                 "titles": kept, "rejected": rejected, "thumbnail_concepts": concepts,
                 "library_date": lib.get("created", "")}
    write_json(ctx.path("packaging.json"), packaging)

    lines = [f"# Packaging: {ctx.title}", "",
             f"**Chosen title:** {packaging['chosen_title']}", f"**Promise the video must pay off:** {packaging['promise']}", "",
             "To use a different title, change `chosen_title` and `promise` in packaging.json before approving the script.", "",
             "## Title ranking"]
    for i, c in enumerate(kept, start=1):
        j = c.get("judge", {})
        lines.append(f"{i}. **{c['title']}** · rank {c['rank_score']} · judge {j.get('overall', '?')} "
                     f"(curiosity {j.get('curiosity', '?')}, truth {j.get('truth', '?')}) · formula `{c.get('formula_id', '')}`")
        lines.append(f"   - Gap: {c.get('curiosity_gap', '')}  ·  Paid off by: {c.get('payoff', '')}")
    if rejected:
        lines += ["", "## Rejected by the title checker"] + [f"- {c['title']}: {'; '.join(c['check']['hard'])}" for c in rejected]
    lines += ["", "## Thumbnail concepts"]
    for c in concepts:
        panels = " | ".join(f"{p.get('query')}" + (f" [{p.get('label')}]" if p.get("label") else "") for p in c.get("panels", []))
        lines.append(f"- `{c['layout']}` \"{c.get('text', '')}\" for \"{c['title']}\": {panels}. {c.get('why', '')}")
    if not lib:
        lines += ["", "_No packaging library yet: run `de trends` so titles are built on real outlier data._"]
    write_text(ctx.path("packaging.md"), "\n".join(lines) + "\n")
    ctx.log.info("concept: chose \"%s\" from %d candidates (%d rejected)", packaging["chosen_title"], len(candidates), len(rejected))
