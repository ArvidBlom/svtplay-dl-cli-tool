"""Download history cache for svtplay-download.

Cache location: ~/.svtplay-cli/downloads/<slug>.json

Each file tracks which SVT episode IDs have been downloaded for a show,
plus enough metadata to reconstruct a backfill if needed.

The cache is supplemented by `scan_dir_for_svt_ids()` which reads ffprobe
metadata from existing video files — this lets the tool detect episodes that
were downloaded before the cache existed.
"""

import json
import os
import re
import time
from pathlib import Path
from typing import Any, Dict, List, Optional, Set

from svtplay._embed import read_svt_id, VIDEO_EXTENSIONS

# Cache lives in the repo root (.svtplay-cache/), override with SVTPLAY_CACHE_DIR env var.
# __file__ is cli/svtplay/svtplay/_dl_cache.py → parents[3] = repo root (personal-agent/)
_REPO_ROOT = Path(__file__).resolve().parents[3]
_CACHE_BASE = Path(os.environ.get("SVTPLAY_CACHE_DIR", str(_REPO_ROOT / ".svtplay-cache")))
_CACHE_DIR = _CACHE_BASE / "downloads"


def _slug(name: str) -> str:
    """Convert show name to a safe filename slug (matches _cache.py convention)."""
    s = name.lower().strip()
    s = re.sub(r"[åä]", "a", s)
    s = re.sub(r"[ö]", "o", s)
    s = re.sub(r"[^a-z0-9]+", "-", s)
    return s.strip("-") or "unknown"


def _empty(show_name: str) -> Dict[str, Any]:
    return {"show_name": show_name, "entries": []}


# ─── Read / Write ──────────────────────────────────────────────────────────────

def load(show_name: str) -> Dict[str, Any]:
    """Load cache for *show_name*. Returns empty structure if not found."""
    path = _CACHE_DIR / f"{_slug(show_name)}.json"
    if not path.exists():
        return _empty(show_name)
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return _empty(show_name)


def save(show_name: str, data: Dict[str, Any]) -> None:
    """Write cache atomically."""
    _CACHE_DIR.mkdir(parents=True, exist_ok=True)
    path = _CACHE_DIR / f"{_slug(show_name)}.json"
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    tmp.replace(path)


# ─── Query / Update ────────────────────────────────────────────────────────────

def is_downloaded(show_name: str, svt_id: str) -> bool:
    """Return True if *svt_id* appears in the download cache for *show_name*."""
    data = load(show_name)
    return any(e.get("svt_id") == svt_id for e in data.get("entries", []))


def add_entry(
    show_name: str,
    *,
    svt_id: str,
    filename: str,
    season: Optional[int],
    episode: Optional[int],
    episode_title: Optional[str] = None,
    svt_url: Optional[str] = None,
    tmdb_show_id: Optional[int] = None,
) -> None:
    """Append a download record and persist."""
    data = load(show_name)
    data["entries"].append({
        "svt_id": svt_id,
        "filename": filename,
        "season": season,
        "episode": episode,
        "episode_title": episode_title,
        "svt_url": svt_url,
        "tmdb_show_id": tmdb_show_id,
        "downloaded_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
    })
    save(show_name, data)


def known_svt_ids(show_name: str) -> Set[str]:
    """Return all svt_ids recorded in the cache for *show_name*."""
    data = load(show_name)
    return {e["svt_id"] for e in data.get("entries", []) if e.get("svt_id")}


# ─── Filesystem fallback ───────────────────────────────────────────────────────

def scan_dir_for_svt_ids(show_dir: Path) -> Set[str]:
    """Read ffprobe metadata from existing video files to extract svt_id tags.

    Used as a fallback when the JSON cache is empty (e.g. pre-existing downloads).
    Returns the set of svt_ids found across all video files in the directory.
    """
    found: Set[str] = set()
    if not show_dir.is_dir():
        return found
    for f in show_dir.iterdir():
        if f.is_file() and f.suffix.lower() in VIDEO_EXTENSIONS:
            svt_id = read_svt_id(f)
            if svt_id:
                found.add(svt_id)
    return found


def get_downloaded_ids(show_name: str, show_dir: Optional[Path] = None) -> Set[str]:
    """Combined check: cache first, then filesystem scan if cache is empty.

    *show_dir* is required for the filesystem fallback.
    """
    ids = known_svt_ids(show_name)
    if not ids and show_dir:
        ids = scan_dir_for_svt_ids(show_dir)
    return ids


def list_entries(show_name: str) -> List[Dict[str, Any]]:
    """Return all recorded entries for *show_name*."""
    return load(show_name).get("entries", [])
