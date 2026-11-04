"""archive.org public-domain film search, licence filtering and clip access.

Clips are cut straight from archive.org with HTTP range requests (ffmpeg
seeks inside the remote file), so a 40-minute film is never downloaded just
to use six seconds of it. If remote seeking fails, the film is downloaded once
into the cache and reused.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any
from urllib.parse import quote

import requests

from ..util import http_download, http_get_json, log, read_json, slugify, write_json

SEARCH = "https://archive.org/advancedsearch.php"
METADATA = "https://archive.org/metadata/{id}"
DOWNLOAD = "https://archive.org/download/{id}/{name}"

ACCEPTED_LICENCES = ("publicdomain", "/zero/", "/licenses/by/", "/licenses/by-sa/", "/mark/")
REJECTED_LICENCE_PARTS = ("-nc", "-nd", "/nc", "/nd")
VIDEO_FORMAT_PREFERENCE = ("h.264", "h.264 hd", "mpeg4", "512kb mpeg4")


@dataclass
class Film:
    identifier: str
    title: str
    year: str
    collection: str
    licence: str
    page_url: str
    video_url: str = ""
    duration: float = 0.0
    width: int = 0
    height: int = 0
    extra: dict[str, Any] = field(default_factory=dict)

    @property
    def credit(self) -> str:
        year = f" ({self.year})" if self.year else ""
        lic = self.licence or "Public domain"
        return f"{self.title}{year}, {self.collection} via Internet Archive: {self.page_url} [{lic}]"


def licence_ok(licenseurl: str, trusted_collection: bool) -> tuple[bool, str]:
    url = (licenseurl or "").lower()
    if any(part in url for part in REJECTED_LICENCE_PARTS):
        return False, f"restricted licence {licenseurl}"
    if any(part in url for part in ACCEPTED_LICENCES):
        return True, licenseurl
    if not url and trusted_collection:
        return True, "Public domain (US federal work)"
    return False, f"no usable licence ({licenseurl or 'none'})"


class Archive:
    def __init__(self, session: requests.Session, cache_dir: Path, collections: list[dict[str, Any]]):
        self.session = session
        self.cache = cache_dir / "archive_org"
        self.cache.mkdir(parents=True, exist_ok=True)
        self.collections = {c["id"]: bool(c.get("trusted")) for c in collections}

    # ---- search -------------------------------------------------------
    def _query(self, text: str) -> str:
        cols = " OR ".join(self.collections)
        return f"collection:({cols}) AND mediatype:movies AND ({text})"

    def count(self, text: str) -> int:
        data = http_get_json(self.session, SEARCH, {"q": self._query(text), "fl[]": "identifier", "rows": 0, "output": "json"})
        return int(data.get("response", {}).get("numFound", 0))

    def search(self, text: str, rows: int = 25) -> list[dict[str, Any]]:
        cache = self.cache / "search" / f"{slugify(text)}-{rows}.json"
        if cache.exists():
            return read_json(cache)
        params = {
            "q": self._query(text),
            "fl[]": ["identifier", "title", "year", "licenseurl", "collection", "downloads"],
            "sort[]": "downloads desc",
            "rows": rows,
            "output": "json",
        }
        data = http_get_json(self.session, SEARCH, params)
        docs = data.get("response", {}).get("docs", [])
        write_json(cache, docs)
        return docs

    # ---- items --------------------------------------------------------
    def film(self, doc: dict[str, Any]) -> Film | None:
        """Resolve a search hit into a playable, licence-checked Film."""
        ident = doc["identifier"]
        cols = doc.get("collection") or []
        cols = [cols] if isinstance(cols, str) else cols
        collection = next((c for c in cols if c in self.collections), cols[0] if cols else "")
        ok, licence = licence_ok(doc.get("licenseurl", ""), self.collections.get(collection, False))
        if not ok:
            log.info("archive: skip %s (%s)", ident, licence)
            return None

        meta_cache = self.cache / "meta" / f"{ident}.json"
        if meta_cache.exists():
            meta = read_json(meta_cache)
        else:
            meta = http_get_json(self.session, METADATA.format(id=quote(ident)))
            write_json(meta_cache, meta)

        best = None
        for fmt in VIDEO_FORMAT_PREFERENCE:
            for f in meta.get("files", []):
                if str(f.get("format", "")).lower() == fmt and f.get("name", "").lower().endswith((".mp4", ".mpeg4", ".m4v")):
                    best = f
                    break
            if best:
                break
        if best is None:
            best = next((f for f in meta.get("files", []) if f.get("name", "").lower().endswith(".mp4")), None)
        if best is None:
            return None

        def _num(v: Any) -> float:
            try:
                if isinstance(v, str) and ":" in v:
                    parts = [float(p) for p in v.split(":")]
                    return sum(p * 60 ** i for i, p in enumerate(reversed(parts)))
                return float(v)
            except (TypeError, ValueError):
                return 0.0

        title = doc.get("title") or meta.get("metadata", {}).get("title") or ident
        if isinstance(title, list):
            title = title[0]
        return Film(
            identifier=ident,
            title=str(title),
            year=str(doc.get("year", "") or meta.get("metadata", {}).get("year", "")),
            collection=collection,
            licence=licence,
            page_url=f"https://archive.org/details/{ident}",
            video_url=DOWNLOAD.format(id=quote(ident), name=quote(best["name"])),
            duration=_num(best.get("length")),
            width=int(_num(best.get("width"))),
            height=int(_num(best.get("height"))),
        )

    def local_copy(self, film: Film) -> Path:
        """Download the whole film once (fallback when remote seeking fails)."""
        dest = self.cache / "films" / f"{slugify(film.identifier, 80)}.mp4"
        return http_download(self.session, film.video_url, dest, timeout=600)
