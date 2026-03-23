"""TMDB REST API — show search and episode metadata.

All HTTP is done with stdlib urllib only.
Requires a TMDB API key (v3).
"""

import json
import time
import urllib.parse
import urllib.request
from typing import Any, Dict, List

_BASE = "https://api.themoviedb.org/3"
_IMAGE_BASE = "https://image.tmdb.org/t/p/original"
_HEADERS = {"User-Agent": "svtplay-cli/1.0", "Accept": "application/json"}


def _still_url(path: str | None) -> str | None:
    return f"{_IMAGE_BASE}{path}" if path else None


def _get(path: str, params: Dict[str, str], timeout: int = 15) -> Dict[str, Any]:
    url = f"{_BASE}{path}?{urllib.parse.urlencode(params)}"
    req = urllib.request.Request(url, headers=_HEADERS)
    time.sleep(0.3)
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read().decode("utf-8"))


def search_show(title: str, api_key: str, language: str = "sv") -> List[Dict[str, Any]]:
    """Search TMDB for TV shows matching *title*. Returns raw result list."""
    data = _get("/search/tv", {"query": title, "language": language, "api_key": api_key})
    return data.get("results") or []


def _get_season_episodes(
    show_id: int, season: int, api_key: str, language: str
) -> List[Dict[str, Any]]:
    data = _get(f"/tv/{show_id}/season/{season}", {"language": language, "api_key": api_key})
    episodes = []
    for ep in data.get("episodes") or []:
        episodes.append({
            "season_number": ep.get("season_number", season),
            "episode_number": ep.get("episode_number"),
            "name": ep.get("name") or "",
            "air_date": ep.get("air_date"),
            "overview": ep.get("overview") or "",
            "id": ep.get("id"),
            "runtime": ep.get("runtime"),
            "episode_type": ep.get("episode_type"),
            "still_url": _still_url(ep.get("still_path")),
        })
    return episodes


def get_all_episodes(
    show_id: int, api_key: str, language: str = "sv"
) -> List[Dict[str, Any]]:
    """Fetch all episodes for *show_id* across all seasons."""
    show = _get(f"/tv/{show_id}", {"language": language, "api_key": api_key})
    num_seasons = show.get("number_of_seasons") or 0
    all_episodes: List[Dict[str, Any]] = []
    for s in range(1, num_seasons + 1):
        all_episodes.extend(_get_season_episodes(show_id, s, api_key, language))
    return all_episodes
