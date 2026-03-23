"""Plain-function video metadata reader."""

from pathlib import Path
from typing import Any, Dict, List

_EXPECTED = {
    "©nam": "title",
    "tvsh": "show",
    "tvsn": "season",
    "tves": "episode",
    "tven": "episode_id",
    "tvnn": "network",
    "©day": "air_date",
    "desc": "description",
    "covr": "cover_art",
    "----:com.apple.iTunes:SVT_ID": "svt_id",
    "----:com.apple.iTunes:SVT_URL": "svt_url",
    "----:com.apple.iTunes:TMDB_SHOW_ID": "tmdb_show_id",
}


def _read_tags(path: Path) -> Dict[str, Any]:
    from mutagen.mp4 import MP4

    f = MP4(str(path))
    tags: Dict[str, Any] = {}
    if not f.tags:
        return tags
    for k, v in f.tags.items():
        if k == "covr":
            tags[k] = f"[cover art, {len(v[0])} bytes]"
        elif k.startswith("----"):
            tags[k] = [bytes(x).decode("utf-8", errors="replace") for x in v]
        elif isinstance(v, list) and len(v) == 1:
            tags[k] = v[0]
        else:
            tags[k] = v
    tags["_duration_seconds"] = round(f.info.length)
    tags["_bitrate_kbps"] = f.info.bitrate // 1000
    return tags


def _missing(tags: Dict[str, Any]) -> List[str]:
    return [label for key, label in _EXPECTED.items() if key not in tags]


def read_meta(file: str) -> Dict[str, Any]:
    """Read metadata embedded in a video file.

    Returns: {file, tags, missing, needs_backfill}
    Raises ValueError on failure.
    """
    path = Path(file)
    try:
        tags = _read_tags(path)
    except Exception as exc:
        raise ValueError(str(exc)) from exc

    missing = _missing(tags)
    return {
        "file": str(path),
        "tags": tags,
        "missing": missing,
        "needs_backfill": len(missing) > 0,
    }
