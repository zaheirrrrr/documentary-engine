"""Topic discovery and scoring.

Claude proposes topics (with web search to confirm each story is real and to
look at existing YouTube coverage). Each topic is then scored with two
objective signals the model cannot invent:

- familiarity: last-12-months Wikipedia page views of the main subject
- footage: how many public-domain films match its footage keywords

- trend: the best of (fit with themes over-performing right now, from
  `de trends`), a Wikipedia interest spike, or a round anniversary coming up

Final score (0-10) = 25% story arc + 10% novelty + 15% source depth
                   + 15% familiarity + 20% footage + 15% trend
"""

from __future__ import annotations

import math
from typing import Callable

import yaml

from .config import Pack, Settings
from .llm import LLM
from .sources import wikipedia
from .sources.archive_org import Archive
from .state import State
from .util import http_session, log

WEIGHTS = {"arc_strength": 0.25, "novelty": 0.10, "source_depth": 0.15, "familiarity": 0.15, "footage": 0.20, "trend": 0.15}


def footage_score(hits: int) -> float:
    """0 films -> 0, 10 -> ~5, 100 -> ~10."""
    if hits <= 0:
        return 0.0
    return min(10.0, 1 + 4.5 * math.log10(hits) if hits >= 1 else 0.0)


def category_split(pack: Pack, count: int, only: str | None) -> str:
    cats = pack.get("topics.categories", {}) or {}
    if only:
        return f"all {count} in category '{only}'"
    mix = pack.get("topics.mix", {}) or {}
    parts = []
    remaining = count
    keys = list(cats)
    for i, key in enumerate(keys):
        n = remaining if i == len(keys) - 1 else round(count * float(mix.get(key, 1 / len(keys))))
        remaining -= n
        parts.append(f"{n} '{key}'")
    return ", ".join(parts)


def discover(settings: Settings, state: State, pack: Pack, count: int = 10, category: str | None = None,
             focus: str = "", echo: Callable[[str], None] = print) -> list[int]:
    llm = LLM(settings, usage_hook=lambda s, u, unit, d: state.log_usage(None, s, u, unit, d))
    rules = {k: pack.get(f"topics.{k}") for k in ("promise", "categories", "era", "must_have", "avoid")}
    existing = state.all_titles()
    from .trends import load_library

    themes = load_library(settings).get("topic_themes", [])
    theme_text = "\n".join(f"- {t.get('theme')}: {t.get('why_now', '')} Evidence: " + "; ".join(t.get("evidence", [])[:3])
                           for t in themes) or "(No outlier research yet. Run `de trends` to fill this.)"
    prompt = pack.prompt(
        "discover",
        trend_themes=theme_text,
        topic_rules=yaml.safe_dump(rules, sort_keys=False, allow_unicode=True),
        existing_titles="\n".join(f"- {t}" for t in existing) or "(none yet)",
        count=str(count),
        category_split=category_split(pack, count, category),
        focus=f"Focus for this batch: {focus}" if focus else "",
    )
    echo(f"Asking Claude for {count} topics (with web search)...")
    data = llm.complete_json(prompt, tier="deep", max_tokens=12000, web_search=True)
    topics = data.get("topics", [])

    session = http_session(settings.user_agent)
    archive = Archive(session, settings.cache_dir, pack.get("footage.collections", []))
    existing_lower = {t.lower() for t in existing}
    ids: list[int] = []
    for t in topics:
        title = str(t.get("title", "")).strip()
        if not title or title.lower() in existing_lower:
            continue
        scores = {k: float(v) for k, v in (t.get("scores") or {}).items() if isinstance(v, (int, float))}

        views, spike = 0, 1.0
        try:
            views, spike = wikipedia.views_with_trend(session, t.get("wikipedia_title", ""))
        except Exception as exc:  # noqa: BLE001
            log.warning("page views failed for %s: %s", title, exc)
        anniv, anniv_note = wikipedia.anniversary_score(str(t.get("key_date", "")))
        spike_score = max(0.0, min(10.0, (spike - 1.0) * 10)) if spike > 1.2 else 0.0
        scores["trend"] = max(scores.pop("trend_fit", 0.0) if t.get("trend_theme") else 0.0, spike_score, anniv)
        scores["familiarity_llm"] = scores.pop("familiarity", 5.0)
        scores["familiarity"] = wikipedia.familiarity_score(views) if views else scores["familiarity_llm"]

        hits = 0
        for kw in t.get("footage_keywords", [])[:4]:
            try:
                hits += archive.count(f'"{kw}"')
            except Exception as exc:  # noqa: BLE001
                log.warning("footage count failed for %s: %s", kw, exc)
        scores["footage"] = footage_score(hits)

        final = round(sum(scores.get(k, 5.0) * w for k, w in WEIGHTS.items()), 2)
        details = dict(t, yearly_views=views, interest_spike=spike, anniversary=anniv_note, footage_hits=hits, scores=scores)
        ids.append(state.add_topic(title, t.get("angle", ""), t.get("category", ""), final, details))
        extra = f", {anniv_note}" if anniv_note else (f", interest x{spike}" if spike > 1.2 else "")
        echo(f"  [{final:4.1f}] {title}  (views/yr {views:,}, films {hits}{extra})")
    return ids
