"""Full pipeline run with simulated Claude, ElevenLabs and archive.org.

Real FFmpeg renders a real video, so this proves the production path:
beats -> narration timing -> footage cutting -> render -> package -> QA.
"""

import base64
import json
import re
import subprocess
from pathlib import Path

import pytest

from engine import pipeline
from engine.config import Settings
from engine.sources.archive_org import Film
from engine.state import State

QUOTE = "The greatest engineering work of the age is now under way in the desert"

SCRIPT = f"""In 1936 the largest dam on Earth was finished in the Nevada desert. It had taken five years and thousands of men. But the price of building it was far higher than anyone admitted.

## A River Problem
The Colorado River flooded farms every spring. Engineers wanted to tame it. The government agreed to pay.

## The Build
Work began in 1931. Men poured concrete day and night. The town of Boulder City grew around them.

A local paper captured the mood:

> {QUOTE}.
— Las Vegas Age, 1931

## Closing
The dam still stands today, ninety years later. Was it worth the cost? Tell me what you think.
"""


SHORT_SCRIPT = """ON-SCREEN: 5 years, 96 men, one dam

In 1931, five thousand men started building the biggest dam on Earth in the Nevada desert.

The summer heat hit 120 degrees, and the river had to be moved through four tunnels first.

By 1936 the dam was done, two years early, and it still holds back Lake Mead today.

The full story is on the channel.
"""


class FakeLLM:
    def __init__(self, settings, usage_hook=None):
        self.calls = []

    def complete(self, prompt, **kw):
        self.calls.append(prompt[:60])
        if "scriptwriter" in prompt:
            return SCRIPT
        if "You write YouTube Shorts" in prompt:
            return SHORT_SCRIPT
        return json.dumps(self.complete_json(prompt, **kw))

    def complete_json(self, prompt, **kw):
        if "lead researcher" in prompt:
            return {
                "summary": "The Hoover Dam rose in the desert in the 1930s.",
                "arc": {"rise": "Built 1931-36", "fall": "Human cost"},
                "discoveries": [{"theme": "build", "fact": "Finished in 1936", "source": "S1", "verified": True}],
                "key_numbers": [{"what": "Cost", "value": "$49 million", "modern_equivalent": "$1 billion", "source": "S1"}],
                "cast": [{"name": "Frank Crowe", "role": "Superintendent", "years": "1882-1946", "detail": "Hard driver", "why": "Ran the job"}],
                "timeline": [{"date": "1931", "event": "Work begins", "source": "S1"}],
                "quotes": [{"text": QUOTE, "speaker": "", "publication": "Las Vegas Age", "date": "1931", "source": "S2"}],
                "source_shelf": [], "visual_plan": ["dam construction"], "open_questions": [], "must_include": [],
            }
        if "story editor" in prompt:
            return {"hooks": [{"text": "Hook A", "score": 6}, {"text": "Hook B", "score": 9}], "chosen_hook": 0,
                    "chapters": [{"title": "A River Problem"}], "closing": {}}
        if "fact-checker" in prompt:
            return {"supported_count": 12, "problems": [], "verdict": "pass"}
        if "archive producer" in prompt:
            beats = json.loads(re.search(r"<beats>\s*(.*?)\s*</beats>", prompt, re.S).group(1))
            out = []
            for b in beats:
                if b["kind"] != "narration":
                    continue
                if b["id"] == 3:
                    out.append({"id": b["id"], "visual": "number", "big_text": "$49 million", "small_text": "about $1 billion today"})
                else:
                    out.append({"id": b["id"], "visual": "archival", "query": "dam construction", "alt_query": "river",
                                "look_for": "workers", "avoid": "text"})
            return {"beats": out}
        if "candidate archive shots" in prompt:
            return {"best": 1, "usable": [1, 2], "reason": "fits"}
        if "You package YouTube Shorts" in prompt:
            return {"titles": ["The Dam Built Two Years Early"], "description": "Five years in the desert.\nFull story: [link to the full video]\n#shorts #history",
                    "pinned_comment": "Would you have signed up?"}
        if "packaging editor" in prompt:
            return {"titles": ["The Dam That Tamed the Colorado"], "thumbnail_texts": ["5 YEARS IN HELL"],
                    "thumbnail_concepts": [], "description_hook": "How the Hoover Dam was built.",
                    "description_body": "A story of concrete and cost.", "tags": ["hoover dam", "history"],
                    "pinned_comment": "Worth it?"}
        raise AssertionError(f"unexpected prompt: {prompt[:80]}")


def fake_tts(ctx, text, prev, nxt):
    dur = max(1.0, len(text) * 0.055)
    mp3 = ctx.dir / "audio" / "tmp_tts.mp3"
    subprocess.run(["ffmpeg", "-y", "-v", "error", "-f", "lavfi", "-i", f"sine=frequency=220:duration={dur:.2f}",
                    "-ac", "1", str(mp3)], check=True)
    step = dur / max(1, len(text))
    return {
        "audio_base64": base64.b64encode(mp3.read_bytes()).decode(),
        "alignment": {
            "characters": list(text),
            "character_start_times_seconds": [i * step for i in range(len(text))],
            "character_end_times_seconds": [(i + 1) * step for i in range(len(text))],
        },
    }


@pytest.fixture()
def film(tmp_path_factory):
    path = tmp_path_factory.mktemp("films") / "film.mp4"
    subprocess.run(["ffmpeg", "-y", "-v", "error", "-f", "lavfi", "-i", "testsrc2=size=640x480:rate=24",
                    "-t", "40", "-pix_fmt", "yuv420p", str(path)], check=True)
    return path


class FakeArchive:
    def __init__(self, film_path):
        self.film_path = film_path

    def search(self, query, rows=25):
        return [{"identifier": "film-a"}, {"identifier": "film-b"}]

    def film(self, doc):
        return Film(identifier=doc["identifier"], title=f"Test {doc['identifier']}", year="1934", collection="FedFlix",
                    licence="Public domain (US federal work)", page_url=f"https://archive.org/details/{doc['identifier']}",
                    video_url=str(self.film_path), duration=40.0)

    def local_copy(self, film):
        return Path(film.video_url)


def test_full_pipeline(tmp_path, monkeypatch, film):
    from engine.stages import footage, narration, research

    monkeypatch.setattr(pipeline, "LLM", FakeLLM)
    monkeypatch.setattr(narration, "_tts", fake_tts)
    monkeypatch.setattr(footage, "make_archive", lambda ctx: FakeArchive(film))
    monkeypatch.setattr(research, "gather_sources", lambda ctx, topic: [
        {"id": "S1", "kind": "wikipedia", "title": "Hoover Dam", "url": "https://en.wikipedia.org/wiki/Hoover_Dam", "text": "Finished in 1936."},
        {"id": "S2", "kind": "newspaper", "title": "Las Vegas Age, 1931", "url": "https://loc.gov/x",
         "text": f"Editorial. {QUOTE}, said the engineer."},
    ])

    settings = Settings(workspace=tmp_path, pack_name="us-rise-and-fall", llm_provider="api", anthropic_api_key="x",
                        model_deep="m", model_fast="m", web_search=False, vision_footage_check=True,
                        elevenlabs_api_key="x", elevenlabs_voice_id="v", elevenlabs_model="m", user_agent="test")
    state = State(settings.db_path)
    pid = state.create_project("hoover-dam", "The Hoover Dam", "Its human cost", "us-rise-and-fall")

    log = []
    assert pipeline.run(settings, state, pid, echo=log.append) == "waiting"
    proj = next(settings.projects_dir.iterdir())
    assert (proj / "dossier.md").exists() and (proj / "script.md").exists()
    dossier = json.loads((proj / "dossier.json").read_text())
    assert dossier["quotes"][0]["verified"] is True
    assert "Hook B" in json.loads((proj / "outline.json").read_text())["hooks"][1]["text"]
    assert json.loads((proj / "outline.json").read_text())["chosen_hook"] == 1

    assert pipeline.approve(state, pid) == "review_script"
    assert pipeline.run(settings, state, pid, echo=log.append) == "waiting", "\n".join(log)

    final = proj / "final.mp4"
    assert final.exists()
    probe = json.loads(subprocess.run(["ffprobe", "-v", "error", "-show_streams", "-show_format", "-of", "json", str(final)],
                                      capture_output=True, text=True, check=True).stdout)
    assert {s["codec_type"] for s in probe["streams"]} == {"video", "audio"}
    video = next(s for s in probe["streams"] if s["codec_type"] == "video")
    assert (video["width"], video["height"]) == (1920, 1080)
    assert (proj / "captions.srt").read_text().startswith("1\n")
    assert len(list((proj / "thumbnails").glob("thumb*.jpg"))) >= 1
    pack_md = (proj / "upload_pack.md").read_text()
    assert "ARCHIVAL FOOTAGE" in pack_md and "CHAPTERS" in pack_md
    assert (proj / "review.html").exists()
    assert "Las Vegas Age, 1931" in (proj / "factcheck.md").read_text() or "All script quotes match" in (proj / "factcheck.md").read_text()

    assert pipeline.approve(state, pid) == "review_final"


def test_short_pipeline(tmp_path, monkeypatch, film):
    from engine.stages import footage, narration
    from engine.util import write_json

    monkeypatch.setattr(pipeline, "LLM", FakeLLM)
    monkeypatch.setattr(narration, "_tts", fake_tts)
    monkeypatch.setattr(footage, "make_archive", lambda ctx: FakeArchive(film))

    settings = Settings(workspace=tmp_path, pack_name="us-rise-and-fall", llm_provider="api", anthropic_api_key="x",
                        model_deep="m", model_fast="m", web_search=False, vision_footage_check=False,
                        elevenlabs_api_key="x", elevenlabs_voice_id="v", elevenlabs_model="m", user_agent="test")
    state = State(settings.db_path)
    pid = state.create_project("short-dam", "Short: The Dam Built Early", "Built two years early", "us-rise-and-fall")
    d = settings.projects_dir / f"{pid:04d}-short-dam"
    d.mkdir(parents=True)
    write_json(d / "format.json", {"format": "short", "parent": 99})
    write_json(d / "topic.json", {"title": "Short", "parent_title": "The Hoover Dam"})
    write_json(d / "dossier.json", {"summary": "s", "discoveries": [{"fact": "f"}], "quotes": []})

    log = []
    assert pipeline.run(settings, state, pid, echo=log.append) == "waiting"
    assert (d / "on_screen.txt").read_text().strip() == "5 years, 96 men, one dam"
    assert "ON-SCREEN" not in (d / "script.md").read_text()
    assert "PASS" in (d / "script_check.md").read_text()
    pipeline.approve(state, pid)
    assert pipeline.run(settings, state, pid, echo=log.append) == "waiting", "\n".join(log)

    probe = json.loads(subprocess.run(["ffprobe", "-v", "error", "-show_streams", "-show_format", "-of", "json",
                                       str(d / "final.mp4")], capture_output=True, text=True, check=True).stdout)
    video = next(s for s in probe["streams"] if s["codec_type"] == "video")
    assert (video["width"], video["height"]) == (1080, 1920)
    shots = json.loads((d / "footage.json").read_text())
    assert all(s["duration"] <= 3.3 for e in shots.values() for s in e["shots"])
    assert not (d / "thumbnails").exists()
    assert "Short" in (d / "upload_pack.md").read_text()
    assert "Short is" in (d / "qa.md").read_text()
