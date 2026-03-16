"""File-based cache for TMDB LLM match results and SVT Play episode lists.

Cache location: .svtplay-cache/tmdb-match/<slug>.json (repo root)
TMDB match TTL: 7 days
SVT episodes TTL: 1 day (new episodes added more frequently)
"""

import json
import os
import re
import time
from pathlib import Path
from typing import Any, Dict, List, Optional

# Cache lives in the repo root (.svtplay-cache/), override with SVTPLAY_CACHE_DIR env var.
# __file__ is cli/svtplay/svtplay/_cache.py → parents[3] = repo root (personal-agent/)
_REPO_ROOT = Path(__file__).resolve().parents[3]
_CACHE_BASE = Path(os.environ.get("SVTPLAY_CACHE_DIR", str(_REPO_ROOT / ".svtplay-cache")))
_CACHE_DIR = _CACHE_BASE / "tmdb-match"
_DEFAULT_TTL = 7 * 24 * 60 * 60       # 7 days (TMDB match)
_SVT_EPISODES_TTL = 24 * 60 * 60      # 1 day  (SVT episode list)


def _slug(name: str) -> str:
    """Convert show name to a safe filename slug."""
    s = name.lower().strip()
    s = re.sub(r"[åä]", "a", s)
    s = re.sub(r"[ö]", "o", s)
    s = re.sub(r"[^a-z0-9]+", "-", s)
    return s.strip("-") or "unknown"


def get(name: str, ttl: int = _DEFAULT_TTL) -> Optional[Dict[str, Any]]:
    """Return cached match dict for *name*, or None if missing/stale."""
    path = _CACHE_DIR / f"{_slug(name)}.json"
    if not path.exists():
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        age = time.time() - data.get("cached_at", 0)
        if age > ttl:
            return None
        return data
    except Exception:
        return None


def put(name: str, payload: Dict[str, Any]) -> None:
    """Write *payload* to cache for *name*."""
    _CACHE_DIR.mkdir(parents=True, exist_ok=True)
    path = _CACHE_DIR / f"{_slug(name)}.json"
    data = {**payload, "cached_at": time.time()}
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def get_svt_episodes(name: str, ttl: int = _SVT_EPISODES_TTL) -> Optional[List]:
    """Return cached SVT episode list for *name*, or None if missing/stale."""
    path = _CACHE_DIR / f"{_slug(name)}.json"
    if not path.exists():
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        age = time.time() - data.get("svt_episodes_cached_at", 0)
        if age > ttl:
            return None
        return data.get("svt_episodes") or None
    except Exception:
        return None


def patch_svt_episodes(name: str, episodes: List) -> None:
    """Update only the svt_episodes field in the cache, preserving TMDB data."""
    _CACHE_DIR.mkdir(parents=True, exist_ok=True)
    path = _CACHE_DIR / f"{_slug(name)}.json"
    try:
        data = json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}
    except Exception:
        data = {}
    data["svt_episodes"] = episodes
    data["svt_episodes_cached_at"] = time.time()
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    tmp.replace(path)


def invalidate(name: str) -> bool:
    """Delete cache entry for *name*. Returns True if it existed."""
    path = _CACHE_DIR / f"{_slug(name)}.json"
    if path.exists():
        path.unlink()
        return True
    return False
