"""Stage: narration. ElevenLabs text-to-speech with character timestamps.

Narration is generated one chapter at a time (with the neighbouring text sent
as context so the delivery flows), cached by content hash, then joined with a
short pause between chapters. Character timestamps give every beat an exact
start time, and give the captions file.
"""

from __future__ import annotations

import base64
import subprocess
from pathlib import Path

import requests

from ..util import PermanentError, read_json, retry, sha, write_json, write_text

API = "https://api.elevenlabs.io/v1/text-to-speech/{voice}/with-timestamps"
CHAPTER_PAUSE = 0.7
PARAGRAPH_JOIN = "\n\n"


@retry(attempts=5, base_delay=4)
def _tts(ctx, text: str, prev: str, nxt: str) -> dict:
    s = ctx.settings
    if not s.elevenlabs_api_key or not s.elevenlabs_voice_id:
        raise PermanentError("Set ELEVENLABS_API_KEY and ELEVENLABS_VOICE_ID in .env")
    voice = ctx.pack.get("voice", {}) or {}
    body = {
        "text": text,
        "model_id": s.elevenlabs_model,
        "previous_text": prev[-800:] or None,
        "next_text": nxt[:800] or None,
        "voice_settings": {
            "stability": voice.get("stability", 0.45),
            "similarity_boost": voice.get("similarity_boost", 0.8),
            "style": voice.get("style", 0.15),
            "speed": voice.get("speed", 1.0),
        },
    }
    r = requests.post(
        API.format(voice=s.elevenlabs_voice_id),
        params={"output_format": "mp3_44100_128"},
        headers={"xi-api-key": s.elevenlabs_api_key, "Content-Type": "application/json"},
        json=body,
        timeout=300,
    )
    if r.status_code in (401, 403):
        raise PermanentError(f"ElevenLabs rejected the request ({r.status_code}): {r.text[:300]}")
    if r.status_code == 422:
        raise PermanentError(f"ElevenLabs could not process the text: {r.text[:300]}")
    r.raise_for_status()
    return r.json()


def ffprobe_duration(path: Path) -> float:
    out = subprocess.run(
        ["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "default=nw=1:nk=1", str(path)],
        capture_output=True, text=True, check=True,
    )
    return float(out.stdout.strip())


def _fmt_srt(t: float) -> str:
    ms = int(round(t * 1000))
    h, ms = divmod(ms, 3_600_000)
    m, ms = divmod(ms, 60_000)
    s, ms = divmod(ms, 1000)
    return f"{h:02d}:{m:02d}:{s:02d},{ms:03d}"


def captions(words: list[tuple[str, float, float]], max_words: int = 8, max_seconds: float = 3.5) -> str:
    lines, group = [], []
    for w in words:
        group.append(w)
        too_long = len(group) >= max_words or (group[-1][2] - group[0][1]) >= max_seconds
        ends_sentence = w[0].endswith((".", "?", "!", ";", ":"))
        if too_long or ends_sentence:
            lines.append(group)
            group = []
    if group:
        lines.append(group)
    out = []
    for i, g in enumerate(lines, start=1):
        out.append(f"{i}\n{_fmt_srt(g[0][1])} --> {_fmt_srt(g[-1][2])}\n{' '.join(x[0] for x in g)}\n")
    return "\n".join(out)


def run(ctx) -> None:
    beats = read_json(ctx.dir / "shotlist.json")["beats"]
    audio_dir = ctx.dir / "audio"
    audio_dir.mkdir(exist_ok=True)

    # Group beats into chapters; join paragraphs with blank lines, beats in a paragraph with spaces.
    chapters: dict[int, list[dict]] = {}
    for b in beats:
        chapters.setdefault(b["chapter"], []).append(b)
    order = sorted(chapters)
    chapter_texts: dict[int, str] = {}
    offsets: dict[int, int] = {}
    for c in order:
        text = ""
        last_para = None
        for b in chapters[c]:
            sep = "" if not text else (" " if b["paragraph"] == last_para else PARAGRAPH_JOIN)
            text += sep
            offsets[b["id"]] = len(text)
            text += b["text"]
            last_para = b["paragraph"]
        chapter_texts[c] = text

    segments: list[Path] = []
    timeline_offset = 0.0
    starts: dict[int, float] = {}
    all_words: list[tuple[str, float, float]] = []
    total_chars = 0

    for i, c in enumerate(order):
        text = chapter_texts[c]
        prev = chapter_texts[order[i - 1]] if i > 0 else ""
        nxt = chapter_texts[order[i + 1]] if i + 1 < len(order) else ""
        key = sha(f"{ctx.settings.elevenlabs_voice_id}|{ctx.settings.elevenlabs_model}|{ctx.pack.get('voice')}|{text}")
        mp3, align_path = audio_dir / f"ch{c:02d}-{key}.mp3", audio_dir / f"ch{c:02d}-{key}.json"
        if not (mp3.exists() and align_path.exists()):
            data = _tts(ctx, text, prev, nxt)
            mp3.write_bytes(base64.b64decode(data["audio_base64"]))
            write_json(align_path, data.get("alignment") or data.get("normalized_alignment") or {})
            total_chars += len(text)
        align = read_json(align_path)
        chars = align.get("characters", [])
        t_start = align.get("character_start_times_seconds", [])
        t_end = align.get("character_end_times_seconds", [])

        for b in chapters[c]:
            idx = min(offsets[b["id"]], max(len(t_start) - 1, 0))
            starts[b["id"]] = timeline_offset + (t_start[idx] if t_start else 0.0)

        word, w_start, w_end = "", 0.0, 0.0
        for ch, s, e in zip(chars, t_start, t_end):
            if ch.isspace():
                if word:
                    all_words.append((word, timeline_offset + w_start, timeline_offset + w_end))
                word = ""
                continue
            if not word:
                w_start = s
            word += ch
            w_end = e
        if word:
            all_words.append((word, timeline_offset + w_start, timeline_offset + w_end))

        segments.append(mp3)
        timeline_offset += ffprobe_duration(mp3) + CHAPTER_PAUSE

    if total_chars:
        ctx.usage("elevenlabs", total_chars, "characters", ctx.settings.elevenlabs_model)

    # Join chapters with silence into one WAV.
    concat_list = ctx.path("audio", "concat.txt")
    silence = ctx.path("audio", "pause.wav")
    subprocess.run(["ffmpeg", "-y", "-v", "error", "-f", "lavfi", "-i", "anullsrc=r=44100:cl=mono",
                    "-t", str(CHAPTER_PAUSE), str(silence)], check=True)
    parts = []
    for i, seg in enumerate(segments):
        wav = seg.with_suffix(".wav")
        if not wav.exists():
            subprocess.run(["ffmpeg", "-y", "-v", "error", "-i", str(seg), "-ar", "44100", "-ac", "1", str(wav)], check=True)
        parts.append(wav)
        if i + 1 < len(segments):
            parts.append(silence)
    concat_list.write_text("".join(f"file '{p.resolve()}'\n" for p in parts), encoding="utf-8")
    narration = ctx.path("narration.wav")
    subprocess.run(["ffmpeg", "-y", "-v", "error", "-f", "concat", "-safe", "0", "-i", str(concat_list),
                    "-c", "copy", str(narration)], check=True)

    total = ffprobe_duration(narration)
    ordered = [b["id"] for b in beats]
    timing = []
    for i, bid in enumerate(ordered):
        start = 0.0 if i == 0 else starts[bid]
        end = starts[ordered[i + 1]] if i + 1 < len(ordered) else total + 1.5
        timing.append({"id": bid, "start": round(start, 3), "end": round(end, 3), "duration": round(end - start, 3)})
    write_json(ctx.path("timing.json"), {"beats": timing, "total": total})
    write_text(ctx.path("captions.srt"), captions(all_words))
    ctx.log.info("narration: %.1f s across %d chapters", total, len(order))
