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


def test_scriptcheck_flags_ai_patterns():
    from engine.scriptcheck import Profile, check

    bad = ("Imagine this. It's not a dam, it's a monument. We need to delve into it; really.\n\n"
           "Same town. Same people. Same ending.\n\nWild. Simple.")
    r = check(bad, Profile(1, 500))
    reasons = " ".join(r.hard)
    for expected in ("stage direction", "it's Y", "banned word", "semicolon", "one-word", "parallel repetition"):
        assert expected in reasons, expected
    assert not r.passed

    good = ("In 1931, five thousand men started building the largest dam on Earth.\n\n"
            "The river had to be moved first, so they drilled four tunnels through the canyon walls.\n\n"
            "Three years later the concrete was rising, and the town of Boulder City had grown around it.\n\n"
            "Tell me in the comments if you would have taken the job.")
    assert check(good, Profile(1, 500)).passed


def test_karaoke_states():
    from engine.karaoke import caption_states

    states = caption_states([("Hello,", 0.5, 0.8), ("world.", 0.9, 1.3)], 2.0)
    assert states[0] == (0.0, 0.5, "")
    assert states[1][2] == "HELLO" and states[2][2] == "WORLD"
    assert abs(states[-1][1] - 2.0) < 1e-9
