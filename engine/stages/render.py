"""Stage: render. Assembles the final video with FFmpeg.

Every beat becomes one segment of exactly its narration length:
- archival beats: the cut clips, colour-graded with light film grain. With
  `footage.fit: fill` old 4:3 film is cropped to fill the 16:9 frame; with
  `blur` it sits over a blurred copy of itself instead
- quote and number beats: the card's text over moving footage when the
  footage stage found some, otherwise a card with a slow push-in
- the first beat of each chapter carries the chapter title

Segments are joined, the narration is mixed over an optional music bed that
ducks under the voice, and loudness is normalised for YouTube.
"""

from __future__ import annotations

import random
import re
import subprocess
from pathlib import Path

from .. import cards, karaoke
from ..util import read_json

NO_ON_SCREEN_TITLE = {"closing", "conclusion", "outro", "epilogue", "intro", "introduction"}

GRADES = {
    "vintage": "eq=saturation=0.78:contrast=1.06:gamma=0.97,curves=preset=vintage,noise=alls=7:allf=t",
    "neutral": "eq=saturation=0.95:contrast=1.03",
    "bw": "hue=s=0,eq=contrast=1.12:gamma=0.97,noise=alls=5:allf=t",
}
# Clips shorter than their beat play slightly slower (up to this factor) before the last frame holds.
MAX_STRETCH = 1.3


def _run(args: list[str], timeout: int = 900) -> None:
    proc = subprocess.run(["ffmpeg", "-y", "-v", "error", *args], capture_output=True, text=True, timeout=timeout)
    if proc.returncode != 0:
        raise RuntimeError(f"ffmpeg failed: {proc.stderr.strip()[-800:]}")


def letterbox_crop(clip: Path) -> str:
    """A crop filter that removes black bars baked into a clip, or "" when it has none.

    Archive films are often 4:3 pictures stored in a 16:9 file with black
    pillars, which would survive a plain scale-to-fill.
    """
    # Black bars first; then dark grey ones, which only count as pillars or
    # letterbox bars (centred, full height or full width), so a dark scene
    # is never cropped into.
    for limit in (24, 40):
        proc = subprocess.run(["ffmpeg", "-v", "info", "-i", str(clip), "-vf", f"cropdetect=limit={limit}:round=2:reset=0",
                               "-f", "null", "-"], capture_output=True, text=True, timeout=300)
        found = re.findall(r"crop=(\d+):(\d+):(\d+):(\d+)", proc.stderr)
        size = re.search(r"Video:.*?(\d{2,5})x(\d{2,5})", proc.stderr)
        if not found or not size:
            return ""
        cw, ch, x, y = (int(v) for v in found[-1])
        w, h = int(size.group(1)), int(size.group(2))
        if cw > w * 0.97 and ch > h * 0.97:
            continue  # no bars at this threshold
        pillars = ch >= h * 0.97 and abs(x - (w - cw - x)) <= w * 0.03
        letterbox = cw >= w * 0.97 and abs(y - (h - ch - y)) <= h * 0.03
        if (pillars or letterbox) and cw >= w * 0.4 and ch >= h * 0.4:
            return f"crop={cw}:{h if pillars else ch}:{x}:{0 if pillars else y},"
    return ""


def _encode_args(fps: int) -> list[str]:
    # Film grain changes every frame, so constant quality alone can reach 60 Mbps;
    # cap it near YouTube's recommended 1080p upload rate.
    return ["-r", str(fps), "-c:v", "libx264", "-preset", "medium", "-crf", "19", "-maxrate", "12M", "-bufsize", "24M",
            "-pix_fmt", "yuv420p", "-an"]


def card_segment(image: Path, duration: float, dest: Path, w: int, h: int, fps: int, overlay: Path | None,
                 fade_in: bool, fade_out: bool) -> None:
    frames = max(1, round(duration * fps))
    chain = (f"[0:v]scale={w * 2}:-2,zoompan=z='min(zoom+0.0004,1.08)':x='iw/2-(iw/zoom/2)':y='ih/2-(ih/zoom/2)'"
             f":d={frames}:s={w}x{h}:fps={fps},setsar=1[v0]")
    _finish(["-i", str(image)], chain, duration, dest, w, h, fps, overlay, fade_in, fade_out)


def clip_segment(clips: list[Path], duration: float, dest: Path, w: int, h: int, fps: int, grade: str,
                 overlay: Path | None, fade_in: bool, fade_out: bool, fit: str = "blur",
                 text: Path | None = None, clip_seconds: float = 0.0) -> None:
    inputs: list[str] = []
    parts = []
    look = GRADES.get(grade, GRADES["neutral"])
    for i, clip in enumerate(clips):
        inputs += ["-i", str(clip)]
        if fit == "fill":
            parts.append(f"[{i}:v]fps={fps},{letterbox_crop(clip)}scale={w}:{h}:force_original_aspect_ratio=increase,crop={w}:{h},{look},setsar=1[c{i}]")
        else:
            parts.append(
                f"[{i}:v]fps={fps},split[a{i}][b{i}];"
                f"[a{i}]scale={w}:{h}:force_original_aspect_ratio=increase,crop={w}:{h},gblur=sigma=28,eq=brightness=-0.13[bg{i}];"
                f"[b{i}]scale={w}:{h}:force_original_aspect_ratio=decrease[fg{i}];"
                f"[bg{i}][fg{i}]overlay=(W-w)/2:(H-h)/2,{look},setsar=1[c{i}]"
            )
    joined = "".join(f"[c{i}]" for i in range(len(clips)))
    stretch = min(MAX_STRETCH, duration / clip_seconds) if 0 < clip_seconds < duration else 1.0
    slow = f"setpts={stretch:.4f}*PTS," if stretch > 1.001 else ""
    chain = ";".join(parts) + f";{joined}concat=n={len(clips)}:v=1:a=0,{slow}tpad=stop_mode=clone:stop_duration={duration + 2:.2f}[v0]"
    _finish(inputs, chain, duration, dest, w, h, fps, overlay, fade_in, fade_out, text)


def _finish(inputs: list[str], chain: str, duration: float, dest: Path, w: int, h: int, fps: int,
            overlay: Path | None, fade_in: bool, fade_out: bool, text: Path | None = None) -> None:
    label = "v0"
    if text is not None:  # card text held over the footage for the whole beat
        idx = inputs.count("-i")
        inputs = inputs + ["-loop", "1", "-t", f"{duration:.3f}", "-i", str(text)]
        chain += (f";[{idx}:v]format=rgba,fade=in:st=0:d=0.5:alpha=1[tx]"
                  f";[{label}][tx]overlay=0:0:shortest=1[vt]")
        label = "vt"
    if overlay is not None:
        idx = inputs.count("-i")
        inputs = inputs + ["-loop", "1", "-t", f"{duration:.3f}", "-i", str(overlay)]
        show_until = max(1.2, min(duration - 0.3, 4.2))
        chain += (f";[{idx}:v]format=rgba,fade=in:st=0.3:d=0.6:alpha=1,fade=out:st={show_until - 0.6:.2f}:d=0.6:alpha=1[ov]"
                  f";[{label}][ov]overlay=0:0:shortest=1[v1]")
        label = "v1"
    extra = []
    if fade_in:
        extra.append("fade=in:st=0:d=1.2")
    if fade_out:
        extra.append(f"fade=out:st={max(0.0, duration - 1.5):.2f}:d=1.5")
    if extra:
        chain += f";[{label}]{','.join(extra)}[v2]"
        label = "v2"
    chain += f";[{label}]format=yuv420p[out]"
    _run([*inputs, "-filter_complex", chain, "-map", "[out]", "-t", f"{duration:.3f}", *_encode_args(fps), str(dest)])


def mix_audio(ctx, narration: Path, total: float, dest: Path) -> None:
    audio = ctx.pack.get("audio", {}) or {}
    lufs = float(audio.get("target_lufs", -14))
    music_dir = ctx.pack.path / str(audio.get("music_dir", "music"))
    tracks = sorted(p for p in music_dir.glob("*") if p.suffix.lower() in {".mp3", ".wav", ".m4a", ".ogg"}) if music_dir.exists() else []
    norm = f"loudnorm=I={lufs}:TP=-1.5:LRA=11"
    if not tracks:
        _run(["-i", str(narration), "-af", f"aformat=sample_rates=48000:channel_layouts=stereo,apad,{norm}",
              "-t", f"{total:.3f}", "-c:a", "aac", "-b:a", "192k", str(dest)])
        return
    track = random.Random(ctx.project_id).choice(tracks)
    vol = float(audio.get("music_volume_db", -24))
    chain = (
        "[0:a]aformat=sample_rates=48000:channel_layouts=stereo,apad,asplit=2[voice][key];"
        f"[1:a]aformat=sample_rates=48000:channel_layouts=stereo,volume={vol}dB,"
        f"afade=t=out:st={max(0.0, total - 4):.2f}:d=4[music];"
        "[music][key]sidechaincompress=threshold=0.02:ratio=5:attack=30:release=600[ducked];"
        f"[voice][ducked]amix=inputs=2:duration=first:normalize=0,{norm}[a]"
    )
    _run(["-i", str(narration), "-stream_loop", "-1", "-i", str(track), "-filter_complex", chain,
          "-map", "[a]", "-t", f"{total:.3f}", "-c:a", "aac", "-b:a", "192k", str(dest)])
    ctx.log.info("render: music bed %s", track.name)


def burn_subtitles(ctx, cfg: dict, video: Path, total: float, w: int, h: int, fps: int, dest: Path) -> None:
    """Long videos: sentence subtitles that follow the narration, burned in."""
    words_path = ctx.dir / "words.json"
    words = [(x["text"], x["start"], x["end"]) for x in read_json(words_path)] if words_path.exists() else []
    if not words:
        ctx.log.warning("render: no words.json; skipping subtitles")
        _run(["-i", str(video), "-c", "copy", "-movflags", "+faststart", str(dest)])
        return
    listing = karaoke.build_subtitles(
        words, total, ctx.dir / "render" / "subtitles", (w, h), ctx.pack.path / "fonts" / str(cfg.get("font", "")),
        int(cfg.get("size", 36)), int(cfg.get("y", h - 70)), str(cfg.get("color", "#F39C2B")), int(cfg.get("weight", 600)),
    )
    _overlay_sequence(video, listing, total, fps, dest)
    ctx.log.info("render: subtitles burned in")


def _overlay_sequence(video: Path, listing: Path, total: float, fps: int, dest: Path) -> None:
    _run(["-i", str(video), "-f", "concat", "-safe", "0", "-i", str(listing),
          "-filter_complex", f"[1:v]fps={fps},format=rgba[cap];[0:v][cap]overlay=0:0:shortest=0:eof_action=pass,format=yuv420p[v]",
          "-map", "[v]", "-map", "0:a", "-c:v", "libx264", "-preset", "medium", "-crf", "19", "-maxrate", "12M",
          "-bufsize", "24M", "-c:a", "copy", "-t", f"{total:.3f}", "-movflags", "+faststart", str(dest)], timeout=3600)


def burn_short_overlay(ctx, video: Path, total: float, w: int, h: int, fps: int, dest: Path) -> None:
    """Shorts: one-word captions plus the on-screen hook in the first seconds."""
    cfg = ctx.pack.get("shorts.captions", {}) or {}
    words_path = ctx.dir / "words.json"
    words = [(x["text"], x["start"], x["end"]) for x in read_json(words_path)] if words_path.exists() else []
    hook_file = ctx.dir / "on_screen.txt"
    hook = hook_file.read_text(encoding="utf-8").strip() if hook_file.exists() else ""
    font_path = ctx.pack.path / "fonts" / str(cfg.get("font", "Montserrat-VariableFont_wght.ttf"))
    listing = karaoke.build_overlay(
        words, total, hook, float(ctx.setting("hook_text_seconds", 3.0)), ctx.dir / "render" / "captions",
        (w, h), font_path, int(cfg.get("size", 92)), int(cfg.get("y", int(h * 0.70))),
    )
    _overlay_sequence(video, listing, total, fps, dest)


def run(ctx) -> None:
    w, h = (int(x) for x in ctx.setting("resolution", [1920, 1080]))
    fps = int(ctx.setting("fps", 30))
    grade = str(ctx.pack.get("footage.grade", "vintage"))
    fit = str(ctx.pack.get("footage.fit", "blur"))
    accent = ctx.pack.get("thumbnail.colors.accent", "#E8B33A")
    font_dirs = [ctx.pack.path / "fonts"]

    beats = read_json(ctx.dir / "shotlist.json")["beats"]
    timing = {t["id"]: t for t in read_json(ctx.dir / "timing.json")["beats"]}
    footage = read_json(ctx.dir / "footage.json") if (ctx.dir / "footage.json").exists() else {}

    seg_dir = ctx.dir / "render" / "segments"
    card_dir = ctx.dir / "render" / "cards"
    seg_dir.mkdir(parents=True, exist_ok=True)
    card_dir.mkdir(parents=True, exist_ok=True)

    segments: list[Path] = []
    for i, beat in enumerate(beats):
        bid = beat["id"]
        duration = timing[bid]["duration"]
        dest = seg_dir / f"seg{bid:03d}.mp4"
        segments.append(dest)
        if dest.exists() and dest.stat().st_size > 0:
            continue  # resumed run
        overlay = None
        title = (beat.get("chapter_title") or "").strip()
        if (beat.get("first_in_chapter") and beat.get("chapter", 0) > 0 and title
                and title.lower() not in NO_ON_SCREEN_TITLE):
            overlay = cards.chapter_overlay(beat["chapter_title"], card_dir / f"chapter{beat['chapter']:02d}.png", (w, h), font_dirs)
        # Shorts start on a moving frame and end on the last word (no fades, so they loop cleanly).
        fade_in, fade_out = (i == 0 and not ctx.is_short), (i == len(beats) - 1 and not ctx.is_short)
        visual = beat["visual"].get("visual")
        entry = footage.get(str(bid), {})
        shots = [Path(s["path"]) for s in entry.get("shots", []) if Path(s["path"]).exists()]
        clip_seconds = sum(float(s.get("duration", 0)) for s in entry.get("shots", []) if Path(s["path"]).exists())

        if visual in ("quote", "number") and shots:
            if visual == "quote":
                text = cards.quote_overlay(beat["text"], beat.get("attribution", ""), card_dir / f"quote{bid:03d}.png", (w, h), font_dirs)
            else:
                text = cards.number_overlay(beat["visual"].get("big_text", ""), beat["visual"].get("small_text", ""),
                                            card_dir / f"number{bid:03d}.png", (w, h), fonts=font_dirs)
            clip_segment(shots, duration, dest, w, h, fps, grade, overlay, fade_in, fade_out, fit, text, clip_seconds)
        elif visual == "quote":
            img = cards.quote_card(beat["text"], beat.get("attribution", ""), card_dir / f"quote{bid:03d}.jpg", (w, h), font_dirs)
            card_segment(img, duration, dest, w, h, fps, overlay, fade_in, fade_out)
        elif visual == "number":
            img = cards.number_card(beat["visual"].get("big_text", ""), beat["visual"].get("small_text", ""),
                                    card_dir / f"number{bid:03d}.jpg", (w, h), accent, font_dirs)
            card_segment(img, duration, dest, w, h, fps, overlay, fade_in, fade_out)
        else:
            if shots:
                clip_segment(shots, duration, dest, w, h, fps, grade, overlay, fade_in, fade_out, fit,
                             clip_seconds=clip_seconds)
            else:
                img = cards.fallback_card(beat.get("chapter_title") or ctx.title, card_dir / f"fallback{bid:03d}.jpg", (w, h), font_dirs)
                card_segment(img, duration, dest, w, h, fps, overlay, fade_in, fade_out)
        ctx.log.info("render: segment %d/%d", i + 1, len(beats))

    concat = ctx.dir / "render" / "segments.txt"
    concat.write_text("".join(f"file '{s.resolve()}'\n" for s in segments), encoding="utf-8")
    silent = ctx.dir / "render" / "video_silent.mp4"
    _run(["-f", "concat", "-safe", "0", "-i", str(concat), "-c", "copy", str(silent)])

    total = sum(timing[b["id"]]["duration"] for b in beats)
    mixed = ctx.dir / "render" / "audio.m4a"
    mix_audio(ctx, ctx.dir / "narration.wav", total, mixed)

    final = ctx.path("final.mp4")
    subtitles = None if ctx.is_short else ctx.pack.get("video.subtitles")
    muxed = ctx.dir / "render" / "muxed.mp4" if (ctx.is_short or subtitles) else final
    _run(["-i", str(silent), "-i", str(mixed), "-map", "0:v", "-map", "1:a", "-c", "copy",
          "-t", f"{total:.3f}", "-movflags", "+faststart", str(muxed)])
    if ctx.is_short:
        burn_short_overlay(ctx, muxed, total, w, h, fps, final)
    elif subtitles:
        burn_subtitles(ctx, subtitles, muxed, total, w, h, fps, final)
    ctx.log.info("render: final.mp4 %.1f s", total)
