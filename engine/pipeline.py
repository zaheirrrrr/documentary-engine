"""Stage runner with checkpoints and human approval gates.

Order of work for one video project:

  research -> outline -> script -> factcheck -> [GATE review_script]
  -> shotlist -> narration -> footage -> render -> package -> thumbnail
  -> qa -> [GATE review_final]

Each stage reads its inputs from the project folder and writes its outputs
there. A finished stage is never re-run unless you reset it, so a crash at
`render` resumes at `render`.
"""

from __future__ import annotations

import importlib
import logging
import traceback
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable

from .config import Pack, Settings
from .llm import LLM
from .state import State
from .util import PermanentError

GATE = "gate"

# (name, module or GATE, human description)
STAGES: list[tuple[str, str, str]] = [
    ("research", "engine.stages.research", "Build the research dossier from sources"),
    ("outline", "engine.stages.outline", "Hooks and chapter outline"),
    ("script", "engine.stages.script", "Write the narration script"),
    ("factcheck", "engine.stages.factcheck", "Check every claim against the dossier"),
    ("review_script", GATE, "YOU: read script.md, edit if needed, then approve"),
    ("shotlist", "engine.stages.shotlist", "Split script into timed visual beats"),
    ("narration", "engine.stages.narration", "Generate narration with ElevenLabs"),
    ("footage", "engine.stages.footage", "Find and cut public-domain footage per beat"),
    ("render", "engine.stages.render", "Assemble the video with FFmpeg"),
    ("package", "engine.stages.package", "Titles, description, chapters, credits, tags"),
    ("thumbnail", "engine.stages.thumbnail", "Three draft thumbnails from the best frames"),
    ("qa", "engine.stages.qa", "Automated quality checks"),
    ("review_final", GATE, "YOU: watch the video, check the upload pack, upload"),
]

STAGE_NAMES = [s[0] for s in STAGES]
STAGE_ATTEMPTS = 2  # automatic whole-stage retries on top of per-call retries


@dataclass
class Context:
    settings: Settings
    pack: Pack
    state: State
    llm: LLM
    project_id: int
    title: str
    angle: str
    dir: Path
    log: logging.Logger = field(default_factory=lambda: logging.getLogger("engine"))

    def path(self, *parts: str) -> Path:
        p = self.dir.joinpath(*parts)
        p.parent.mkdir(parents=True, exist_ok=True)
        return p

    def usage(self, service: str, units: float, unit: str, detail: str = "") -> None:
        self.state.log_usage(self.project_id, service, units, unit, detail)


def build_context(settings: Settings, state: State, project_id: int) -> Context:
    row = state.project(project_id)
    pack = Pack.load(row["pack"])
    project_dir = settings.projects_dir / f"{row['id']:04d}-{row['slug']}"
    project_dir.mkdir(parents=True, exist_ok=True)

    logger = logging.getLogger(f"engine.p{project_id}")
    if not any(isinstance(h, logging.FileHandler) for h in logger.handlers):
        fh = logging.FileHandler(project_dir / "pipeline.log", encoding="utf-8")
        fh.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(message)s"))
        logger.addHandler(fh)
    logger.setLevel(logging.INFO)

    llm = LLM(settings, usage_hook=lambda s, u, unit, d: state.log_usage(project_id, s, u, unit, d))
    return Context(settings, pack, state, llm, project_id, row["title"], row["angle"], project_dir, logger)


def _load_stage(module: str) -> Callable[[Context], None]:
    return importlib.import_module(module).run  # type: ignore[no-any-return]


def run(settings: Settings, state: State, project_id: int, only: str | None = None,
        echo: Callable[[str], None] = print) -> str:
    """Run a project forward until it finishes, fails, or reaches a gate.

    Returns the final project status.
    """
    ctx = build_context(settings, state, project_id)
    done = state.stages(project_id)
    state.set_project_status(project_id, "active")

    for name, module, desc in STAGES:
        if only and name != only:
            continue
        current = done.get(name)
        if current and current["status"] in {"done", "approved"}:
            continue

        if module == GATE:
            state.mark_stage(project_id, name, "waiting")
            state.set_project_status(project_id, "waiting")
            echo(f"⏸  Waiting for you at '{name}': {desc}")
            echo(f"   Folder: {ctx.dir}")
            echo(f"   When ready: de approve {project_id}")
            return "waiting"

        echo(f"▶  {name}: {desc}")
        stage_fn = _load_stage(module)
        last_error = ""
        succeeded = False
        for attempt in range(1, STAGE_ATTEMPTS + 1):
            try:
                ctx.log.info("stage %s attempt %d starting", name, attempt)
                stage_fn(ctx)
                state.mark_stage(project_id, name, "done")
                ctx.log.info("stage %s done", name)
                echo(f"✓  {name}")
                succeeded = True
                break
            except PermanentError as exc:
                last_error = str(exc)
                ctx.log.error("stage %s permanent failure: %s", name, exc)
                echo(f"!  {name}: {exc}")
                break
            except Exception as exc:  # noqa: BLE001
                last_error = f"{exc}\n{traceback.format_exc()}"
                ctx.log.error("stage %s attempt %d failed: %s", name, attempt, last_error)
                echo(f"!  {name} attempt {attempt} failed: {exc}")

        if not succeeded:
            state.mark_stage(project_id, name, "failed", last_error[-4000:])
            state.set_project_status(project_id, "failed")
            echo(f"✗  {name} failed. Details: {ctx.dir / 'pipeline.log'}")
            echo(f"   Fix the cause, then: de run {project_id}  (it resumes here)")
            return "failed"

        if only:
            return "active"

    state.set_project_status(project_id, "ready")
    echo("✓  All stages complete.")
    return "ready"


def approve(state: State, project_id: int) -> str | None:
    """Approve whichever gate the project is waiting at."""
    for name, module, _ in STAGES:
        row = state.stage(project_id, name)
        if module == GATE and row is not None and row["status"] == "waiting":
            state.mark_stage(project_id, name, "approved")
            state.set_project_status(project_id, "active")
            return name
    return None


def reset_from(state: State, project_id: int, stage: str) -> list[str]:
    """Forget `stage` and everything after it, so they re-run next time."""
    if stage not in STAGE_NAMES:
        raise ValueError(f"Unknown stage '{stage}'. Stages: {', '.join(STAGE_NAMES)}")
    cleared = STAGE_NAMES[STAGE_NAMES.index(stage):]
    for name in cleared:
        state.reset_stage(project_id, name)
    return cleared
