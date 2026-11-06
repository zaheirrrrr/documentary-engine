"""Destockd: shot-level visual search over the FedFlix archive.

destockd.com cuts FedFlix films (US government films on the Internet Archive)
into single shots and indexes them with CLIP, so a search for "power plant
turbines" returns shots that show turbines, not films with a matching title.
Each shot is a short MP4 on Destockd's clip server, linked to its archive.org
item and, where known, its National Archives record.

Destockd is a free, independently hosted project with no published API; this
uses the same JSON endpoints as its web app. Be polite: results are cached on
disk, requests are spaced out, and only the first page of a search is read.
"""

from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any
from urllib.parse import quote

import requests

from ..util import PermanentError, http_get_json, retry, sha
from .archive_org import Film

BASE = "https://www.destockd.com/api"
SITE = "https://www.destockd.com"
LICENCE = "Public domain (US federal work via FedFlix)"


class Destockd:
    def __init__(self, session: requests.Session, cache_dir: Path, delay: float = 0.6):
        self.session = session
        self.cache = cache_dir / "destockd"
        self.cache.mkdir(parents=True, exist_ok=True)
        self.delay = delay
        self._last = 0.0

    @retry(attempts=3, base_delay=3)
    def _fetch(self, url: str, params: dict | None) -> Any:
        wait = self.delay - (time.monotonic() - self._last)
        if wait > 0:
            time.sleep(wait)
        self._last = time.monotonic()
        return http_get_json(self.session, url, params)

    def _get(self, path: str, params: dict | None = None) -> Any:
        key = self.cache / f"{sha(path + json.dumps(params or {}, sort_keys=True))}.json"
        if key.exists():
            return json.loads(key.read_text(encoding="utf-8"))
        data = self._fetch(f"{BASE}{path}", params)
        key.write_text(json.dumps(data), encoding="utf-8")
        return data

    def search(self, query: str) -> list[dict]:
        """Shots for a visual description, best match first (one page, ~48)."""
        if not query.strip():
            return []
        try:
            return list(self._get("/search", {"q": query, "page": 1}).get("results", []))
        except PermanentError:
            return []

    def film(self, result: dict, duration: float) -> Film:
        """A Film for one shot, with its archive.org source for the credit."""
        name, shot = str(result["film"]), str(result["shot"])
        detail = self._get(f"/shot/{quote(name, safe='')}/{quote(shot, safe='')}")
        archive_url = detail.get("archive_url") or ""
        identifier = archive_url.rstrip("/").rsplit("/", 1)[-1] if archive_url else f"destockd:{name}"
        return Film(
            identifier=identifier, title=name, year="", collection="FedFlix", licence=LICENCE,
            page_url=archive_url or f"{SITE}/#/shot/{quote(name)}/{quote(shot)}",
            video_url=str(result["clip"]), duration=duration,
            extra={"destockd": True, "shot": shot,
                   "shot_page": f"{SITE}/#/shot/{quote(name)}/{quote(shot)}",
                   "national_archives_url": detail.get("national_archives_url") or ""},
        )
