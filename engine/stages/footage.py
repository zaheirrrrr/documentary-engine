"""Stage: footage. Finds, checks and cuts public-domain film for every beat.

For each archival beat:
1. Search Destockd's shot-level visual index of FedFlix when the pack turns it
   on (footage.destockd), then archive.org (only licence-approved films
   survive). Destockd shots are used whole-shot, so only shots at least as
   long as the beat are taken.
2. For a few candidate films, pick a random window that avoids the opening
   titles and end credits, and grab a 4-frame contact sheet. Windows that are
   too dark, blown out or flat are dropped before anyone looks at them.
3. Claude looks at the contact sheets and picks the clip that fits the
   narration (rejecting title cards, cartoons, black frames, the pack's
   footage.avoid list and anything that contradicts the story).
4. The chosen windows are cut straight from archive.org, with no audio.

Beats longer than the pack's max clip length get several shots. If no footage
is found, the beat falls back to a card. If the vision check itself fails, the
stage stops (the per-beat checkpoint keeps finished beats): unvetted footage
is how wrong shots reach a render.

`reshoot()` replaces the shots of chosen beats: their current films are
blocked for that beat (footage_blocked.json) and the beat is searched again.
"""

from __future__ import annotations

import math
import random
import subprocess
from pathlib import Path

from PIL import Image

from ..sources.archive_org import Archive, Film
from ..sources.destockd import Destockd
from ..util import PermanentError, http_session, read_json, write_json

GENERIC = ["city street", "factory", "crowd", "railroad", "industry", "office workers"]


def make_archive(ctx) -> Archive:
    return Archive(http_session(ctx.settings.user_agent), ctx.settings.cache_dir, ctx.pack.get("footage.collections", []))


def _ffmpeg(args: list[str], timeout: int = 240) -> bool:
    proc = subprocess.run(["ffmpeg", "-y", "-v", "error", *args], capture_output=True, text=True, timeout=timeout)
    return proc.returncode == 0


def probe_duration(source: str) -> float:
    proc = subprocess.run(
        ["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "default=nw=1:nk=1", source],
        capture_output=True, text=True, timeout=120,
    )
    try:
        return float(proc.stdout.strip())
    except ValueError:
        return 0.0


def grab_frame(source: str, t: float, dest: Path) -> bool:
    return _ffmpeg(["-ss", f"{t:.2f}", "-i", source, "-frames:v", "1", "-vf", "scale=480:-2", str(dest)], timeout=120) and dest.exists()


def contact_sheet(frames: list[Path], dest: Path) -> Path:
    images = [Image.open(f).convert("RGB") for f in frames]
    h = min(i.height for i in images)
    images = [i.resize((int(i.width * h / i.height), h)) for i in images]
    sheet = Image.new("RGB", (sum(i.width for i in images) + 8 * (len(images) - 1), h), "white")
    x = 0
    for i in images:
        sheet.paste(i, (x, 0))
        x += i.width + 8
    sheet.save(dest, quality=85)
    return dest


def cut_clip(source: str, start: float, duration: float, dest: Path) -> bool:
    return _ffmpeg([
        "-ss", f"{start:.2f}", "-i", source, "-t", f"{duration:.2f}", "-an",
        "-vf", "scale='min(1280,iw)':-2,fps=30", "-c:v", "libx264", "-preset", "veryfast", "-crf", "20",
        "-pix_fmt", "yuv420p", str(dest),
    ], timeout=600) and dest.exists() and dest.stat().st_size > 1000


def exposure_problem(frames: list[Path], cfg: dict) -> str:
    """'' when the frames are watchable, else why not (too dark, blown out, flat)."""
    from PIL import ImageStat

    stats = [ImageStat.Stat(Image.open(f).convert("L")) for f in frames]
    mean = sum(st.mean[0] for st in stats) / len(stats)
    spread = sum(st.stddev[0] for st in stats) / len(stats)
    if mean < float(cfg.get("min_brightness", 38)):
        return f"too dark (brightness {mean:.0f})"
    if mean > float(cfg.get("max_brightness", 215)):
        return f"blown out (brightness {mean:.0f})"
    if spread < float(cfg.get("min_contrast", 22)):
        return f"flat or washed out (contrast {spread:.0f})"
    return ""


def sample_times(start: float, length: float) -> list[float]:
    """Four frames across the window, so a cut inside it is seen too."""
    return [start + 0.3, start + length / 3, start + 2 * length / 3, start + max(length - 0.3, 0.5)]


def load_blocked(ctx) -> dict[str, list[str]]:
    path = ctx.dir / "footage_blocked.json"
    return read_json(path) if path.exists() else {}


class Candidate:
    def __init__(self, film: Film, start: float, length: float, sheet: Path):
        self.film, self.start, self.length, self.sheet = film, start, length, sheet


def find_candidates(ctx, archive: Archive, query: str, length: float, beat_id: int, used: dict[str, int],
                    want: int, work: Path, blocked: frozenset[str] = frozenset()) -> list[Candidate]:
    cfg = ctx.pack.get("footage", {}) or {}
    head, tail = float(cfg.get("skip_head_fraction", 0.08)), float(cfg.get("skip_tail_fraction", 0.08))
    docs = archive.search(query, rows=30)
    rng = random.Random(f"{ctx.project_id}-{beat_id}-{query}")
    docs = sorted(docs, key=lambda d: (used.get(d["identifier"], 0), rng.random()))
    out: list[Candidate] = []
    for doc in docs:
        if len(out) >= want:
            break
        if doc.get("identifier") in blocked:
            continue
        try:
            film = archive.film(doc)
        except Exception as exc:  # noqa: BLE001
            ctx.log.info("footage: metadata failed for %s: %s", doc.get("identifier"), exc)
            continue
        if film is None:
            continue
        if film.duration <= 0:
            film.duration = probe_duration(film.video_url)
        usable_from, usable_to = film.duration * head, film.duration * (1 - tail) - length
        if usable_to <= usable_from:
            continue
        start = rng.uniform(usable_from, usable_to)
        tag = f"b{beat_id:03d}-{len(out)}"
        frames = []
        for j, t in enumerate(sample_times(start, length)):
            f = work / f"{tag}-f{j}.jpg"
            if grab_frame(film.video_url, t, f):
                frames.append(f)
        if len(frames) < 3:
            continue
        problem = exposure_problem(frames, cfg)
        if problem:
            ctx.log.info("footage: beat %s skips %s: %s", beat_id, film.identifier, problem)
            continue
        out.append(Candidate(film, start, length, contact_sheet(frames, work / f"{tag}-sheet.jpg")))
    return out


def find_destockd_candidates(ctx, ds: Destockd, query: str, length: float, beat_id: int, used: dict[str, int],
                             want: int, work: Path, blocked: frozenset[str] = frozenset()) -> list[Candidate]:
    cfg = ctx.pack.get("footage", {}) or {}
    out: list[Candidate] = []
    probes = 0
    for result in ds.search(query):
        if len(out) >= want or probes >= want * 3:
            break
        shot_key = f"destockd:{result.get('film')}/{result.get('shot')}"
        if used.get(shot_key) or shot_key in blocked:
            continue  # never show the same shot twice in one video, nor one rejected for this beat
        probes += 1
        try:
            duration = probe_duration(str(result["clip"]))
        except Exception:  # noqa: BLE001
            continue
        if duration < length + 0.2:
            continue
        start = max(0.1, (duration - length) / 2)
        tag = f"b{beat_id:03d}-d{len(out)}"
        frames = []
        for j, t in enumerate(sample_times(start, length)):
            f = work / f"{tag}-f{j}.jpg"
            if grab_frame(str(result["clip"]), t, f):
                frames.append(f)
        if len(frames) < 3:
            continue
        problem = exposure_problem(frames, cfg)
        if problem:
            ctx.log.info("footage: beat %s skips %s: %s", beat_id, shot_key, problem)
            continue
        try:
            film = ds.film(result, duration)
        except Exception as exc:  # noqa: BLE001
            ctx.log.info("footage: destockd details failed for %s: %s", shot_key, exc)
            continue
        film.extra["shot_key"] = shot_key
        out.append(Candidate(film, start, length, contact_sheet(frames, work / f"{tag}-sheet.jpg")))
    return out


def avoid_list(ctx, visual: dict) -> str:
    """The beat's own avoid list plus the pack's footage.avoid, which applies to every shot."""
    general = ctx.pack.get("footage.avoid", []) or []
    parts = [visual.get("avoid", "")] + ([general] if isinstance(general, str) else list(general))
    return ", ".join(p for p in parts if p)


def judge(ctx, beat: dict, cands: list[Candidate]) -> list[Candidate]:
    """Return usable candidates, best first."""
    if not cands:
        return []
    if not ctx.settings.vision_footage_check:
        return cands
    v = beat["visual"]
    prompt = ctx.pack.prompt("footage_pick", text=beat["text"], look_for=v.get("look_for", ""),
                             avoid=avoid_list(ctx, v), count=str(len(cands)))
    try:
        verdict = ctx.llm.complete_json(prompt, tier="fast", max_tokens=600, images=[c.sheet for c in cands])
    except Exception as exc:  # noqa: BLE001
        raise PermanentError(f"footage: the vision check failed ({exc}). Stopped so no unvetted footage is used; "
                             "fix it and run again (finished beats are kept).") from exc
    usable = [int(i) for i in verdict.get("usable", []) if 1 <= int(i) <= len(cands)]
    best = int(verdict.get("best", 0) or 0)
    if not 1 <= best <= len(cands):
        best = 0
    if best and best not in usable:
        usable.insert(0, best)
    elif best:
        usable.remove(best)
        usable.insert(0, best)
    return [cands[i - 1] for i in usable]


def run(ctx) -> None:
    beats = read_json(ctx.dir / "shotlist.json")["beats"]
    timing = {t["id"]: t for t in read_json(ctx.dir / "timing.json")["beats"]}
    cfg = ctx.pack.get("footage", {}) or {}
    max_clip = float(ctx.setting("max_clip_seconds", cfg.get("max_clip_seconds", 9)))
    min_clip = float(ctx.setting("min_clip_seconds", cfg.get("min_clip_seconds", 3)))
    want = int(cfg.get("candidates_per_beat", 4))

    archive = make_archive(ctx)
    ds = Destockd(http_session(ctx.settings.user_agent), ctx.settings.cache_dir) if cfg.get("destockd") else None
    work = ctx.dir / "footage" / "work"
    clips_dir = ctx.dir / "footage" / "clips"
    work.mkdir(parents=True, exist_ok=True)
    clips_dir.mkdir(parents=True, exist_ok=True)

    plan_path = ctx.dir / "footage.json"
    plan = read_json(plan_path) if plan_path.exists() else {}
    blocked_by_beat = load_blocked(ctx)
    used: dict[str, int] = {}
    credits: dict[str, str] = {}
    for entry in plan.values():
        for shot in entry.get("shots", []):
            used[shot["identifier"]] = used.get(shot["identifier"], 0) + 1
            if shot.get("shot_key"):
                used[shot["shot_key"]] = 1
            credits[shot["identifier"]] = shot["credit"]

    # With footage.backdrop_cards, quote and number beats get footage too, and
    # the render lays their text over it. A card beat without its own query
    # borrows the nearest earlier archival beat's.
    backdrops = bool(cfg.get("backdrop_cards"))
    last_archival: dict = {}
    for beat in beats:
        key = str(beat["id"])
        kind = beat["visual"].get("visual")
        if kind == "archival":
            last_archival = beat["visual"]
        elif not (backdrops and kind in ("quote", "number")):
            continue
        if key in plan and all(Path(s["path"]).exists() for s in plan[key].get("shots", [])) and plan[key].get("shots"):
            continue  # resumed run: this beat is already cut

        duration = timing[beat["id"]]["duration"]
        n = max(1, math.ceil(duration / max_clip))
        shot_len = max(min_clip, duration / n)
        own = beat["visual"] if beat["visual"].get("query") else last_archival
        queries = [own.get("query", ""), own.get("alt_query", ""), GENERIC[beat["id"] % len(GENERIC)]]

        blocked = frozenset(blocked_by_beat.get(key, []))
        chosen: list[Candidate] = []
        searches = [(q, src) for q in queries if q for src in (("destockd", "archive") if ds else ("archive",))]
        for q, src in searches:
            try:
                if src == "destockd":
                    cands = find_destockd_candidates(ctx, ds, q, shot_len, beat["id"], used, want, work, blocked)
                else:
                    cands = find_candidates(ctx, archive, q, shot_len, beat["id"], used, want, work, blocked)
            except PermanentError:
                raise
            except Exception as exc:  # noqa: BLE001
                ctx.log.warning("footage: %s search '%s' failed: %s", src, q, exc)
                continue
            chosen = judge(ctx, beat, cands)
            if chosen:
                break

        shots = []
        for k in range(n):
            if not chosen:
                break
            cand = chosen[k % len(chosen)]
            from_destockd = bool(cand.film.extra.get("destockd"))
            if from_destockd and k >= len(chosen):
                break  # a Destockd shot holds one clip; never repeat it
            start = cand.start + (k // len(chosen)) * (shot_len + 1.0)
            dest = clips_dir / f"b{beat['id']:03d}-{k}.mp4"
            ok = cut_clip(cand.film.video_url, start, shot_len, dest)
            if not ok and not from_destockd:
                ctx.log.info("footage: remote cut failed for %s; downloading film", cand.film.identifier)
                try:
                    ok = cut_clip(str(archive.local_copy(cand.film)), start, shot_len, dest)
                except Exception as exc:  # noqa: BLE001
                    ctx.log.warning("footage: download failed for %s: %s", cand.film.identifier, exc)
            if ok:
                shots.append({"path": str(dest), "identifier": cand.film.identifier, "start": round(start, 2),
                              "duration": round(shot_len, 2), "credit": cand.film.credit, "page": cand.film.page_url,
                              "shot_key": cand.film.extra.get("shot_key", ""),
                              "source": "destockd" if from_destockd else "archive.org"})
                used[cand.film.identifier] = used.get(cand.film.identifier, 0) + 1
                if from_destockd:
                    used[cand.film.extra["shot_key"]] = 1
                credits[cand.film.identifier] = cand.film.credit

        plan[key] = {"shots": shots, "fallback": not shots}
        if not shots:
            ctx.log.warning("footage: beat %s has no footage; it will use a card", key)
        write_json(plan_path, plan)  # checkpoint after every beat

    write_json(ctx.path("credits.json"), {"footage": sorted(credits.values()), "music": _music_credits(ctx)})
    fallbacks = sum(1 for e in plan.values() if e.get("fallback"))
    ctx.log.info("footage: %d beats cut, %d fell back to cards, %d films used", len(plan) - fallbacks, fallbacks, len(credits))


def reshoot(ctx, beat_ids: list[int]) -> None:
    """Replace the footage of these beats: block their current shots for that
    beat, drop their clips and any rendered segment, and search again."""
    plan_path = ctx.dir / "footage.json"
    plan = read_json(plan_path) if plan_path.exists() else {}
    blocked = load_blocked(ctx)
    for bid in beat_ids:
        key = str(bid)
        entry = plan.pop(key, None) or {}
        for shot in entry.get("shots", []):
            mark = shot.get("shot_key") or shot["identifier"]
            if mark not in blocked.setdefault(key, []):
                blocked[key].append(mark)
            Path(shot["path"]).unlink(missing_ok=True)
        (ctx.dir / "render" / "segments" / f"seg{bid:03d}.mp4").unlink(missing_ok=True)
    write_json(ctx.dir / "footage_blocked.json", blocked)
    write_json(plan_path, plan)
    run(ctx)


def _music_credits(ctx) -> list[str]:
    path = ctx.pack.path / str(ctx.pack.get("audio.music_dir", "music")) / "credits.txt"
    if not path.exists():
        return []
    return [line.strip() for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]
