"""Stage: shotcheck. Audits every cut clip against its line before anything
is rendered, so a wrong shot costs a footage search instead of a render.

1. For each beat in footage.json, grab four frames from each of its cut clips
   (local files, so this is fast) and make one contact sheet per beat.
2. Flag sheets that are too dark, blown out or flat.
3. Claude looks at the sheets a few beats at a time and flags any shot that
   does not fit its narration or breaks the pack's footage.avoid list.
4. Flagged beats are searched again automatically (footage.reshoot), up to
   the pack's footage.auto_reshoot_rounds, and re-audited.
5. shotcheck.html shows every beat's line next to its frames, problems first,
   for the review_shots gate. `de reshoot <id> <beat...>` replaces any shot
   you still dislike.
"""

from __future__ import annotations

import html
import subprocess
from pathlib import Path

from . import footage as footage_stage
from ..util import PermanentError, read_json, write_json, write_text

BATCH = 6


def _probe(path: Path) -> float:
    proc = subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "default=nw=1:nk=1",
                           str(path)], capture_output=True, text=True, timeout=60)
    try:
        return float(proc.stdout.strip())
    except ValueError:
        return 0.0


def beat_sheet(ctx, bid: int, entry: dict) -> tuple[Path | None, list[Path]]:
    out_dir = ctx.dir / "footage" / "check"
    out_dir.mkdir(parents=True, exist_ok=True)
    frames: list[Path] = []
    for k, shot in enumerate(entry.get("shots", [])):
        clip = Path(shot["path"])
        if not clip.exists():
            continue
        length = _probe(clip) or float(shot.get("duration", 3))
        for j, t in enumerate(footage_stage.sample_times(0.0, length)):
            f = out_dir / f"b{bid:03d}-{k}-{j}.jpg"
            if footage_stage.grab_frame(str(clip), min(t, max(length - 0.1, 0)), f):
                frames.append(f)
    if not frames:
        return None, []
    return footage_stage.contact_sheet(frames[:8], out_dir / f"b{bid:03d}.jpg"), frames


def _line(beat: dict) -> str:
    v = beat["visual"]
    if v.get("visual") == "number":
        return f'{beat["text"]} (on screen over the footage: {v.get("big_text", "")} {v.get("small_text", "")})'
    return beat["text"]


def audit(ctx, beats: dict[int, dict], plan: dict) -> dict[str, dict]:
    """Return {beat id: {"ok": bool, "problem": str, "sheet": str}} for these beats."""
    cfg = ctx.pack.get("footage", {}) or {}
    results: dict[str, dict] = {}
    to_ask: list[tuple[int, Path]] = []
    for bid, beat in beats.items():
        entry = plan.get(str(bid), {})
        if not entry.get("shots"):
            results[str(bid)] = {"ok": False, "problem": "no footage (falls back to a card)", "sheet": ""}
            continue
        sheet, frames = beat_sheet(ctx, bid, entry)
        if sheet is None:
            results[str(bid)] = {"ok": False, "problem": "clip files missing", "sheet": ""}
            continue
        problem = footage_stage.exposure_problem(frames, cfg)
        results[str(bid)] = {"ok": not problem, "problem": problem, "sheet": str(sheet)}
        if not problem:
            to_ask.append((bid, sheet))

    if not ctx.settings.vision_footage_check:
        for bid, _ in to_ask:
            results[str(bid)]["problem"] = "not checked (VISION_FOOTAGE_CHECK is off)"
        return results

    for i in range(0, len(to_ask), BATCH):
        batch = to_ask[i:i + BATCH]
        listing = "\n".join(
            f'Image {n}: beat {bid}. Narration: "{_line(beats[bid])}" Ideal shot: {beats[bid]["visual"].get("look_for", "")}'
            for n, (bid, _) in enumerate(batch, start=1))
        prompt = ctx.pack.prompt("shot_audit", beats=listing, count=str(len(batch)),
                                 avoid=footage_stage.avoid_list(ctx, {}))
        try:
            verdict = ctx.llm.complete_json(prompt, tier="fast", max_tokens=1200, images=[s for _, s in batch])
        except Exception as exc:  # noqa: BLE001
            raise PermanentError(f"shotcheck: the vision check failed ({exc}). Fix it and run again.") from exc
        by_id = {int(r.get("id", 0)): r for r in verdict.get("beats", []) if str(r.get("id", "")).isdigit()}
        for bid, _ in batch:
            r = by_id.get(bid)
            if r is None:
                results[str(bid)]["problem"] = "not checked (no verdict returned)"
                results[str(bid)]["ok"] = False
            else:
                results[str(bid)]["ok"] = bool(r.get("ok"))
                results[str(bid)]["problem"] = "" if r.get("ok") else str(r.get("problem", "does not fit"))
    return results


def write_report(ctx, beats: dict[int, dict], results: dict[str, dict]) -> None:
    timing = {t["id"]: t for t in read_json(ctx.dir / "timing.json")["beats"]}
    write_json(ctx.path("shotcheck.json"), results)
    flagged = [b for b in beats if not results.get(str(b), {}).get("ok")]
    order = flagged + [b for b in beats if b not in flagged]

    def stamp(t: float) -> str:
        return f"{int(t) // 60}:{int(t) % 60:02d}"

    rows = []
    for bid in order:
        r = results.get(str(bid), {})
        sheet = Path(r["sheet"]).relative_to(ctx.dir).as_posix() if r.get("sheet") else ""
        status = "OK" if r.get("ok") else html.escape(r.get("problem", "")) or "not checked"
        img = f'<img src="{sheet}">' if sheet else ""
        rows.append(
            f'<tr class="{"ok" if r.get("ok") else "bad"}"><td>{bid}<br><small>{stamp(timing[bid]["start"])}</small></td>'
            f'<td>{html.escape(_line(beats[bid]))}<br><b>{status}</b></td><td>{img}</td></tr>')
    page = f"""<!doctype html><meta charset="utf-8"><title>Shot check</title>
<style>body{{font:15px system-ui;margin:24px;background:#111;color:#eee}}table{{border-collapse:collapse;width:100%}}
td{{border-bottom:1px solid #333;padding:8px;vertical-align:top}}td:nth-child(2){{width:32%}}img{{max-width:100%}}
tr.bad td:nth-child(2) b{{color:#ff8a65}}tr.ok td:nth-child(2) b{{color:#81c784}}code{{background:#222;padding:2px 4px}}</style>
<h1>Shot check: {html.escape(ctx.title)}</h1>
<p>{len(flagged)} of {len(beats)} beats need a look (listed first). To replace shots:
<code>de reshoot {ctx.project_id} &lt;beat&gt; [&lt;beat&gt; ...]</code>. When every shot is right: <code>de approve {ctx.project_id}</code>.</p>
<table>{"".join(rows)}</table>"""
    write_text(ctx.path("shotcheck.html"), page)


def check(ctx, only: list[int] | None = None, rounds: int | None = None) -> dict[str, dict]:
    """Audit (some) beats, reshoot what fails, and rewrite the report."""
    cfg = ctx.pack.get("footage", {}) or {}
    rounds = int(cfg.get("auto_reshoot_rounds", 2)) if rounds is None else rounds
    all_beats = {b["id"]: b for b in read_json(ctx.dir / "shotlist.json")["beats"]}
    plan = read_json(ctx.dir / "footage.json")
    beats = {bid: b for bid, b in all_beats.items() if str(bid) in plan}
    previous = read_json(ctx.dir / "shotcheck.json") if (ctx.dir / "shotcheck.json").exists() else {}
    results = {k: v for k, v in previous.items() if k in {str(b) for b in beats}}

    targets = {bid: beats[bid] for bid in (only if only is not None else beats) if bid in beats}
    results.update(audit(ctx, targets, plan))
    for n in range(rounds):
        failed = [bid for bid in targets if not results[str(bid)]["ok"]
                  and not results[str(bid)]["problem"].startswith("not checked")]
        if not failed:
            break
        ctx.log.info("shotcheck: round %d, searching again for beats %s", n + 1, ", ".join(map(str, failed)))
        footage_stage.reshoot(ctx, failed)
        plan = read_json(ctx.dir / "footage.json")
        results.update(audit(ctx, {bid: beats[bid] for bid in failed}, plan))
    write_report(ctx, beats, results)
    bad = [k for k, v in results.items() if not v["ok"]]
    ctx.log.info("shotcheck: %d of %d beats pass%s", len(results) - len(bad), len(results),
                 f"; still flagged: {', '.join(bad)}" if bad else "")
    return results


def run(ctx) -> None:
    check(ctx)
