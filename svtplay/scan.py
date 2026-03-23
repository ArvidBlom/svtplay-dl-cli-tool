"""Folder scanner — reads embedded metadata from all .mp4 files."""

from pathlib import Path
from typing import Any, Dict, List, Optional


def _extract(tags: Dict[str, Any]) -> Dict[str, Any]:
    """Pull the fields we care about from raw mutagen tags."""

    def freeform(key: str) -> Optional[str]:
        v = tags.get(key)
        if isinstance(v, list) and v:
            return str(v[0])
        return str(v) if v is not None else None

    def tmdb_id() -> Optional[int]:
        v = freeform("----:com.apple.iTunes:TMDB_SHOW_ID")
        try:
            return int(v) if v else None
        except (ValueError, TypeError):
            return None

    return {
        "season": tags.get("tvsn"),
        "episode": tags.get("tves"),
        "episode_id": tags.get("tven"),
        "title": tags.get("\xa9nam"),
        "air_date": tags.get("\xa9day"),
        "svt_id": freeform("----:com.apple.iTunes:SVT_ID"),
        "svt_url": freeform("----:com.apple.iTunes:SVT_URL"),
        "tmdb_show_id": tmdb_id(),
        "duration_seconds": tags.get("_duration_seconds"),
    }


def scan_folder(folder: str, recursive: bool = True) -> Dict[str, Any]:
    """Crawl .mp4 files in *folder* and return embedded metadata grouped by show.

    Returns::

        {
            "folder": str,
            "total_files": int,
            "shows": {
                "Show Name": {
                    "tmdb_show_id": int | None,
                    "episodes": [
                        {
                            "file": str,
                            "season": int | None,
                            "episode": int | None,
                            "episode_id": str | None,
                            "title": str | None,
                            "air_date": str | None,
                            "svt_id": str | None,
                            "svt_url": str | None,
                            "tmdb_show_id": int | None,
                            "duration_seconds": int | None,
                        }
                    ],
                }
            },
            "unmatched": [{"file": str, "reason": str}],
        }
    """
    from svtplay.meta import read_meta

    root = Path(folder)
    _VIDEO_EXTS = ("*.mp4", "*.webm", "*.mkv", "*.m4v")
    prefix = "**/" if recursive else ""
    files = sorted(
        f for ext in _VIDEO_EXTS for f in root.glob(f"{prefix}{ext}")
    )

    shows: Dict[str, Any] = {}
    unmatched: List[Dict[str, Any]] = []

    for f in files:
        try:
            result = read_meta(str(f))
        except ValueError as exc:
            unmatched.append({"file": str(f), "reason": str(exc)})
            continue

        tags = result["tags"]
        show_name = tags.get("tvsh") or None
        if not show_name:
            unmatched.append({"file": str(f), "reason": "no show name in metadata"})
            continue

        ep = _extract(tags)

        if show_name not in shows:
            shows[show_name] = {"tmdb_show_id": ep.get("tmdb_show_id"), "episodes": []}
        elif ep.get("tmdb_show_id") and not shows[show_name]["tmdb_show_id"]:
            shows[show_name]["tmdb_show_id"] = ep["tmdb_show_id"]

        shows[show_name]["episodes"].append({"file": str(f), **ep})

    for show_data in shows.values():
        show_data["episodes"].sort(
            key=lambda e: (e.get("season") or 0, e.get("episode") or 0)
        )

    return {
        "folder": str(root.resolve()),
        "total_files": len(files),
        "shows": shows,
        "unmatched": unmatched,
    }
