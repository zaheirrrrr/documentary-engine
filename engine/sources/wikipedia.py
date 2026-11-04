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


def views_with_trend(session: requests.Session, title: str) -> tuple[int, float]:
    """(views over the last 12 months, spike ratio of the last 2 months vs the 10 before)."""
    if not title:
        return 0, 1.0
    today = date.today()
    end = date(today.year, today.month, 1)
    sm = end.month - 12
    start = date(end.year + (sm - 1) // 12, (sm - 1) % 12 + 1, 1)
    url = PAGEVIEWS.format(title=quote(title.replace(" ", "_"), safe=""),
                           start=start.strftime("%Y%m%d00"), end=end.strftime("%Y%m%d00"))
    try:
        items = http_get_json(session, url).get("items", [])
    except PermanentError:
        return 0, 1.0
    views = [int(i.get("views", 0)) for i in items]
    total = sum(views)
    if len(views) < 6:
        return total, 1.0
    recent, before = views[-2:], views[:-2]
    base = (sum(before) / len(before)) or 1
    return total, round((sum(recent) / len(recent)) / base, 2)


def anniversary_score(key_date: str, horizon_days: int = 180) -> tuple[float, str]:
    """Bonus for a round anniversary (25/50/75/100/125/150 years) coming up soon."""
    import re as _re

    m = _re.match(r"(\d{4})(?:-(\d{2}))?(?:-(\d{2}))?", key_date or "")
    if not m:
        return 0.0, ""
    y, mo, d = int(m.group(1)), int(m.group(2) or 7), int(m.group(3) or 1)
    today = date.today()
    for years_ahead in range(0, 2):
        try:
            nxt = date(today.year + years_ahead, mo, d)
        except ValueError:
            return 0.0, ""
        if nxt < today:
            continue
        age = nxt.year - y
        days = (nxt - today).days
        if age > 0 and age % 25 == 0 and days <= horizon_days:
            weight = 10.0 if age % 100 == 0 else 8.0 if age % 50 == 0 else 6.0
            return weight, f"{age}th anniversary on {nxt.isoformat()} ({days} days away)"
        break
    return 0.0, ""


def familiarity_score(yearly_views: int) -> float:
    """Map yearly views to 1..10 on a log scale (10k -> ~3, 100k -> ~5.5, 1M -> ~8)."""
    if yearly_views <= 0:
        return 1.0
    return max(1.0, min(10.0, (math.log10(yearly_views) - 2.8) * 2.5))
