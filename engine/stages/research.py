"""Stage: research. Gathers sources and builds the dossier.

Sources, each given an id (S1, S2, ...):
- the main Wikipedia article for the subject
- period newspaper excerpts from Chronicling America
- anything Claude finds with web search during the call (cited by URL)

Every quote the model returns is checked against the fetched source text. A
quote that cannot be found word for word is kept but flagged "(verify)" in
the dossier, so it never slips into a video unnoticed.
"""

from __future__ import annotations

import json
import re

from ..dossier import render
from ..sources import chronam, wikipedia
from ..util import http_session, normalise_for_match, read_json, write_json


def _topic(ctx) -> dict:
    path = ctx.dir / "topic.json"
    return read_json(path) if path.exists() else {"title": ctx.title, "angle": ctx.angle}


def _era(ctx, topic: dict) -> tuple[int, int]:
    era = str(topic.get("era", ""))
    years = [int(y) for y in re.findall(r"\b(1[6-9]\d\d|20\d\d)\b", era)]
    if len(years) >= 2:
        return max(years[0] - 5, 1690), years[-1] + 5
    return int(ctx.pack.get("topics.era.start", 1850)), int(ctx.pack.get("topics.era.end", 1985))


def quote_verified(quote: str, source_text: str) -> bool:
    """True when every chunk of the quote (split at ellipses) appears in the source."""
    haystack = normalise_for_match(source_text)
    chunks = [normalise_for_match(c) for c in re.split(r"\.\.\.|…", quote)]
    chunks = [c for c in chunks if len(c.split()) >= 4]
    return bool(chunks) and all(c in haystack for c in chunks)


def gather_sources(ctx, topic: dict) -> list[dict]:
    session = http_session(ctx.settings.user_agent)
    sources: list[dict] = []

    if ctx.pack.get("research.wikipedia", True):
        wiki_title = topic.get("wikipedia_title") or wikipedia.search_title(session, ctx.title)
        if wiki_title:
            art = wikipedia.article(session, wiki_title)
            if art["text"]:
                sources.append({"kind": "wikipedia", "title": art["title"], "url": art["url"], "text": art["text"][:30000]})
                topic["wikipedia_title"] = art["title"]

    if ctx.pack.get("research.chronicling_america", True):
        start, end = _era(ctx, topic)
        subject = re.sub(r"\s*\(.*?\)", "", topic.get("wikipedia_title") or ctx.title)
        terms = [t for t in re.findall(r"[A-Za-z][A-Za-z'’-]{3,}", subject)][:3]
        pages = chronam.search(session, subject, start, end, terms or [subject],
                               int(ctx.pack.get("research.max_newspaper_pages", 12)))
        for p in pages:
            sources.append({"kind": "newspaper", "title": f"{p['publication']}, {p['date']}", "url": p["url"], "text": p["text"]})

    for i, s in enumerate(sources, start=1):
        s["id"] = f"S{i}"
    return sources


def run(ctx) -> None:
    topic = _topic(ctx)
    sources = gather_sources(ctx, topic)
    write_json(ctx.path("sources.json"), sources)
    ctx.log.info("research: %d sources gathered", len(sources))

    if sources:
        listing = "\n\n".join(
            f"<source id=\"{s['id']}\" kind=\"{s['kind']}\" title=\"{s['title']}\" url=\"{s['url']}\">\n{s['text']}\n</source>"
            for s in sources
        )
    else:
        listing = "(No sources could be fetched automatically. Use web search for everything and cite URLs.)"

    prompt = ctx.pack.prompt("research", title=ctx.title, angle=ctx.angle, sources=listing)
    dossier = ctx.llm.complete_json(prompt, tier="deep", max_tokens=16000,
                                    web_search=bool(ctx.pack.get("research.web_search", True)))

    by_id = {s["id"]: s for s in sources}
    for q in dossier.get("quotes", []) or []:
        src = by_id.get(str(q.get("source", "")).strip())
        q["verified"] = bool(src and quote_verified(q.get("text", ""), src["text"]))
        if src and not q.get("url"):
            q["url"] = src["url"]
    for item in dossier.get("discoveries", []) or []:
        src = by_id.get(str(item.get("source", "")).strip())
        if src:
            item["source"] = f"{item['source']} {src['url']}"

    shelf = dossier.setdefault("source_shelf", [])
    known = {s.get("url") for s in shelf}
    for s in sources:
        if s["url"] and s["url"] not in known:
            shelf.append({"title": s["title"], "url": s["url"], "note": s["kind"]})

    dossier["topic"] = topic
    write_json(ctx.path("dossier.json"), dossier)
    write_json(ctx.path("topic.json"), topic)
    render(ctx.dir, ctx.title, ctx.angle)

    verified = sum(1 for q in dossier.get("quotes", []) if q.get("verified"))
    ctx.log.info("research: %d quotes (%d verified), %d discoveries",
                 len(dossier.get("quotes", [])), verified, len(dossier.get("discoveries", [])))
    if not dossier.get("discoveries"):
        raise RuntimeError("Research returned no discoveries; the dossier is empty")


def dossier_for_prompt(ctx, drop: tuple[str, ...] = ("source_shelf", "topic")) -> str:
    data = read_json(ctx.dir / "dossier.json")
    slim = {k: v for k, v in data.items() if k not in drop}
    return json.dumps(slim, indent=1, ensure_ascii=False)
