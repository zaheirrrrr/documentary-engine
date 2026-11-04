import json
from pathlib import Path

from PIL import Image

from engine import thumbs, trends
from engine.config import Pack, Settings
from engine.sources import wikipedia, youtube
from engine.state import State
from engine.titles import check_title


def test_outlier_scoring():
    vids = [youtube.Video(str(i), "C", f"t{i}", v, 600) for i, v in enumerate([100, 120, 90, 110, 1500, 100])]
    vids.append(youtube.Video("s", "C", "short", 9_000_000, 40))  # a Short: excluded
    scored = youtube.score_outliers(vids)
    assert all(v.duration >= 180 for v in scored)
    top = max(scored, key=lambda v: v.outlier)
    assert top.title == "t4" and top.outlier > 10
    assert youtube.iso_duration("PT1H2M3S") == 3723 and youtube.iso_duration("PT45S") == 45


def test_formula_evidence_uses_real_numbers():
    vids = [youtube.Video("a", "MrBeast", "$1 vs $1,000,000 Hotel Room!", 100, 900, outlier=14.0),
            youtube.Video("b", "X", "$1 vs $500,000 Car", 100, 900, outlier=6.0)]
    formulas = [{"id": "price", "fit": 8, "examples": ["$1 vs $1,000,000 Hotel Room!", "$1 vs $500,000 Car", "Invented Title"]},
                {"id": "made_up", "fit": 9, "examples": ["Not In Data"]}]
    out = trends.formula_evidence(formulas, vids)
    assert out[0]["id"] == "price" and out[0]["evidence_count"] == 2 and out[0]["evidence_median_outlier"] == 10.0
    assert out[1]["strength"] == 0.0  # no proof, sinks


def test_thumb_stats_weighted():
    tags = [{"layout": "versus", "text_words": 2, "devices": ["price_tag"], "_outlier": 9.0},
            {"layout": "single_subject", "text_words": 7, "devices": [], "_outlier": 1.0}]
    stats = trends.thumb_stats(tags)
    assert stats["layout"]["versus"] == 90.0 and stats["text_words"]["1-3"] == 90.0


def test_anniversary():
    from datetime import date, timedelta

    soon = date.today() + timedelta(days=30)
    score, note = wikipedia.anniversary_score(f"{soon.year - 100}-{soon:%m-%d}")
    assert score == 10.0 and "100th" in note
    assert wikipedia.anniversary_score(f"{soon.year - 37}-{soon:%m-%d}")[0] == 0.0


def test_title_checker():
    assert check_title("$1 Store vs $1,000,000 Store").ok
    assert not check_title("SHOCKING Truth About Sears!!").ok
    assert not check_title("x" * 75).ok
    assert check_title("Why the IBM Building Was Abandoned").ok  # acronyms are fine


def test_thumbnail_layouts(tmp_path):
    a, b = tmp_path / "a.jpg", tmp_path / "b.jpg"
    Image.effect_noise((640, 480), 60).convert("RGB").save(a)
    Image.linear_gradient("L").resize((640, 480)).convert("RGB").save(b)
    font = Path("packs/us-rise-and-fall/fonts/Montserrat-VariableFont_wght.ttf")
    colors = {"text": "#FFFFFF", "stroke": "#000000", "accent": "#E8B33A"}
    for layout, frames, text, labels in [("split", [a, b], "BUILT THEN BURNED", ["1898", "1969"]),
                                         ("versus", [a, b], "", ["$4", "$40,000,000"]),
                                         ("subject", [a], "THE LAST ONE", []),
                                         ("number", [b], "$49M", [])]:
        dest = tmp_path / f"{layout}.jpg"
        size = thumbs.render(layout, frames, text, dest, colors, font, labels, "today", "circle")
        img = Image.open(dest)
        assert img.size == (1280, 720)
        checks = thumbs.mobile_checks(dest, text, size)
        assert checks["words_ok"]
        if text:
            assert checks["readable_small"], (layout, checks)


class FakeYT:
    def channel_videos(self, handle, limit=60):
        base = [youtube.Video(f"{handle}{i}", handle, f"{handle} normal {i}", 1000, 900) for i in range(10)]
        base.append(youtube.Video(f"{handle}X", handle, f"$1 vs $1,000,000 {handle}", 20000, 900, published="2026-10-01"))
        return base


class FakeLLM:
    def __init__(self, *a, **k):
        pass

    def complete_json(self, prompt, **kw):
        if "packaging analyst" in prompt:
            return {"formulas": [{"id": "price_vs", "template": "$[small] vs $[huge] [thing]", "fit": 8,
                                  "examples": ["$1 vs $1,000,000 @MrBeast"], "adaptations": ["$4 Store vs $40M Store"]}],
                    "principles": ["Numbers"], "avoid": ["Fake stakes"]}
        if "thumbnail analyst" in prompt:
            return {"thumbnails": [{"n": 1, "layout": "versus", "text_words": 2, "devices": ["price_tag"]}]}
        if "designing the thumbnail system" in prompt:
            return {"patterns": [{"id": "rise_fall", "layout": "split", "name": "Then and now"}], "rules": ["One focal point"]}
        if "what is working right now" in prompt:
            return {"themes": [{"theme": "Vanished brands", "evidence": ["x"], "topic_ideas": ["Montgomery Ward"]}]}
        raise AssertionError(prompt[:80])


def test_trends_run(tmp_path, monkeypatch):
    monkeypatch.setattr(youtube, "client", lambda session, key: FakeYT())
    monkeypatch.setattr(trends, "LLM", FakeLLM)

    def fake_download(session, url, dest, timeout=30):
        dest.parent.mkdir(parents=True, exist_ok=True)
        Image.new("RGB", (320, 180), "red").save(dest)
        return dest

    monkeypatch.setattr(trends, "http_download", fake_download)
    settings = Settings(workspace=tmp_path, pack_name="us-rise-and-fall", llm_provider="api", anthropic_api_key="x",
                        model_deep="m", model_fast="m", web_search=False, vision_footage_check=True,
                        elevenlabs_api_key="", elevenlabs_voice_id="", elevenlabs_model="m", user_agent="t")
    pack = Pack.load("us-rise-and-fall")
    path = trends.run(settings, State(settings.db_path), pack, echo=lambda *_: None)
    lib = json.loads((tmp_path / "research" / "library.json").read_text())
    assert lib["title_formulas"][0]["evidence_count"] == 1
    assert lib["title_formulas"][0]["evidence_median_outlier"] > 10
    assert lib["thumbnail_patterns"][0]["layout"] == "split"
    assert lib["topic_themes"][0]["theme"] == "Vanished brands"
    assert "Then and now" in path.read_text()
    assert list((tmp_path / "research").glob("*/grid01.jpg"))
