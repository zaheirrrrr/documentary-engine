"""Wikipedia article text and page-view demand signal (both free, no key)."""

from __future__ import annotations

import math
from datetime import date
from urllib.parse import quote

import requests

from ..util import PermanentError, http_get_json

API = "https://en.wikipedia.org/w/api.php"
PAGEVIEWS = "https://wikimedia.org/api/rest_v1/metrics/pageviews/per-article/en.wikipedia/all-access/user/{title}/monthly/{start}/{end}"


def search_title(session: requests.Session, query: str) -> str:
    data = http_get_json(session, API, {"action": "query", "list": "search", "srsearch": query, "format": "json", "srlimit": 1})
    hits = data.get("query", {}).get("search", [])
    return hits[0]["title"] if hits else ""


def article(session: requests.Session, title: str) -> dict:
    """Return {"title", "url", "text"} for an article (follows redirects)."""
    data = http_get_json(
        session,
        API,
        {"action": "query", "prop": "extracts", "explaintext": 1, "redirects": 1, "titles": title, "format": "json"},
    )
    pages = data.get("query", {}).get("pages", {})
    for page in pages.values():
        if "missing" in page:
            continue
        real = page.get("title", title)
        return {
            "title": real,
            "url": f"https://en.wikipedia.org/wiki/{quote(real.replace(' ', '_'))}",
            "text": page.get("extract", ""),
        }
    return {"title": title, "url": "", "text": ""}


def monthly_views(session: requests.Session, title: str, months: int = 12) -> int:
    """Total human page views over roughly the last `months` full months."""
    if not title:
        return 0
    today = date.today()
    end = date(today.year, today.month, 1)
    start_month = end.month - months
    start_year = end.year + (start_month - 1) // 12
    start_month = (start_month - 1) % 12 + 1
    start = date(start_year, start_month, 1)
    url = PAGEVIEWS.format(
        title=quote(title.replace(" ", "_"), safe=""),
        start=start.strftime("%Y%m%d00"),
        end=end.strftime("%Y%m%d00"),
    )
    try:
        data = http_get_json(session, url)
    except PermanentError:
        return 0
    return int(sum(item.get("views", 0) for item in data.get("items", [])))


def familiarity_score(yearly_views: int) -> float:
    """Map yearly views to 1..10 on a log scale (10k -> ~3, 100k -> ~5.5, 1M -> ~8)."""
    if yearly_views <= 0:
        return 1.0
    return max(1.0, min(10.0, (math.log10(yearly_views) - 2.8) * 2.5))
