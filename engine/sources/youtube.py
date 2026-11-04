"""Public YouTube channel data for packaging research.

Two interchangeable backends:
- YouTube Data API with a free API key (YOUTUBE_API_KEY): exact views, upload
  dates and durations; about 4 quota units per channel of a 10,000/day free
  allowance. No OAuth, no channel access.
- yt-dlp (no key): views, titles and durations from the channel's Videos tab;
  no upload dates.

The outlier multiple of a video is its views divided by the median views of
the same channel's recent long-form videos. A 10x video on a channel that
normally does 100k says more about its packaging than a 2M video on a
channel that normally does 2M.
"""

from __future__ import annotations

import json
import re
import shutil
import statistics
import subprocess
from dataclasses import asdict, dataclass
from typing import Any

import requests

from ..util import PermanentError, http_get_json, log

API = "https://www.googleapis.com/youtube/v3"
MIN_LONG_SECONDS = 180  # ignore Shorts and clips when measuring long-form packaging


@dataclass
class Video:
    id: str
    channel: str
    title: str
    views: int
    duration: int
    published: str = ""
    outlier: float = 0.0
    channel_median: int = 0

    @property
    def url(self) -> str:
        return f"https://www.youtube.com/watch?v={self.id}"

    @property
    def thumb(self) -> str:
        # mqdefault is 320x180 with no letterbox: the size viewers see in feeds.
        return f"https://i.ytimg.com/vi/{self.id}/mqdefault.jpg"

    def to_dict(self) -> dict[str, Any]:
        d = asdict(self)
        d.update(url=self.url, thumb=self.thumb)
        return d


def iso_duration(value: str) -> int:
    m = re.match(r"P(?:(\d+)D)?T?(?:(\d+)H)?(?:(\d+)M)?(?:(\d+)S)?", value or "")
    if not m:
        return 0
    d, h, mi, s = (int(x) if x else 0 for x in m.groups())
    return d * 86400 + h * 3600 + mi * 60 + s


def score_outliers(videos: list[Video]) -> list[Video]:
    long_form = [v for v in videos if v.duration >= MIN_LONG_SECONDS or v.duration == 0]
    if len(long_form) < 5:
        return []
    median = int(statistics.median(v.views for v in long_form)) or 1
    for v in long_form:
        v.channel_median = median
        v.outlier = round(v.views / median, 2)
    return long_form


class YouTubeAPI:
    def __init__(self, session: requests.Session, key: str):
        self.session, self.key = session, key

    def _get(self, path: str, **params: Any) -> dict:
        params["key"] = self.key
        return http_get_json(self.session, f"{API}/{path}", params)

    def channel_videos(self, handle: str, limit: int = 60) -> list[Video]:
        handle = handle if handle.startswith("@") or handle.startswith("UC") else f"@{handle}"
        params = {"part": "contentDetails,snippet"}
        params["id" if handle.startswith("UC") else "forHandle"] = handle
        data = self._get("channels", **params)
        items = data.get("items", [])
        if not items:
            raise PermanentError(f"YouTube channel not found: {handle}")
        name = items[0]["snippet"]["title"]
        uploads = items[0]["contentDetails"]["relatedPlaylists"]["uploads"]
        ids: list[str] = []
        token = None
        while len(ids) < limit:
            page = self._get("playlistItems", part="contentDetails", playlistId=uploads, maxResults=50,
                             **({"pageToken": token} if token else {}))
            ids += [i["contentDetails"]["videoId"] for i in page.get("items", [])]
            token = page.get("nextPageToken")
            if not token:
                break
        videos: list[Video] = []
        for i in range(0, min(len(ids), limit), 50):
            batch = self._get("videos", part="snippet,statistics,contentDetails", id=",".join(ids[i:i + 50]))
            for it in batch.get("items", []):
                videos.append(Video(
                    id=it["id"], channel=name, title=it["snippet"]["title"],
                    views=int(it.get("statistics", {}).get("viewCount", 0)),
                    duration=iso_duration(it.get("contentDetails", {}).get("duration", "")),
                    published=it["snippet"].get("publishedAt", "")[:10],
                ))
        return videos


class YtDlp:
    def __init__(self) -> None:
        self.exe = shutil.which("yt-dlp")
        if not self.exe:
            raise PermanentError("Set YOUTUBE_API_KEY, or install yt-dlp (pip install yt-dlp)")

    def channel_videos(self, handle: str, limit: int = 60) -> list[Video]:
        handle = handle if handle.startswith("@") else f"@{handle}"
        url = f"https://www.youtube.com/{handle}/videos"
        proc = subprocess.run([self.exe, "--flat-playlist", "-J", "--playlist-end", str(limit), url],
                              capture_output=True, text=True, timeout=180)
        if proc.returncode != 0:
            raise RuntimeError(f"yt-dlp failed for {handle}: {proc.stderr.strip()[-300:]}")
        data = json.loads(proc.stdout)
        name = data.get("channel") or data.get("uploader") or handle
        return [
            Video(id=e["id"], channel=name, title=e.get("title", ""), views=int(e.get("view_count") or 0),
                  duration=int(e.get("duration") or 0))
            for e in data.get("entries", []) if e.get("id")
        ]


def client(session: requests.Session, api_key: str):
    return YouTubeAPI(session, api_key) if api_key else YtDlp()


def outliers_for(yt, handles: list[str], limit: int = 60, min_multiple: float = 2.0,
                 echo=print) -> tuple[list[Video], list[str]]:
    """Return (outlier videos above min_multiple, sorted best first), (failed handles)."""
    found: list[Video] = []
    failed: list[str] = []
    for handle in handles:
        try:
            scored = score_outliers(yt.channel_videos(handle, limit))
        except Exception as exc:  # noqa: BLE001
            log.warning("youtube: %s failed: %s", handle, exc)
            failed.append(handle)
            echo(f"  ✗ {handle}: {exc}")
            continue
        top = [v for v in scored if v.outlier >= min_multiple]
        echo(f"  ✓ {handle}: {len(scored)} videos, {len(top)} at {min_multiple}x+ (median {scored[0].channel_median:,} views)"
             if scored else f"  · {handle}: not enough long videos")
        found += top
    found.sort(key=lambda v: v.outlier, reverse=True)
    return found, failed
