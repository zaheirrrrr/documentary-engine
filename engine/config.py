"""Settings (from environment / .env) and niche pack loading."""

from __future__ import annotations

import os
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

ROOT = Path(__file__).resolve().parent.parent


def load_dotenv(path: Path) -> None:
    """Minimal .env loader. Existing environment variables always win."""
    if not path.exists():
        return
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        key, value = key.strip(), value.strip().strip('"').strip("'")
        os.environ.setdefault(key, value)


def _env(name: str, default: str = "") -> str:
    return os.environ.get(name, default).strip()


def _env_bool(name: str, default: bool) -> bool:
    raw = _env(name)
    if not raw:
        return default
    return raw.lower() in {"1", "true", "yes", "on"}


@dataclass
class Settings:
    workspace: Path
    pack_name: str
    llm_provider: str  # "api" or "claude-code"
    anthropic_api_key: str
    model_deep: str
    model_fast: str
    web_search: bool
    vision_footage_check: bool
    elevenlabs_api_key: str
    elevenlabs_voice_id: str
    elevenlabs_model: str
    user_agent: str
    youtube_api_key: str = ""
    tts_provider: str = "elevenlabs"  # "elevenlabs" or "voicestudio"
    voicestudio_url: str = "http://127.0.0.1:3900"
    voicestudio_voice: str = "default"
    voicestudio_model: str = "mlx-audio"

    @classmethod
    def load(cls) -> "Settings":
        load_dotenv(ROOT / ".env")
        workspace = Path(_env("DE_WORKSPACE", str(ROOT / "workspace"))).expanduser()
        return cls(
            workspace=workspace,
            pack_name=_env("DE_PACK", "us-rise-and-fall"),
            llm_provider=_env("LLM_PROVIDER", "api"),
            anthropic_api_key=_env("ANTHROPIC_API_KEY"),
            model_deep=_env("MODEL_DEEP", "claude-opus-5-5"),
            model_fast=_env("MODEL_FAST", "claude-sonnet-5-5"),
            web_search=_env_bool("WEB_SEARCH", True),
            vision_footage_check=_env_bool("VISION_FOOTAGE_CHECK", True),
            elevenlabs_api_key=_env("ELEVENLABS_API_KEY"),
            elevenlabs_voice_id=_env("ELEVENLABS_VOICE_ID"),
            elevenlabs_model=_env("ELEVENLABS_MODEL", "eleven_multilingual_v2"),
            user_agent=_env("DE_USER_AGENT", "documentary-engine/0.1"),
            youtube_api_key=_env("YOUTUBE_API_KEY"),
            tts_provider=_env("TTS_PROVIDER", "elevenlabs").lower(),
            voicestudio_url=_env("VOICESTUDIO_URL", "http://127.0.0.1:3900").rstrip("/"),
            voicestudio_voice=_env("VOICESTUDIO_VOICE", "default"),
            voicestudio_model=_env("VOICESTUDIO_MODEL", "mlx-audio"),
        )

    @property
    def research_dir(self) -> Path:
        return self.workspace / "research"

    @property
    def db_path(self) -> Path:
        return self.workspace / "engine.db"

    @property
    def projects_dir(self) -> Path:
        return self.workspace / "projects"

    @property
    def cache_dir(self) -> Path:
        return self.workspace / "cache"


@dataclass
class Pack:
    """A niche pack: everything that makes a channel what it is."""

    name: str
    path: Path
    data: dict[str, Any] = field(default_factory=dict)

    @classmethod
    def load(cls, name: str) -> "Pack":
        path = ROOT / "packs" / name
        manifest = path / "pack.yaml"
        if not manifest.exists():
            raise FileNotFoundError(f"Niche pack '{name}' not found at {manifest}")
        data = yaml.safe_load(manifest.read_text(encoding="utf-8")) or {}
        return cls(name=name, path=path, data=data)

    def get(self, dotted: str, default: Any = None) -> Any:
        node: Any = self.data
        for part in dotted.split("."):
            if not isinstance(node, dict) or part not in node:
                return default
            node = node[part]
        return node

    def text(self, relative: str) -> str:
        return (self.path / relative).read_text(encoding="utf-8")

    def prompt(self, name: str, **variables: Any) -> str:
        """Load packs/<name>/prompts/<name>.md and fill {{variables}}.

        Double-brace placeholders keep literal JSON braces in prompts safe.
        Every prompt also receives the channel brief and style guide.
        """
        template = self.text(f"prompts/{name}.md")
        base = {
            "channel_brief": self.text("channel_brief.md"),
            "style_guide": self.text("style_guide.md"),
            "dossier_template": self.text("dossier_template.md"),
        }
        base.update({k: v for k, v in variables.items()})

        def replace(match: re.Match[str]) -> str:
            key = match.group(1).strip()
            if key not in base:
                raise KeyError(f"Prompt '{name}' needs variable '{key}'")
            value = base[key]
            return value if isinstance(value, str) else yaml.safe_dump(value, sort_keys=False, allow_unicode=True)

        return re.sub(r"\{\{\s*([a-zA-Z0-9_]+)\s*\}\}", replace, template)
