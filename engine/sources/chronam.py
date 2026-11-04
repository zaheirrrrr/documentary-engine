"""Chronicling America (Library of Congress) historic US newspapers.

Pre-1964 American newspaper pages with OCR text, free, via the loc.gov JSON
API. Used to find period quotes. Only short windows of text around the search
terms are kept, because full OCR pages are long and noisy.
"""

from __future__ import annotations

import re
from typing import Any

import requests

from ..util import PermanentError, http_get_json, log

SEARCH = "https://www.loc.gov/collections/chronicling-america/"


def _ocr_text(session: requests.Session, result: dict[str, Any]) -> str:
    desc = result.get("description")
    if isinstance(desc, list):
        desc = " ".join(str(d) for d in desc)
    text = str(desc or "")
    if len(text) > 400:
        return text
    # Fall back to the page record, which links a full-text file.
    url = result.get("id") or result.get("url")
    if not url:
        return text
    try:
        record = http_get_json(session, url, {"fo": "json"})
    except Exception as exc:  # noqa: BLE001
        log.info("chronam: no record for %s (%s)", url, exc)
        return text
    for resource in record.get("resources", []) or []:
        for key in ("fulltext_file", "fulltext"):
            link = resource.get(key)
            if isinstance(link, str) and link.startswith("http"):
                try:
                    r = session.get(link, timeout=30)
                    if r.ok:
                        return r.text
                except requests.RequestException:
                    pass
    return text


def _windows(text: str, terms: list[str], radius: int = 900, limit: int = 3) -> list[str]:
    text = re.sub(r"\s+", " ", text)
    lowered = text.lower()
    spans: list[tuple[int, int]] = []
    for term in terms:
        for m in re.finditer(re.escape(term.lower()), lowered):
            start, end = max(0, m.start() - radius), min(len(text), m.end() + radius)
            if spans and start <= spans[-1][1]:
                spans[-1] = (spans[-1][0], max(spans[-1][1], end))
            else:
                spans.append((start, end))
            if len(spans) >= limit:
                break
    return [text[s:e] for s, e in sorted(spans)[:limit]]


def search(session: requests.Session, query: str, start_year: int, end_year: int,
           terms: list[str], max_pages: int = 10) -> list[dict[str, Any]]:
    """Return newspaper excerpts: {"publication", "date", "url", "text"}."""
    end_year = min(end_year, 1963)
    if start_year > end_year:
        return []
    params = {"q": query, "dates": f"{start_year}/{end_year}", "fo": "json", "c": max_pages}
    try:
        data = http_get_json(session, SEARCH, params)
    except PermanentError as exc:
        log.warning("chronam search failed: %s", exc)
        return []
    out = []
    for result in data.get("results", [])[:max_pages]:
        text = _ocr_text(session, result)
        excerpts = _windows(text, terms or query.split())
        if not excerpts:
            continue
        publication = result.get("partof_title") or result.get("title") or "Unknown newspaper"
        if isinstance(publication, list):
            publication = publication[0]
        out.append(
            {
                "publication": str(publication),
                "date": str(result.get("date", "")),
                "url": result.get("url") or result.get("id", ""),
                "text": "\n...\n".join(excerpts),
            }
        )
    return out
