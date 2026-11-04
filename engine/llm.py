"""Claude access. Two interchangeable providers:

- "api": the Anthropic API with an API key (server web search + vision).
- "claude-code": the `claude` CLI in headless mode, which runs on a Claude
  Code subscription instead of API billing.

Stages only call LLM.complete / LLM.complete_json, so the provider can be
swapped in .env without touching any stage.
"""

from __future__ import annotations

import base64
import json
import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable

from .config import Settings
from .util import PermanentError, extract_json, log, retry


@dataclass
class Reply:
    text: str
    input_tokens: int = 0
    output_tokens: int = 0
    web_searches: int = 0


class LLM:
    def __init__(self, settings: Settings, usage_hook: Callable[[str, float, str, str], None] | None = None):
        self.settings = settings
        self.usage_hook = usage_hook
        self._client = None

    # ---- public API ---------------------------------------------------
    def complete(
        self,
        prompt: str,
        *,
        system: str = "",
        tier: str = "deep",
        max_tokens: int = 8000,
        web_search: bool = False,
        images: list[Path] | None = None,
    ) -> str:
        model = self.settings.model_deep if tier == "deep" else self.settings.model_fast
        if self.settings.llm_provider == "claude-code":
            reply = self._claude_code(prompt, system, model, web_search, images)
        else:
            reply = self._api(prompt, system, model, max_tokens, web_search and self.settings.web_search, images)
        if self.usage_hook:
            self.usage_hook("claude", reply.input_tokens, "input_tokens", model)
            self.usage_hook("claude", reply.output_tokens, "output_tokens", model)
            if reply.web_searches:
                self.usage_hook("claude", reply.web_searches, "web_searches", model)
        return reply.text

    def complete_json(self, prompt: str, **kwargs: Any) -> Any:
        """Ask for JSON; if the reply does not parse, ask once more to repair it."""
        text = self.complete(prompt, **kwargs)
        try:
            return extract_json(text)
        except (ValueError, json.JSONDecodeError) as exc:
            log.warning("JSON parse failed (%s); asking for a repair", exc)
            repair = (
                "The following reply was meant to contain one valid JSON value but does not parse.\n"
                "Return ONLY the corrected JSON inside <json></json> tags, with no other text.\n\n"
                f"<reply>\n{text}\n</reply>"
            )
            fixed = self.complete(repair, tier="fast", max_tokens=kwargs.get("max_tokens", 8000))
            return extract_json(fixed)

    # ---- providers ----------------------------------------------------
    @retry(attempts=4, base_delay=5)
    def _api(
        self, prompt: str, system: str, model: str, max_tokens: int, web_search: bool, images: list[Path] | None
    ) -> Reply:
        if not self.settings.anthropic_api_key:
            raise PermanentError("ANTHROPIC_API_KEY is not set (or set LLM_PROVIDER=claude-code)")
        import anthropic

        if self._client is None:
            self._client = anthropic.Anthropic(api_key=self.settings.anthropic_api_key, max_retries=2)

        content: list[dict[str, Any]] = []
        for image in images or []:
            media = "image/png" if image.suffix.lower() == ".png" else "image/jpeg"
            content.append(
                {
                    "type": "image",
                    "source": {"type": "base64", "media_type": media, "data": base64.b64encode(image.read_bytes()).decode()},
                }
            )
        content.append({"type": "text", "text": prompt})

        params: dict[str, Any] = {
            "model": model,
            "max_tokens": max_tokens,
            "messages": [{"role": "user", "content": content}],
        }
        if system:
            params["system"] = system
        if web_search:
            params["tools"] = [{"type": "web_search_20250305", "name": "web_search", "max_uses": 8}]

        try:
            with self._client.messages.stream(**params) as stream:
                message = stream.get_final_message()
        except anthropic.AuthenticationError as exc:
            raise PermanentError(f"Anthropic rejected the API key: {exc}") from exc
        except anthropic.BadRequestError as exc:
            raise PermanentError(f"Anthropic rejected the request: {exc}") from exc

        text = "".join(block.text for block in message.content if getattr(block, "type", "") == "text")
        searches = 0
        server_use = getattr(message.usage, "server_tool_use", None)
        if server_use is not None:
            searches = getattr(server_use, "web_search_requests", 0) or 0
        return Reply(
            text=text,
            input_tokens=message.usage.input_tokens,
            output_tokens=message.usage.output_tokens,
            web_searches=searches,
        )

    @retry(attempts=3, base_delay=10)
    def _claude_code(
        self, prompt: str, system: str, model: str, web_search: bool, images: list[Path] | None
    ) -> Reply:
        exe = shutil.which("claude")
        if not exe:
            raise PermanentError("LLM_PROVIDER=claude-code but the `claude` CLI is not on PATH")
        full_prompt = prompt
        tools: list[str] = []
        if images:
            listing = "\n".join(f"- {p.resolve()}" for p in images)
            full_prompt = f"Look at these image files with the Read tool before answering:\n{listing}\n\n{prompt}"
            tools.append("Read")
        if web_search:
            tools += ["WebSearch", "WebFetch"]
        cmd = [exe, "-p", full_prompt, "--output-format", "json", "--model", model]
        if system:
            cmd += ["--append-system-prompt", system]
        if tools:
            cmd += ["--allowedTools", ",".join(tools)]
        proc = subprocess.run(cmd, capture_output=True, text=True, timeout=1800)
        if proc.returncode != 0:
            raise RuntimeError(f"claude CLI failed: {proc.stderr.strip()[:500]}")
        payload = json.loads(proc.stdout)
        if payload.get("is_error"):
            raise RuntimeError(f"claude CLI error: {payload.get('result', '')[:500]}")
        usage = payload.get("usage", {})
        return Reply(
            text=payload.get("result", ""),
            input_tokens=usage.get("input_tokens", 0),
            output_tokens=usage.get("output_tokens", 0),
        )
