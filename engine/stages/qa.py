"""Stage: qa. Automated checks on the finished video, then the review page.

Hard failures (the stage fails): missing video or audio, or a video whose
length does not match the narration. Everything else is a warning listed in
qa.md and on review.html for you to judge.
"""

from __future__ import annotations

import html
import json
import re
import subprocess
from pathlib import Path

from ..util import PermanentError, read_json, write_text


def probe(path: Path) -> dict:
    out = subprocess.run(["ffprobe", "-v", "error", "-show_format", "-show_streams", "-of", "json", str(path)],
                         capture_output=True, text=True, check=True)
    return json.loads(out.stdout)


def black_intervals(path: Path) -> list[tuple[float, float]]:
    proc = subprocess.run(["ffmpeg", "-v", "info", "-i", str(path), "-vf", "blackdetect=d=1.5:pix_th=0.08",
                           "-an", "-f", "null", "-"], capture_output=True, text=True)
    return [(float(a), float(b)) for a, b in re.findall(r"black_start:([\d.]+) black_end:([\d.]+)", proc.stderr)]


def loudness(path: Path) -> float | None:
    proc = subprocess.run(["ffmpeg", "-v", "info", "-i", str(path), "-vn", "-af", "ebur128", "-f", "null", "-"],
                          capture_output=True, text=True)
    m = re.findall(r"I:\s+(-?[\d.]+) LUFS", proc.stderr)
    return float(m[-1]) if m else None


def run(ctx) -> None:
    final = ctx.dir / "final.mp4"
    if not final.exists():
        raise PermanentError("final.mp4 is missing; re-run the render stage")
    info = probe(final)
    kinds = {s["codec_type"] for s in info["streams"]}
    if kinds != {"video", "audio"}:
        raise PermanentError(f"final.mp4 should have one video and one audio stream, found {sorted(kinds)}")

    timing = read_json(ctx.dir / "timing.json")
    expected = sum(t["duration"] for t in timing["beats"])
    actual = float(info["format"]["duration"])
    if abs(actual - expected) > 2.0:
        raise PermanentError(f"Video is {actual:.1f}s but narration timeline is {expected:.1f}s")

    warnings: list[str] = []
    passes: list[str] = [f"Length {actual / 60:.1f} min ({actual:.1f}s), matches narration"]

    if ctx.is_short:
        limit = float(ctx.setting("max_seconds", 59))
        (warnings if actual > limit else passes).append(
            f"Short is {actual:.1f}s (limit {limit:.0f}s)" + (": trim the script and redo from narration" if actual > limit else ""))
        video = next(s for s in info["streams"] if s["codec_type"] == "video")
        (passes if video["height"] > video["width"] else warnings).append(f"Frame {video['width']}x{video['height']}")

    check_file = ctx.dir / "script_check.md"
    if check_file.exists():
        last = check_file.read_text(encoding="utf-8").strip().split("## Draft")[-1]
        headline = next((l for l in last.splitlines() if l.startswith("Score")), "")
        if headline:
            (passes if "PASS" in headline else warnings).append(f"Script checker: {headline}")

    blacks = black_intervals(final)
    inner = [(a, b) for a, b in blacks if a > 2 and b < actual - 2]
    (warnings if inner else passes).append(
        f"Black stretches mid-video: {', '.join(f'{a:.0f}-{b:.0f}s' for a, b in inner)}" if inner else "No black stretches mid-video")

    target = float(ctx.pack.get("audio.target_lufs", -14))
    lufs = loudness(final)
    if lufs is None or abs(lufs - target) > 2:
        warnings.append(f"Loudness {lufs} LUFS (target {target})")
    else:
        passes.append(f"Loudness {lufs:.1f} LUFS (target {target})")

    footage = read_json(ctx.dir / "footage.json") if (ctx.dir / "footage.json").exists() else {}
    fallbacks = [k for k, v in footage.items() if v.get("fallback")]
    archival = len(footage)
    if archival and len(fallbacks) / archival > 0.1:
        warnings.append(f"{len(fallbacks)} of {archival} footage beats fell back to plain cards (beats {', '.join(fallbacks[:12])})")
    elif archival:
        passes.append(f"Footage found for {archival - len(fallbacks)} of {archival} beats")
    if (ctx.dir / "shotcheck.json").exists():
        checked = read_json(ctx.dir / "shotcheck.json")
        flagged = [k for k, v in checked.items() if not v.get("ok")]
        (warnings if flagged else passes).append(
            f"Shot check: {len(checked) - len(flagged)} of {len(checked)} shots fit their line"
            + (f" (flagged: beats {', '.join(flagged[:12])}; see shotcheck.html)" if flagged else ""))

    fc = (ctx.dir / "factcheck.md").read_text(encoding="utf-8") if (ctx.dir / "factcheck.md").exists() else ""
    needs = fc.split("## Still needs your eyes", 1)[-1].split("## Quotes", 1)[0] if fc else ""
    open_items = [l for l in needs.splitlines() if l.startswith("- **")]
    if open_items:
        warnings.append(f"{len(open_items)} fact-check items still need your eyes (factcheck.md)")
    quote_flags = [l for l in fc.split("## Quotes", 1)[-1].splitlines() if l.startswith("- Quote")] if fc else []
    if quote_flags:
        warnings.append(f"{len(quote_flags)} quotes are not matched word for word to a fetched source")

    package = read_json(ctx.dir / "package.json") if (ctx.dir / "package.json").exists() else {}
    long_titles = [t for t in package.get("titles", []) if len(t) > 70]
    if long_titles:
        warnings.append(f"{len(long_titles)} title options are over 70 characters")
    desc = (ctx.dir / "description.txt").read_text(encoding="utf-8") if (ctx.dir / "description.txt").exists() else ""
    if len(desc) > 5000:
        warnings.append("Description is over YouTube's 5,000 character limit")
    if "CHAPTERS" not in desc and not ctx.is_short:
        warnings.append("No chapters in the description (fewer than 3 chapters of 10s+)")

    lines = ["# QA report", "", "## Passed"] + [f"- {p}" for p in passes]
    lines += ["", "## Warnings"] + ([f"- {w}" for w in warnings] or ["- None"])
    write_text(ctx.path("qa.md"), "\n".join(lines) + "\n")
    review_page(ctx, passes, warnings)


def review_page(ctx, passes: list[str], warnings: list[str]) -> Path:
    def read(name: str) -> str:
        p = ctx.dir / name
        return p.read_text(encoding="utf-8") if p.exists() else ""

    thumbs = sorted((ctx.dir / "thumbnails").glob("thumb*.jpg"))
    package = read_json(ctx.dir / "package.json") if (ctx.dir / "package.json").exists() else {}
    esc = html.escape
    items = "".join(f"<li class=ok>{esc(p)}</li>" for p in passes) + "".join(f"<li class=warn>{esc(w)}</li>" for w in warnings)
    titles = "".join(f"<li>{esc(t)}</li>" for t in package.get("titles", []))
    thumbs_html = "".join(f"<img src='thumbnails/{t.name}' alt='{t.name}'>" for t in thumbs)
    page = f"""<!doctype html><html lang=en><head><meta charset=utf-8>
<meta name=viewport content="width=device-width,initial-scale=1"><title>Review: {esc(ctx.title)}</title>
<style>
:root{{--bg:#f6f3ee;--fg:#1d1a16;--muted:#6b645a;--card:#fff;--ok:#2f6b3a;--warn:#9a5b00;--line:#e2dccf}}
@media (prefers-color-scheme:dark){{:root{{--bg:#151412;--fg:#ece7de;--muted:#a39c90;--card:#1e1c19;--ok:#7fc48b;--warn:#f0b35a;--line:#2e2b26}}}}
body{{margin:0;background:var(--bg);color:var(--fg);font:16px/1.55 Georgia,serif}}
main{{max-width:1100px;margin:0 auto;padding:24px 16px 80px}}
h1{{font-size:28px;margin:8px 0}} h2{{font-size:19px;margin:32px 0 10px;border-bottom:1px solid var(--line);padding-bottom:6px}}
video{{width:100%;border-radius:8px;background:#000}}
.thumbs{{display:grid;grid-template-columns:repeat(auto-fit,minmax(240px,1fr));gap:12px}} .thumbs img{{width:100%;border-radius:6px}}
li.ok{{color:var(--ok)}} li.warn{{color:var(--warn)}}
pre{{white-space:pre-wrap;background:var(--card);border:1px solid var(--line);padding:14px;border-radius:6px;font:14px/1.5 ui-monospace,monospace;overflow-x:auto}}
.muted{{color:var(--muted)}}
</style></head><body><main>
<p class=muted>Final review · project {ctx.project_id}</p><h1>{esc(ctx.title)}</h1>
<video controls src="final.mp4" style="{'max-height:80vh;width:auto;display:block;margin:0 auto' if ctx.is_short else ''}"></video>
<h2>Checks</h2><ul>{items}</ul>
<h2>Thumbnails</h2><div class=thumbs>{thumbs_html}</div>
<h2>Title options</h2><ol>{titles}</ol>
<h2>Description</h2><pre>{esc(read('description.txt'))}</pre>
<h2>Fact-check</h2><pre>{esc(read('factcheck.md'))}</pre>
<h2>Script</h2><pre>{esc(read('script.md'))}</pre>
<p class=muted>When you are happy: <code>de approve {ctx.project_id}</code>, upload by hand, then <code>de published {ctx.project_id} &lt;url&gt;</code>.</p>
</main></body></html>"""
    path = ctx.path("review.html")
    write_text(path, page)
    return path
