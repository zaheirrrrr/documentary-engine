"""Title checker: hard rules a title must pass before Claude judges it.

Scored like the script checker: 100, minus 15 per hard fail and 5 per soft
flag. A title is only kept if it has no hard fails.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

ACRONYMS = {"USA", "US", "NASA", "IBM", "GM", "RCA", "AT&T", "WWI", "WWII", "TV", "NYC", "FBI", "CIA", "UK", "AI", "CEO",
            "TWA", "DC", "LA", "NY", "AOL", "MGM", "GE", "AMC", "TVA", "KFC", "RV", "II", "III"}
CURIOSITY = re.compile(
    r"(?i)\b(why|how|what|who|vs\.?|versus|last|only|nobody|forgotten|lost|vanished|disappeared|abandoned|killed|"
    r"fell|fall|collapse[d]?|died|death|ruined|biggest|largest|tallest|first|richest|secret|strange|mystery|"
    r"almost|never|banned|failed|failure|doomed|deadliest|worst|greatest|insane|impossible|hidden|ghost|"
    r"rise|empire|billion|million)\b"
)
CLICKBAIT = re.compile(r"(?i)you won'?t believe|shocking|gone wrong|must see|mind[- ]?blowing|jaw[- ]?dropping|\(emotional\)|omg")
FLAT_OPENERS = re.compile(r"(?i)^(the story of|a documentary|a history of|an introduction to|everything you need)")
EMOJI = re.compile("[\U0001F300-\U0001FAFF☀-➿]")


@dataclass
class TitleCheck:
    title: str
    score: int
    hard: list[str] = field(default_factory=list)
    soft: list[str] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return not self.hard


def check_title(title: str) -> TitleCheck:
    t = title.strip()
    hard: list[str] = []
    soft: list[str] = []
    n = len(t)
    if n > 70:
        hard.append(f"{n} characters: YouTube cuts it off (keep under 60)")
    elif n > 60:
        soft.append(f"{n} characters: may be cut off on mobile (aim 40-60)")
    elif n < 20:
        soft.append(f"only {n} characters: too vague to search or click")
    caps = [w for w in re.findall(r"[A-Za-z&]{3,}", t) if w.isupper() and w not in ACRONYMS]
    if caps:
        hard.append(f"ALL CAPS words {caps}: reads as clickbait on a documentary channel")
    if CLICKBAIT.search(t):
        hard.append("clickbait phrase")
    if t.count("!") > 0:
        hard.append("exclamation mark")
    if EMOJI.search(t):
        hard.append("emoji")
    if t.count("?") > 1:
        soft.append("more than one question mark")
    if not re.search(r"\d|\$|\b[A-Z][a-z]+", t[1:]):
        soft.append("no number, money or name (specificity drives clicks)")
    if not CURIOSITY.search(t) and "?" not in t:
        soft.append("no curiosity trigger (contrast, superlative, why/how, loss, stakes)")
    if FLAT_OPENERS.search(t):
        soft.append("flat opener ('The Story of...'): lead with the hook instead")
    score = max(0, 100 - 15 * len(hard) - 5 * len(soft))
    return TitleCheck(t, score, hard, soft)
