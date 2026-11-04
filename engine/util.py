"""Shared helpers: retries, JSON extraction, slugs, logging, HTTP."""

from __future__ import annotations

import functools
import hashlib
import json
import logging
import random
import re
import time
import unicodedata
from pathlib import Path
from typing import Any, Callable, TypeVar

import requests

T = TypeVar("T")

log = logging.getLogger("engine")


class PermanentError(Exception):
    """An error that retrying will not fix (bad key, missing file, policy)."""


def retry(attempts: int = 4, base_delay: float = 2.0, max_delay: float = 60.0) -> Callable:
    """Exponential backoff with jitter. PermanentError is never retried."""

    def decorator(fn: Callable[..., T]) -> Callable[..., T]:
        @functools.wraps(fn)
        def wrapper(*args: Any, **kwargs: Any) -> T:
            for attempt in range(1, attempts + 1):
                try:
                    return fn(*args, **kwargs)
                except PermanentError:
                    raise
                except Exception as exc:  # noqa: BLE001
                    if attempt == attempts:
                        raise
                    delay = min(max_delay, base_delay * 2 ** (attempt - 1)) * (0.75 + random.random() / 2)
                    log.warning("%s failed (%s); retry %d/%d in %.1fs", fn.__name__, exc, attempt, attempts - 1, delay)
                    time.sleep(delay)
            raise RuntimeError("unreachable")

        return wrapper

    return decorator


def slugify(text: str, max_len: int = 60) -> str:
    text = unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode()
    text = re.sub(r"[^a-zA-Z0-9]+", "-", text).strip("-").lower()
    return text[:max_len].rstrip("-") or "untitled"


def extract_json(text: str) -> Any:
    """Pull the first JSON object/array out of a model reply.

    Accepts ```json fences, <json> tags, or bare JSON surrounded by prose.
    """
    for pattern in (r"<json>\s*(.*?)\s*</json>", r"```(?:json)?\s*(.*?)\s*```"):
        match = re.search(pattern, text, re.DOTALL)
        if match:
            try:
                return json.loads(match.group(1))
            except json.JSONDecodeError:
                pass
    starts = [i for i in (text.find("{"), text.find("[")) if i != -1]
    if not starts:
        raise ValueError("No JSON found in model output")
    start = min(starts)
    closer = "}" if text[start] == "{" else "]"
    end = text.rfind(closer)
    if end <= start:
        raise ValueError("Unterminated JSON in model output")
    return json.loads(text[start : end + 1])


def sha(text: str, length: int = 16) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()[:length]


def write_json(path: Path, data: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")
    tmp.replace(path)


def read_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def write_text(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(text, encoding="utf-8")
    tmp.replace(path)


def http_session(user_agent: str) -> requests.Session:
    s = requests.Session()
    s.headers["User-Agent"] = user_agent
    return s


@retry(attempts=4)
def http_get_json(session: requests.Session, url: str, params: dict | None = None, timeout: int = 30) -> Any:
    r = session.get(url, params=params, timeout=timeout)
    if r.status_code in (401, 403, 404):
        raise PermanentError(f"GET {url} -> {r.status_code}")
    r.raise_for_status()
    return r.json()


@retry(attempts=4)
def http_download(session: requests.Session, url: str, dest: Path, timeout: int = 120) -> Path:
    """Stream a file to disk atomically; skips if already cached."""
    if dest.exists() and dest.stat().st_size > 0:
        return dest
    dest.parent.mkdir(parents=True, exist_ok=True)
    tmp = dest.with_suffix(dest.suffix + ".part")
    with session.get(url, stream=True, timeout=timeout) as r:
        if r.status_code in (401, 403, 404):
            raise PermanentError(f"GET {url} -> {r.status_code}")
        r.raise_for_status()
        with tmp.open("wb") as fh:
            for chunk in r.iter_content(chunk_size=1 << 20):
                fh.write(chunk)
    tmp.replace(dest)
    return dest


def words(text: str) -> int:
    return len(re.findall(r"\b[\w'’-]+\b", text))


def normalise_for_match(text: str) -> str:
    text = unicodedata.normalize("NFKD", text).lower()
    text = re.sub(r"[“”\"'‘’`]", "", text)
    text = re.sub(r"[^a-z0-9 ]+", " ", text)
    return re.sub(r"\s+", " ", text).strip()
