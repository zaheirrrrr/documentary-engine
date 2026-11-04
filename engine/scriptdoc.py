"""Parse script.md into chapters and beats.

script.md format (written by the script stage, editable by you):

    Cold open paragraphs...

    ## Chapter title
    Paragraphs...

    > Exact quote text
    — Publication, date

A beat is a short run of narration (about 6 to 10 seconds) that gets one
visual. Quotes become quote-card beats. Beats never cross paragraph or chapter
boundaries, and together they contain every word of the narration in order.
"""

from __future__ import annotations

import re
from dataclasses import asdict, dataclass

SENTENCE_SPLIT = re.compile(r"(?<=[.!?…])[\"”’)]?\s+(?=[\"“‘(]?[A-Z0-9$])")


@dataclass
class Block:
    kind: str          # "para" | "quote"
    text: str
    chapter: int
    chapter_title: str
    attribution: str = ""


@dataclass
class Beat:
    id: int
    kind: str          # "narration" | "quote"
    text: str
    chapter: int
    chapter_title: str
    first_in_chapter: bool
    paragraph: int
    attribution: str = ""

    def to_dict(self) -> dict:
        return asdict(self)


def parse_blocks(script: str) -> list[Block]:
    blocks: list[Block] = []
    chapter, title = 0, ""
    para_lines: list[str] = []
    quote_lines: list[str] = []

    def flush_para() -> None:
        if para_lines:
            text = " ".join(l.strip() for l in para_lines).strip()
            if text:
                blocks.append(Block("para", text, chapter, title))
            para_lines.clear()

    def flush_quote(attribution: str = "") -> None:
        if quote_lines:
            text = " ".join(l.strip() for l in quote_lines).strip()
            blocks.append(Block("quote", text, chapter, title, attribution.strip()))
            quote_lines.clear()

    for raw in script.splitlines():
        line = raw.rstrip()
        stripped = line.strip()
        if stripped.startswith("## "):
            flush_para()
            flush_quote()
            chapter += 1
            title = stripped[3:].strip()
            continue
        if stripped.startswith("# "):
            continue  # a document title, not narration
        if stripped.startswith(">"):
            flush_para()
            quote_lines.append(stripped.lstrip(">").strip())
            continue
        if quote_lines and re.match(r"^[—–-]{1,2}\s*\S", stripped):
            flush_quote(re.sub(r"^[—–-]{1,2}\s*", "", stripped))
            continue
        if not stripped:
            flush_para()
            if quote_lines:
                flush_quote()
            continue
        if quote_lines:
            flush_quote()
        para_lines.append(stripped)
    flush_para()
    flush_quote()
    return blocks


def split_sentences(text: str) -> list[str]:
    parts = [p.strip() for p in SENTENCE_SPLIT.split(text) if p.strip()]
    return parts or [text.strip()]


def build_beats(script: str, max_words: int = 24, quote_page_words: int = 55) -> list[Beat]:
    beats: list[Beat] = []
    seen_chapters: set[int] = set()
    for p_index, block in enumerate(parse_blocks(script)):
        first = block.chapter not in seen_chapters
        seen_chapters.add(block.chapter)

        if block.kind == "quote":
            words = block.text.split()
            pages = [words[i : i + quote_page_words] for i in range(0, len(words), quote_page_words)] or [[]]
            for page in pages:
                beats.append(Beat(len(beats) + 1, "quote", " ".join(page), block.chapter, block.chapter_title,
                                  first, p_index, block.attribution))
                first = False
            continue

        group: list[str] = []
        count = 0
        for sentence in split_sentences(block.text):
            n = len(sentence.split())
            if group and count + n > max_words:
                beats.append(Beat(len(beats) + 1, "narration", " ".join(group), block.chapter,
                                  block.chapter_title, first, p_index))
                first = False
                group, count = [], 0
            group.append(sentence)
            count += n
        if group:
            beats.append(Beat(len(beats) + 1, "narration", " ".join(group), block.chapter,
                              block.chapter_title, first, p_index))
    return beats


def narration_text(script: str) -> str:
    """Everything the narrator reads, in order (quote attributions excluded)."""
    return "\n\n".join(b.text for b in parse_blocks(script))


def chapter_titles(script: str) -> list[tuple[int, str]]:
    seen: dict[int, str] = {}
    for block in parse_blocks(script):
        seen.setdefault(block.chapter, block.chapter_title)
    return sorted(seen.items())
