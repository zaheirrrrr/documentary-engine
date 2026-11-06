"""`de` command line.

Typical flow:
  de doctor                     check keys, tools and sources
  de discover --count 10        propose and score topics
  de topics                     list candidates
  de pick 3 --run               turn topic 3 into a project and run to the script review
  (edit script.md if you like)
  de approve 1 --run            approve the script, produce the video
  (watch review.html)
  de approve 1                  final approval; then upload by hand
  de published 1 https://youtu.be/...
"""

from __future__ import annotations

import argparse
import json
import logging
import shutil
import subprocess
import sys
from datetime import date
from pathlib import Path

import requests

from . import pipeline
from .config import ROOT, Pack, Settings
from .state import State
from .util import http_session, slugify, write_json


def _setup(args) -> tuple[Settings, State, Pack]:
    settings = Settings.load()
    if getattr(args, "pack", None):
        settings.pack_name = args.pack
    logging.basicConfig(level=logging.INFO if getattr(args, "verbose", False) else logging.WARNING,
                        format="%(levelname)s %(name)s: %(message)s")
    state = State(settings.db_path)
    return settings, state, Pack.load(settings.pack_name)


def _project_dir(settings: Settings, state: State, pid: int) -> Path:
    row = state.project(pid)
    return settings.projects_dir / f"{row['id']:04d}-{row['slug']}"


def cmd_doctor(args) -> int:
    settings, state, pack = _setup(args)
    ok = True

    def line(good: bool, msg: str) -> None:
        nonlocal ok
        ok &= good
        print(("✓ " if good else "✗ ") + msg)

    line(shutil.which("ffmpeg") is not None and shutil.which("ffprobe") is not None, "ffmpeg and ffprobe installed")
    if settings.llm_provider == "claude-code":
        line(shutil.which("claude") is not None, "Claude Code CLI found (LLM_PROVIDER=claude-code)")
    else:
        line(bool(settings.anthropic_api_key), "ANTHROPIC_API_KEY set (LLM_PROVIDER=api)")
    if settings.tts_provider == "voicestudio":
        try:
            r = requests.get(f"{settings.voicestudio_url}/health", timeout=10)
            line(r.ok, f"VoiceStudio running at {settings.voicestudio_url} ({r.status_code})")
            if r.ok:
                # Engine presets (e.g. Kokoro's am_michael) aren't in /v1/audio/voices, so
                # synthesize one word: it proves the voice, the engine and its licence at once.
                r = requests.post(f"{settings.voicestudio_url}/v1/audio/speech", timeout=300, json={
                    "model": settings.voicestudio_model, "voice": settings.voicestudio_voice,
                    "input": "Test.", "response_format": "wav"})
                ok_voice = r.ok and r.content[:4] == b"RIFF"
                why = "" if ok_voice else f": {r.text[:200]}"
                line(ok_voice, f"VoiceStudio speaks with voice '{settings.voicestudio_voice}' "
                               f"on engine '{settings.voicestudio_model}'{why}")
        except Exception as exc:  # noqa: BLE001
            line(False, f"VoiceStudio not reachable at {settings.voicestudio_url} (open the app): {exc.__class__.__name__}")
    else:
        line(bool(settings.elevenlabs_api_key), "ELEVENLABS_API_KEY set")
        line(bool(settings.elevenlabs_voice_id), "ELEVENLABS_VOICE_ID set")
    print(f"• Niche pack: {pack.name} ({pack.get('channel_name')})")
    music = pack.path / str(pack.get("audio.music_dir", "music"))
    tracks = [p for p in music.glob("*") if p.suffix.lower() in {".mp3", ".wav", ".m4a", ".ogg"}] if music.exists() else []
    print(f"• Music tracks: {len(tracks)} in {music} " + ("" if tracks else "(optional: videos render with voice only)"))

    session = http_session(settings.user_agent)
    checks = [
        ("Wikipedia", "https://en.wikipedia.org/w/api.php", {"action": "query", "meta": "siteinfo", "format": "json"}),
        ("Library of Congress newspapers", "https://www.loc.gov/collections/chronicling-america/", {"q": "steel", "fo": "json", "c": 1}),
    ]
    for name, url, params in checks:
        try:
            r = session.get(url, params=params, timeout=20)
            line(r.ok, f"{name} reachable ({r.status_code})")
        except Exception as exc:  # noqa: BLE001
            line(False, f"{name} unreachable: {exc}")
    from .sources.archive_org import Archive

    archive = Archive(session, settings.cache_dir, [])
    for col in pack.get("footage.collections", []):
        try:
            archive.collections = {col["id"]: bool(col.get("trusted"))}
            n = archive.count("*:*")
            line(n > 0, f"archive.org collection '{col['id']}': {n:,} films")
        except Exception as exc:  # noqa: BLE001
            line(False, f"archive.org collection '{col['id']}' failed: {exc}")
    if settings.elevenlabs_api_key and settings.elevenlabs_voice_id:
        try:
            r = session.get(f"https://api.elevenlabs.io/v1/voices/{settings.elevenlabs_voice_id}",
                            headers={"xi-api-key": settings.elevenlabs_api_key}, timeout=20)
            line(r.ok, f"ElevenLabs voice found ({r.json().get('name', r.status_code) if r.ok else r.status_code})")
        except Exception as exc:  # noqa: BLE001
            line(False, f"ElevenLabs check failed: {exc}")
    print("\nAll good." if ok else "\nFix the ✗ items above, then run `de doctor` again.")
    return 0 if ok else 1


def cmd_trends(args) -> int:
    settings, state, pack = _setup(args)
    from . import trends

    print("Researching what makes people click (outlier titles, thumbnails, topics)...")
    path = trends.run(settings, state, pack)
    print(f"\nPackaging library saved: {path}")
    print("New videos now build titles and thumbnails from it; `de discover` uses its topic themes.")
    return 0


def cmd_titles(args) -> int:
    """Check your own title ideas against the title checker."""
    from .titles import check_title

    for t in args.titles:
        r = check_title(t)
        print(f"{r.score:>3}  {'OK ' if r.ok else 'NO '} {t}")
        for h in r.hard:
            print(f"       HARD: {h}")
        for s_ in r.soft:
            print(f"       soft: {s_}")
    return 0


def cmd_discover(args) -> int:
    settings, state, pack = _setup(args)
    from .discover import discover

    from .trends import library_age_days

    age = library_age_days(settings)
    limit = int(pack.get("packaging.refresh_days", 14))
    if age is None:
        print("Tip: run `de trends` first so topics and titles use real outlier data.\n")
    elif age > limit:
        print(f"Tip: the packaging library is {age} days old; refresh it with `de trends`.\n")
    ids = discover(settings, state, pack, args.count, args.category, args.focus or "")
    print(f"\n{len(ids)} topics added. See them with `de topics`; start one with `de pick <id> --run`.")
    return 0


def cmd_topics(args) -> int:
    _, state, _ = _setup(args)
    rows = state.topics(None if args.all else "candidate")
    if not rows:
        print("No topics. Run `de discover`.")
        return 0
    for r in rows:
        d = json.loads(r["details"])
        print(f"#{r['id']:<4} [{r['score']:4.1f}] {r['title']}  ({r['category']}, {r['status']})")
        if args.verbose or args.detail:
            print(f"       {r['angle']}")
            print(f"       views/yr {d.get('yearly_views', 0):,} · films {d.get('footage_hits', 0)} · era {d.get('era', '')}")
            if d.get("competition"):
                print(f"       competition: {d['competition']}")
    return 0


def _create_project(settings: Settings, state: State, pack: Pack, title: str, angle: str, topic: dict) -> int:
    base = slugify(title)
    slug, n = base, 2
    existing = {p["slug"] for p in state.projects()}
    while slug in existing:
        slug, n = f"{base}-{n}", n + 1
    pid = state.create_project(slug, title, angle, pack.name)
    write_json(_project_dir(settings, state, pid) / "topic.json", topic)
    return pid


def cmd_pick(args) -> int:
    settings, state, pack = _setup(args)
    row = state.topic(args.topic_id)
    if row is None:
        print(f"No topic #{args.topic_id}")
        return 1
    details = json.loads(row["details"])
    pid = _create_project(settings, state, pack, row["title"], row["angle"], details)
    state.set_topic_status(row["id"], "used", pid)
    print(f"Project {pid} created: {_project_dir(settings, state, pid)}")
    if args.run:
        return 1 if pipeline.run(settings, state, pid) == "failed" else 0
    return 0


def cmd_reject(args) -> int:
    _, state, _ = _setup(args)
    state.set_topic_status(args.topic_id, "rejected")
    print(f"Topic #{args.topic_id} rejected.")
    return 0


def cmd_new(args) -> int:
    settings, state, pack = _setup(args)
    topic = {"title": args.title, "angle": args.angle or "", "wikipedia_title": args.wikipedia or "", "era": args.era or ""}
    pid = _create_project(settings, state, pack, args.title, args.angle or "", topic)
    print(f"Project {pid} created: {_project_dir(settings, state, pid)}")
    if args.run:
        pipeline.run(settings, state, pid)
    return 0


def cmd_shorts(args) -> int:
    """Plan Shorts from a long video's dossier and create one project per Short."""
    settings, state, pack = _setup(args)
    parent = state.project(args.project_id)
    parent_dir = _project_dir(settings, state, parent["id"])
    if not (parent_dir / "dossier.json").exists():
        print("That project has no dossier yet. Run it past the research stage first.")
        return 1
    from .llm import LLM

    llm = LLM(settings, usage_hook=lambda s, u, unit, d: state.log_usage(parent["id"], s, u, unit, d))
    count = args.count or int(pack.get("shorts.per_video", 3))
    dossier = json.loads((parent_dir / "dossier.json").read_text(encoding="utf-8"))
    slim = {k: v for k, v in dossier.items() if k not in ("source_shelf", "topic")}
    plan = llm.complete_json(pack.prompt("short_angles", title=parent["title"], count=str(count),
                                         dossier=json.dumps(slim, indent=1, ensure_ascii=False)),
                             tier="deep", max_tokens=3000)
    created = []
    for s in plan.get("shorts", [])[:count]:
        title = f"Short: {s.get('title', parent['title'])}"
        angle = f"{s.get('angle', '')} Hook idea: {s.get('hook', '')}".strip()
        topic = {"title": title, "angle": angle, "parent_id": parent["id"], "parent_title": parent["title"]}
        pid = _create_project(settings, state, pack, title, angle, topic)
        d = _project_dir(settings, state, pid)
        write_json(d / "format.json", {"format": "short", "parent": parent["id"]})
        shutil.copy2(parent_dir / "dossier.json", d / "dossier.json")
        if (parent_dir / "sources.json").exists():
            shutil.copy2(parent_dir / "sources.json", d / "sources.json")
        created.append(pid)
        print(f"Short project {pid}: {title}")
    if args.run:
        for pid in created:
            pipeline.run(settings, state, pid)
    else:
        print("Run each with `de run <id>`; each stops at the script review like a long video.")
    return 0


def cmd_run(args) -> int:
    settings, state, _ = _setup(args)
    result = pipeline.run(settings, state, args.project_id, only=args.stage)
    return 1 if result == "failed" else 0


def cmd_status(args) -> int:
    settings, state, _ = _setup(args)
    projects = [state.project(args.project_id)] if args.project_id else state.projects()
    if not projects:
        print("No projects yet.")
        return 0
    for p in projects:
        print(f"#{p['id']} {p['title']}  [{p['status']}]" + (f"  {p['published_url']}" if p["published_url"] else ""))
        if args.project_id:
            runs = state.stages(p["id"])
            for name, _, desc in pipeline.STAGES:
                r = runs.get(name)
                mark = {"done": "✓", "approved": "✓", "waiting": "⏸", "failed": "✗"}.get(r["status"], "·") if r else "·"
                extra = f"  (attempts {r['attempts']})" if r and r["attempts"] > 1 else ""
                print(f"   {mark} {name:<14} {desc}{extra}")
                if r and r["status"] == "failed" and r["error"]:
                    print(f"       {r['error'].splitlines()[0][:200]}")
            print(f"   Folder: {_project_dir(settings, state, p['id'])}")
    return 0


def cmd_approve(args) -> int:
    settings, state, _ = _setup(args)
    gate = pipeline.approve(state, args.project_id)
    if gate is None:
        print("Nothing is waiting for approval on this project. See `de status <id>`.")
        return 1
    print(f"Approved '{gate}'.")
    if gate == "review_final":
        print("Upload final.mp4 by hand using upload_pack.md, then run: de published "
              f"{args.project_id} <youtube-url>")
        state.set_project_status(args.project_id, "ready")
        return 0
    if args.run:
        return 1 if pipeline.run(settings, state, args.project_id) == "failed" else 0
    print(f"Continue with: de run {args.project_id}")
    return 0


def cmd_redo(args) -> int:
    settings, state, _ = _setup(args)
    cleared = pipeline.reset_from(state, args.project_id, args.from_stage)
    project_dir = _project_dir(settings, state, args.project_id)
    if "render" in cleared and (args.fresh or "footage" in cleared):
        shutil.rmtree(project_dir / "render", ignore_errors=True)  # otherwise finished segments are reused
    if "footage" in cleared:
        (project_dir / "footage.json").unlink(missing_ok=True)
        shutil.rmtree(project_dir / "footage" / "clips", ignore_errors=True)
    print(f"Reset: {', '.join(cleared)}")
    if args.run:
        return 1 if pipeline.run(settings, state, args.project_id) == "failed" else 0
    return 0


def cmd_reshoot(args) -> int:
    from .stages import footage, shotcheck

    settings, state, _ = _setup(args)
    ctx = pipeline.build_context(settings, state, args.project_id)
    footage.reshoot(ctx, args.beats)
    results = shotcheck.check(ctx, only=args.beats, rounds=0)
    for b in args.beats:
        r = results.get(str(b), {})
        print(f"beat {b}: {'OK' if r.get('ok') else r.get('problem', 'no result')}")
    print(f"Look again: {ctx.dir / 'shotcheck.html'}")
    rendered = state.stage(args.project_id, "render")
    if rendered is not None and rendered["status"] == "done":
        print(f"Only these beats' segments were removed. Re-render with: de redo {args.project_id} --from render --run")
    return 0


def cmd_review(args) -> int:
    settings, state, _ = _setup(args)
    d = _project_dir(settings, state, args.project_id)
    page = d / "review.html"
    target = page if page.exists() else d / "script.md"
    print(target)
    if args.open:
        opener = "open" if sys.platform == "darwin" else "xdg-open" if sys.platform.startswith("linux") else "start"
        subprocess.run([opener, str(target)], check=False, shell=sys.platform == "win32")
    return 0


def cmd_published(args) -> int:
    settings, state, _ = _setup(args)
    state.set_project_status(args.project_id, "published", args.url)
    notes = _project_dir(settings, state, args.project_id) / "notes.md"
    with notes.open("a", encoding="utf-8") as fh:
        fh.write(f"- {date.today().isoformat()}: published at {args.url}\n")
    print("Marked as published. Add lessons later with: de notes "
          f"{args.project_id} \"what worked, what to change\"")
    return 0


def cmd_notes(args) -> int:
    settings, state, _ = _setup(args)
    d = _project_dir(settings, state, args.project_id)
    with (d / "notes.md").open("a", encoding="utf-8") as fh:
        fh.write(f"- {date.today().isoformat()}: {args.text}\n")
    from .dossier import render

    p = state.project(args.project_id)
    render(d, p["title"], p["angle"])
    print("Note added to the dossier.")
    return 0


def cmd_usage(args) -> int:
    _, state, _ = _setup(args)
    rows = state.usage_summary(args.project_id)
    if not rows:
        print("No usage recorded yet.")
    for r in rows:
        print(f"{r['service']:<12} {r['total']:>14,.0f} {r['unit']}")
    return 0


def cmd_new_pack(args) -> int:
    src = ROOT / "packs" / args.source
    dst = ROOT / "packs" / args.name
    if dst.exists():
        print(f"{dst} already exists")
        return 1
    shutil.copytree(src, dst, ignore=shutil.ignore_patterns("music", "fonts"))
    text = (dst / "pack.yaml").read_text(encoding="utf-8").replace(f"pack: {args.source}", f"pack: {args.name}")
    (dst / "pack.yaml").write_text(text, encoding="utf-8")
    print(f"New pack at {dst}. Edit pack.yaml, channel_brief.md and style_guide.md, then set DE_PACK={args.name}.")
    return 0


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(prog="de", description="Documentary Engine")
    p.add_argument("--pack", help="niche pack to use (default: DE_PACK in .env)")
    p.add_argument("-v", "--verbose", action="store_true")
    sub = p.add_subparsers(dest="cmd", required=True)

    sub.add_parser("doctor", help="check keys, tools and sources").set_defaults(fn=cmd_doctor)

    sub.add_parser("trends", help="research outlier titles, thumbnails and topics across niches").set_defaults(fn=cmd_trends)

    s = sub.add_parser("titles", help="score title ideas with the title checker")
    s.add_argument("titles", nargs="+")
    s.set_defaults(fn=cmd_titles)

    s = sub.add_parser("discover", help="propose and score new topics")
    s.add_argument("--count", type=int, default=10)
    s.add_argument("--category")
    s.add_argument("--focus", help="steer this batch, e.g. 'railroads' or 'retail brands'")
    s.set_defaults(fn=cmd_discover)

    s = sub.add_parser("topics", help="list topic candidates")
    s.add_argument("--all", action="store_true")
    s.add_argument("--detail", action="store_true")
    s.set_defaults(fn=cmd_topics)

    s = sub.add_parser("pick", help="turn a topic into a project")
    s.add_argument("topic_id", type=int)
    s.add_argument("--run", action="store_true")
    s.set_defaults(fn=cmd_pick)

    s = sub.add_parser("reject", help="reject a topic")
    s.add_argument("topic_id", type=int)
    s.set_defaults(fn=cmd_reject)

    s = sub.add_parser("new", help="start a project from your own topic")
    s.add_argument("title")
    s.add_argument("--angle")
    s.add_argument("--wikipedia", help="exact Wikipedia article title")
    s.add_argument("--era", help="e.g. 1920-1955")
    s.add_argument("--run", action="store_true")
    s.set_defaults(fn=cmd_new)

    s = sub.add_parser("shorts", help="plan vertical Shorts from a long video's research")
    s.add_argument("project_id", type=int)
    s.add_argument("--count", type=int)
    s.add_argument("--run", action="store_true")
    s.set_defaults(fn=cmd_shorts)

    s = sub.add_parser("run", help="run a project forward (resumes where it stopped)")
    s.add_argument("project_id", type=int)
    s.add_argument("--stage", choices=pipeline.STAGE_NAMES)
    s.set_defaults(fn=cmd_run)

    s = sub.add_parser("status", help="show projects or one project's stages")
    s.add_argument("project_id", type=int, nargs="?")
    s.set_defaults(fn=cmd_status)

    s = sub.add_parser("approve", help="approve the gate a project is waiting at")
    s.add_argument("project_id", type=int)
    s.add_argument("--run", action="store_true")
    s.set_defaults(fn=cmd_approve)

    s = sub.add_parser("redo", help="re-run from a stage onward")
    s.add_argument("project_id", type=int)
    s.add_argument("--from", dest="from_stage", required=True, choices=pipeline.STAGE_NAMES)
    s.add_argument("--fresh", action="store_true", help="also delete rendered segments (e.g. after a grade change)")
    s.add_argument("--run", action="store_true")
    s.set_defaults(fn=cmd_redo)

    s = sub.add_parser("reshoot", help="replace the footage of some beats and re-check them")
    s.add_argument("project_id", type=int)
    s.add_argument("beats", type=int, nargs="+")
    s.set_defaults(fn=cmd_reshoot)

    s = sub.add_parser("review", help="path to the review page")
    s.add_argument("project_id", type=int)
    s.add_argument("--open", action="store_true")
    s.set_defaults(fn=cmd_review)

    s = sub.add_parser("published", help="mark a project as uploaded")
    s.add_argument("project_id", type=int)
    s.add_argument("url")
    s.set_defaults(fn=cmd_published)

    s = sub.add_parser("notes", help="add a post-release note to the dossier")
    s.add_argument("project_id", type=int)
    s.add_argument("text")
    s.set_defaults(fn=cmd_notes)

    s = sub.add_parser("usage", help="API usage totals")
    s.add_argument("project_id", type=int, nargs="?")
    s.set_defaults(fn=cmd_usage)

    s = sub.add_parser("new-pack", help="copy a niche pack to start a new niche")
    s.add_argument("name")
    s.add_argument("--source", default="us-rise-and-fall")
    s.set_defaults(fn=cmd_new_pack)

    args = p.parse_args(argv)
    return int(args.fn(args) or 0)


if __name__ == "__main__":
    raise SystemExit(main())
