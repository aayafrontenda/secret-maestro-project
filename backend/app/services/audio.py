"""Resolve a playable recording URL for voice calls.

The organizer's `audio_url` points at an HTML player page (Dynamics 365) whose <audio><source>
carries a short-lived SAS link to the mp3. We fetch the page, extract that link and cache it
for a little less than its lifetime.
"""

import html
import logging
import re
import time
from dataclasses import dataclass

import httpx

log = logging.getLogger(__name__)

SOURCE_RE = re.compile(r"""<source[^>]+src=["']([^"']+)["']""", re.I)
AUDIO_SRC_RE = re.compile(r"""<audio[^>]+src=["']([^"']+)["']""", re.I)
CACHE_TTL_S = 50 * 60


@dataclass
class ResolvedAudio:
    url: str | None  # direct media link, or None if the page could not be parsed
    player_url: str
    content_type: str | None
    expires_at: float  # unix time when the cached entry should be refreshed


_cache: dict[str, ResolvedAudio] = {}


async def resolve_audio(player_url: str, *, timeout_s: float = 30.0) -> ResolvedAudio:
    cached = _cache.get(player_url)
    if cached and cached.expires_at > time.time():
        return cached

    url: str | None = None
    content_type: str | None = None
    try:
        async with httpx.AsyncClient(timeout=timeout_s, follow_redirects=True) as client:
            resp = await client.get(player_url)
            content_type = resp.headers.get("content-type", "")
            if resp.status_code < 400:
                if content_type.startswith("audio/") or content_type.startswith("video/"):
                    url = str(resp.url)  # already a media file
                else:
                    match = SOURCE_RE.search(resp.text) or AUDIO_SRC_RE.search(resp.text)
                    if match:
                        url = html.unescape(match.group(1))
                        content_type = None
            else:
                log.warning("audio page %s returned %s", player_url[:80], resp.status_code)
    except httpx.HTTPError as exc:
        log.warning("audio page fetch failed: %s", exc)

    resolved = ResolvedAudio(
        url=url,
        player_url=player_url,
        content_type=content_type,
        expires_at=time.time() + (CACHE_TTL_S if url else 60),
    )
    _cache[player_url] = resolved
    return resolved


def clear_cache() -> None:
    _cache.clear()
