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


def test_voicestudio_chunks_stay_under_limit():
    from engine.stages.narration import _chunks

    para = " ".join(["The dam rose another foot of concrete that week."] * 40)
    text = "\n\n".join([para, "Short closing line."])
    chunks = _chunks(text, limit=500)
    assert all(len(c) <= 500 for c in chunks)
    assert " ".join(chunks).split() == text.split()


def test_align_words_maps_and_fills_gaps():
    from engine.stages.narration import align_words

    text = "In 1931, workers poured concrete."
    # The recogniser drops "1931," and mishears nothing else.
    heard = [{"word": "In", "start": 0.0, "end": 0.2},
             {"word": "workers", "start": 1.0, "end": 1.5},
             {"word": "poured", "start": 1.6, "end": 2.0},
             {"word": "concrete.", "start": 2.1, "end": 2.8}]
    a = align_words(text, heard, duration=3.0)
    starts, ends = a["character_start_times_seconds"], a["character_end_times_seconds"]
    assert len(starts) == len(text) == len(a["characters"])
    assert starts[text.index("workers")] == 1.0
    assert ends[len(text) - 1] == 2.8
    year = text.index("1931")
    assert 0.2 <= starts[year] < 1.0  # interpolated into the gap
    assert starts == sorted(starts)


def test_align_words_without_timestamps_spreads_evenly():
    from engine.stages.narration import align_words

    a = align_words("one two three four", [], duration=4.0)
    assert a["character_start_times_seconds"][0] == 0.0
    assert abs(a["character_end_times_seconds"][-1] - 4.0) < 1e-9


def test_voicestudio_tts_requests_speech_then_word_timestamps(monkeypatch):
    import base64
    from types import SimpleNamespace

    from engine.stages import narration

    calls = []

    def fake_post(url, **kw):
        calls.append((url, kw))
        if url.endswith("/v1/audio/speech"):
            return SimpleNamespace(content=b"RIFFfakewav")
        return SimpleNamespace(json=lambda: {"words": [{"word": "Hello", "start": 0.0, "end": 0.4},
                                                       {"word": "dam.", "start": 0.5, "end": 0.9}]})

    monkeypatch.setattr(narration, "_voicestudio_post", fake_post)
    monkeypatch.setattr(narration, "ffprobe_duration", lambda p: 1.0)
    settings = SimpleNamespace(voicestudio_url="http://127.0.0.1:3900", voicestudio_model="omnivoice",
                               voicestudio_voice="Narrator", tts_provider="voicestudio")
    ctx = SimpleNamespace(settings=settings, pack={"voice": {"speed": 0.95}}, log=SimpleNamespace(warning=print))
    out = narration._tts(ctx, "Hello dam.", "", "")
    speech = calls[0][1]["json"]
    assert speech["voice"] == "Narrator" and speech["response_format"] == "wav" and speech["speed"] == 0.95
    assert calls[1][1]["data"]["timestamp_granularities[]"] == "word"
    assert base64.b64decode(out["audio_base64"]) == b"RIFFfakewav"
    assert out["alignment"]["character_end_times_seconds"][-1] == 0.9


def test_parse_manual_newspapers():
    from engine.stages.research import parse_manual_newspapers

    text = """# Newspaper finds
> Help text the parser ignores.

## Evening Star (Washington, DC), June 7, 1932, page 1
URL: https://www.loc.gov/resource/sn83045462/1932-06-07/ed-1/?sp=1&st=text
> paste below
INSULL QUITS ALL POSTS
Chicago, June 6.--Samuel Insull resigned today.

## Empty heading with no text
URL: https://example.org
"""
    finds = parse_manual_newspapers(text)
    assert len(finds) == 1
    f = finds[0]
    assert f["title"].startswith("Evening Star") and f["url"].startswith("https://www.loc.gov/")
    assert "Samuel Insull resigned today." in f["text"] and "paste below" not in f["text"]


def test_factcheck_instruction_fix_deletes_sentence():
    from engine.stages.factcheck import INSTRUCTION

    assert INSTRUCTION.match("Remove the sentence. The next paragraph already covers it.")
    assert INSTRUCTION.match("Delete this claim.")
    assert not INSTRUCTION.match("He cut the price of power by a third.")


def test_quote_verified_tolerates_ocr_line_breaks():
    from engine.stages.research import quote_verified

    ocr = "While Sam\nuel Insull, broken former head of the\nworld's largest public utility combina\ntion, was under technical arrest"
    assert quote_verified("Samuel Insull, broken former head of the world's largest public utility combination", ocr)
    assert not quote_verified("Samuel Insull, the richest man in the whole world", ocr)


def test_destockd_candidates_skip_short_and_used_shots(monkeypatch, tmp_path):
    import logging
    from types import SimpleNamespace

    from engine.sources.archive_org import Film
    from engine.stages import footage

    results = [{"film": "A", "shot": "shot_001", "clip": "short.mp4"},
               {"film": "B", "shot": "shot_002", "clip": "used.mp4"},
               {"film": "C", "shot": "shot_003", "clip": "good.mp4"}]
    lengths = {"short.mp4": 3.0, "used.mp4": 20.0, "good.mp4": 12.0}

    class FakeDs:
        def search(self, q):
            return results

        def film(self, r, duration):
            return Film(identifier=f"id-{r['film']}", title=r["film"], year="", collection="FedFlix",
                        licence="PD", page_url="https://archive.org/details/x", video_url=r["clip"],
                        duration=duration, extra={"destockd": True, "shot": r["shot"]})

    monkeypatch.setattr(footage, "probe_duration", lambda src: lengths[src])
    monkeypatch.setattr(footage, "grab_frame", lambda src, t, dest: dest.write_bytes(b"x") or True)
    monkeypatch.setattr(footage, "contact_sheet", lambda frames, dest: dest)
    monkeypatch.setattr(footage, "exposure_problem", lambda frames, cfg: "")
    ctx = SimpleNamespace(log=logging.getLogger("t"), pack=SimpleNamespace(get=lambda key, default=None: default))
    used = {"destockd:B/shot_002": 1}
    cands = footage.find_destockd_candidates(ctx, FakeDs(), "q", 6.0, 1, used, 4, tmp_path)
    assert [c.film.title for c in cands] == ["C"]
    assert cands[0].start + 6.0 <= 12.0
    assert cands[0].film.extra["shot_key"] == "destockd:C/shot_003"
    # a shot rejected for this beat is never offered again
    assert footage.find_destockd_candidates(ctx, FakeDs(), "q", 6.0, 1, used, 4, tmp_path,
                                            frozenset({"destockd:C/shot_003"})) == []


def test_spoken_money_moves_unit_after_number():
    from engine.stages.narration import spoken
    assert spoken("a fortune of $100 million, about $2.4 billion today.") == \
        "a fortune of 100 million dollars, about 2.4 billion dollars today."
    assert spoken("$147,738,900, at $200 a share") == "147,738,900 dollars, at 200 dollars a share"
    assert spoken("a $1 bill") == "a 1 dollar bill"


def test_exposure_problem_rejects_dark_blown_and_flat(tmp_path):
    from PIL import Image, ImageDraw
    from engine.stages.footage import exposure_problem

    def frame(name, fill, stripes=None):
        img = Image.new("L", (64, 64), fill)
        if stripes is not None:
            d = ImageDraw.Draw(img)
            for x in range(0, 64, 8):
                d.rectangle((x, 0, x + 3, 63), fill=stripes)
        path = tmp_path / f"{name}.png"
        img.save(path)
        return [path]

    assert exposure_problem(frame("dark", 10, 30), {}).startswith("too dark")
    assert exposure_problem(frame("blown", 250, 235), {}).startswith("blown out")
    assert exposure_problem(frame("flat", 120), {}).startswith("flat")
    assert exposure_problem(frame("good", 60, 200), {}) == ""


def test_footage_summary_names_collections():
    from engine.stages.package import footage_summary

    line = footage_summary([
        "A, prelinger via Internet Archive: https://archive.org/details/a [pd]",
        "B, FedFlix via Internet Archive: https://archive.org/details/b [pd]",
        "C, FedFlix via Internet Archive: https://archive.org/details/c [pd]",
    ])
    assert line.startswith("3 archival films from Prelinger and FedFlix via Internet Archive")
