from engine.scriptdoc import build_beats, narration_text, parse_blocks
from engine.sources.archive_org import licence_ok
from engine.stages.research import quote_verified
from engine.util import extract_json, normalise_for_match

SCRIPT = """When the dam opened in 1936, it was the largest in the world. Nobody had built anything like it. But the cost was high.

## The Plan
Engineers drew up plans in 1928. Money came from Washington. Work began fast.

The newspapers were thrilled. One wrote this:

> The greatest engineering work of the age is now under way in the desert.
— Las Vegas Age, 1931

## Closing
It still stands today. What do you think?
"""


def test_blocks_and_quotes():
    blocks = parse_blocks(SCRIPT)
    kinds = [b.kind for b in blocks]
    assert kinds.count("quote") == 1
    quote = next(b for b in blocks if b.kind == "quote")
    assert quote.attribution == "Las Vegas Age, 1931"
    assert quote.chapter_title == "The Plan"


def test_beats_cover_all_words_in_order():
    beats = build_beats(SCRIPT, max_words=10)
    joined = normalise_for_match(" ".join(b.text for b in beats))
    assert joined == normalise_for_match(narration_text(SCRIPT))
    assert beats[0].chapter == 0 and beats[0].first_in_chapter
    assert any(b.kind == "quote" for b in beats)
    assert all(len(b.text.split()) <= 24 for b in beats if b.kind == "narration")


def test_licences():
    assert licence_ok("http://creativecommons.org/licenses/publicdomain/", False)[0]
    assert licence_ok("https://creativecommons.org/publicdomain/zero/1.0/", False)[0]
    assert licence_ok("https://creativecommons.org/licenses/by-sa/4.0/", False)[0]
    assert not licence_ok("https://creativecommons.org/licenses/by-nc/3.0/", True)[0]
    assert not licence_ok("https://creativecommons.org/licenses/by-nd/4.0/", True)[0]
    assert licence_ok("", True)[0]
    assert not licence_ok("", False)[0]


def test_quote_verification():
    source = "Yesterday the Mayor said: “The greatest engineering work of the age is now under way in the desert,” to cheers."
    assert quote_verified("The greatest engineering work of the age is now under way in the desert.", source)
    assert quote_verified("The greatest engineering work ... now under way in the desert", source)
    assert not quote_verified("The finest engineering work of all time is happening", source)


def test_extract_json_variants():
    assert extract_json('<json>{"a": 1}</json>') == {"a": 1}
    assert extract_json('Here:\n```json\n{"a": [1,2]}\n```') == {"a": [1, 2]}
    assert extract_json('prose {"b": 2} more') == {"b": 2}
