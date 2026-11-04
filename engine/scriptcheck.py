"""Script checker: scores narration out of 100 and lists every failed check.

Adapted from the viral-video-writing skill's score.py (hard fails cost 15,
soft flags cost 5; a script passes at 90+ with zero hard fails), extended for
long-form documentaries and for this project's own banned patterns.

Only the narrator's own words are checked. Quote blocks are verbatim
historical text and are excluded (an 1897 newspaper may use semicolons).
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from .scriptdoc import parse_blocks

HARD = [
    (r"—", "em dash (nobody speaks one; use a period or 'and')"),
    (r";", "semicolon"),
    (r"(?i)\bnot just\b[^.]*\bbut\b", '"not just X but Y"'),
    (r"(?i)\b(?:it|this|that)(?:'s| is| was) not (?:about )?[^.,]+, (?:it|this|that)(?:'s| is| was)\b", '"it\'s not X, it\'s Y"'),
    (r"(?i)\bisn'?t (?:just )?(?:about )?[^.,]+\. (?:it|this)(?:'s| is)\b", '"It isn\'t X. It\'s Y."'),
    (r"(?i)here'?s the thing|let that sink in|read the (?:tiny|fine) print|the truth is|in today'?s|buckle up|imagine (?:this|if|waking)|it'?s worth noting|at the end of the day|whether you'?re a|let'?s dive in|more on that later|but wait,? there'?s more",
     "stage direction / filler"),
    (r"(?i)\b(spoiler|plot twist)\s*:|here'?s where it gets interesting|the best part\?|and this is where it gets crazy", "fake suspense"),
    (r"(?i)\b(delve|unlock|unleash|harness|leverage|seamless|robust|cutting[- ]edge|game[- ]?changer|revolutionary|transformative|landscape|realm|tapestry|elevate|empower|supercharge|deep dive|next level|dive in)\b",
     "banned word"),
    (r"(?i)\b(?:panic button|goldmine|secret sauce)\b", "metaphor punchline"),
]
NUM = r"\d|\b(?:one|two|three|four|five|six|seven|eight|nine|ten|twelve|twenty|fifty|hundred|thousand|million|billion)\b"
REHOOK = re.compile(
    r"(?i)" + NUM + r"|\b(but|then|until|turns out|which meant|that meant|instead|years later|months later|weeks later|by \d|that was|the problem|the answer|first|second|third|finally|now|meanwhile|soon)\b"
)
CTA = re.compile(r"(?i)\b(comment|tell me|let me know|follow|subscribe|watch|full story|link|part)\b")


@dataclass
class Profile:
    min_words: int
    max_words: int
    hook_max_words: int = 25
    rehook_gap_words: int = 160      # long-form: a new number/turn at least every ~minute
    max_sentence_words: int = 32
    max_body_questions: int = 2


@dataclass
class Result:
    score: int
    words: int
    hard: list[str] = field(default_factory=list)
    soft: list[str] = field(default_factory=list)

    @property
    def passed(self) -> bool:
        return not self.hard and self.score >= 90

    def report(self) -> str:
        lines = [f"Score {self.score}/100 · {self.words} spoken words · {'PASS' if self.passed else 'REWRITE'}"]
        lines += [f"- HARD: {h}" for h in self.hard] + [f"- soft: {s}" for s in self.soft]
        return "\n".join(lines)


def spoken_text(script: str) -> str:
    """The narrator's own lines (quote blocks excluded)."""
    return "\n".join(b.text for b in parse_blocks(script) if b.kind == "para")


def sentences(text: str) -> list[str]:
    paragraphs = [re.sub(r"\s*\n\s*", " ", p) for p in re.split(r"\n\s*\n", text)]
    out: list[str] = []
    for p in paragraphs:
        out += [s.strip() for s in re.split(r"(?<=[.?!])[\"”’]?\s+(?=[\"“‘]?[A-Z0-9$])", p) if s.strip()]
    return out


def check(script: str, profile: Profile) -> Result:
    text = spoken_text(script) if "## " in script or "\n> " in script else script
    hard: list[str] = []
    soft: list[str] = []
    n = len(text.split())
    S = sentences(text)
    hook = S[0] if S else ""

    if not profile.min_words <= n <= profile.max_words:
        soft.append(f"length {n} spoken words (aim {profile.min_words}-{profile.max_words})")
    if len(hook.split()) > profile.hook_max_words:
        soft.append(f"first sentence is {len(hook.split())} words (aim {profile.hook_max_words} or fewer)")
    if not re.search(NUM, hook, re.I) and not re.search(r"\b[A-Z][a-z]+\w*\b", hook[1:]):
        soft.append("first sentence has no number and no named thing")

    for rx, why in HARD:
        m = re.search(rx, text)
        if m:
            hard.append(f'{why}: "...{text[max(0, m.start() - 30):m.end() + 30].strip()}..."')

    one_word = [s for s in S if len(s.split()) == 1]
    if len(one_word) > 1:
        hard.append(f"{len(one_word)} one-word dramatic sentences: {one_word[:3]}")

    # Parallel repetition stack: short consecutive sentences echoing the same opener.
    for a, b in zip(S, S[1:]):
        wa, wb = a.split(), b.split()
        if wa and wb and len(wa) <= 6 and len(wb) <= 6 and wa[0].lower() == wb[0].lower():
            hard.append(f'parallel repetition stack: "{a} {b}"')
            break
    for a, b, c in zip(S, S[1:], S[2:]):
        if all(len(x.split()) <= 4 for x in (a, b, c)):
            soft.append(f'three short stacked sentences: "{a} {b} {c}"')
            break

    long_ones = [s for s in S if len(s.split()) > profile.max_sentence_words]
    if long_ones:
        soft.append(f'{len(long_ones)} sentence(s) over {profile.max_sentence_words} words, e.g. "{long_ones[0][:70]}..."')

    body_q = [s for s in S[1:-2] if s.endswith("?")]
    if len(body_q) > profile.max_body_questions:
        soft.append(f"{len(body_q)} rhetorical questions in the body (only the hook and the close should ask)")

    gap = worst = 0
    worst_at = ""
    for s in S[1:-1]:
        gap = 0 if REHOOK.search(s) else gap + len(s.split())
        if gap > worst:
            worst, worst_at = gap, s
    if worst > profile.rehook_gap_words:
        soft.append(f'{worst} words with no re-hook (number, turn or time jump), ending near "{worst_at[:60]}"')

    if not CTA.search(" ".join(S[-3:])):
        soft.append("no clear ask at the end (one question or one call to action)")

    total = max(0, 100 - 15 * len(hard) - 5 * len(soft))
    return Result(total, n, hard, soft)


def profile_for(pack, fmt: str) -> Profile:
    if fmt == "short":
        s = pack.get("shorts", {}) or {}
        return Profile(int(s.get("min_words", 100)), int(s.get("max_words", 160)), hook_max_words=18,
                       rehook_gap_words=int(s.get("rehook_gap_words", 30)), max_sentence_words=24,
                       max_body_questions=1)
    v = pack.get("video", {}) or {}
    return Profile(int(v.get("min_words", 1700)), int(v.get("max_words", 2600)),
                   rehook_gap_words=int(v.get("rehook_gap_words", 160)))
