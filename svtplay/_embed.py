"""Embed SVT/TMDB metadata and cover art into a video file via ffmpeg.

Designed to be reusable for both the download command and a future backfill command.
The caller provides a plain dict of metadata — no coupling to download logic.
"""

import os
import shutil
import subprocess
import tempfile
import urllib.request
from pathlib import Path
from typing import Optional

_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
    ),
}

VIDEO_EXTENSIONS = {".mp4", ".mkv", ".avi", ".mov", ".m4v", ".webm", ".ts"}


def _find_ffmpeg() -> str:
    exe = shutil.which("ffmpeg")
    if not exe:
        raise RuntimeError("ffmpeg not found on PATH. Please install ffmpeg.")
    return exe


def _download_thumbnail(url: str, suffix: str = ".jpg") -> Optional[Path]:
    """Download thumbnail URL to a temp file. Returns path or None on failure."""
    try:
        req = urllib.request.Request(url, headers=_HEADERS)
        with urllib.request.urlopen(req, timeout=15) as r:
            data = r.read()
        # Detect format from content-type or URL
        ct = r.headers.get("Content-Type", "")
        if "png" in ct or url.lower().endswith(".png"):
            suffix = ".png"
        tmp = tempfile.NamedTemporaryFile(delete=False, suffix=suffix)
        tmp.write(data)
        tmp.close()
        return Path(tmp.name)
    except Exception:
        return None


_ITUNES_NS = "----:com.apple.iTunes"


def _embed_freeform(
    path: Path,
    *,
    svt_id: Optional[str] = None,
    svt_url: Optional[str] = None,
    tmdb_show_id: Optional[int] = None,
) -> None:
    """Write custom fields as MP4 freeform atoms via mutagen.

    Standard ffmpeg -metadata keys are silently dropped by the MP4 container
    for non-iTunes keys. Freeform atoms (----:com.apple.iTunes:*) survive.
    """
    from mutagen.mp4 import MP4, MP4FreeForm

    fields: dict = {}
    if svt_id:
        fields[f"{_ITUNES_NS}:SVT_ID"] = [MP4FreeForm(svt_id.encode())]
    if svt_url:
        fields[f"{_ITUNES_NS}:SVT_URL"] = [MP4FreeForm(svt_url.encode())]
    if tmdb_show_id is not None:
        fields[f"{_ITUNES_NS}:TMDB_SHOW_ID"] = [MP4FreeForm(str(tmdb_show_id).encode())]

    if not fields:
        return

    f = MP4(str(path))
    f.tags.update(fields)
    f.save()


def embed(
    path: Path,
    *,
    title: str,
    show: str,
    season: Optional[int] = None,
    episode: Optional[int] = None,
    description: Optional[str] = None,
    air_date: Optional[str] = None,
    svt_id: Optional[str] = None,
    svt_url: Optional[str] = None,
    tmdb_show_id: Optional[int] = None,
    thumbnail_url: Optional[str] = None,
) -> None:
    """Embed metadata tags and optional cover art into *path* via ffmpeg.

    Atomically replaces the file on success. Raises RuntimeError on failure.
    """
    ffmpeg = _find_ffmpeg()
    path = Path(path)
    if not path.exists():
        raise FileNotFoundError(f"File not found: {path}")

    # Build metadata args
    meta: list[str] = []

    def _add(key: str, value: Optional[object]) -> None:
        if value is not None and str(value).strip():
            meta.extend(["-metadata", f"{key}={value}"])

    _add("title", title)
    _add("show", show)
    _add("artist", show)
    _add("album", show)
    _add("network", "SVT Play")
    if description:
        # comment is widely supported; description is iTunes-specific
        _add("comment", description)
        _add("description", description)
    _add("date", air_date)
    if season is not None:
        _add("season_number", season)
    if episode is not None:
        _add("episode_sort", episode)
        _add("track", episode)
    if season is not None and episode is not None:
        _add("episode_id", f"S{season:02d}E{episode:02d}")
    _add("svt_id", svt_id)
    _add("svt_url", svt_url)
    _add("tmdb_show_id", tmdb_show_id)
    _add("encoder", "svtplay-cli")

    # Download thumbnail if provided
    thumb_path: Optional[Path] = None
    if thumbnail_url:
        thumb_path = _download_thumbnail(thumbnail_url)

    # Build ffmpeg command
    tmp_path = path.with_suffix(".embed_tmp" + path.suffix)
    try:
        if thumb_path:
            cmd = [
                ffmpeg, "-y",
                "-i", str(path),
                "-i", str(thumb_path),
                "-map", "0",
                "-map", "1",
                "-c", "copy",
                "-disposition:v:1", "attached_pic",
                "-metadata:s:v:1", "comment=Cover (front)",
            ] + meta + [str(tmp_path)]
        else:
            cmd = [
                ffmpeg, "-y",
                "-i", str(path),
                "-c", "copy",
            ] + meta + [str(tmp_path)]

        result = subprocess.run(cmd, capture_output=True, text=True)
        if result.returncode != 0:
            raise RuntimeError(
                f"ffmpeg failed (exit {result.returncode}):\n{result.stderr[-2000:]}"
            )

        os.replace(str(tmp_path), str(path))

    finally:
        if thumb_path and thumb_path.exists():
            thumb_path.unlink(missing_ok=True)
        if tmp_path.exists():
            tmp_path.unlink(missing_ok=True)

    # Write custom freeform atoms via mutagen (MP4 drops arbitrary ffmpeg -metadata keys)
    _embed_freeform(path, svt_id=svt_id, svt_url=svt_url, tmdb_show_id=tmdb_show_id)


def read_svt_id(path: Path) -> Optional[str]:
    """Extract the svt_id metadata tag from a video file via ffprobe.

    Used by the download cache to detect already-downloaded files.
    Returns None if ffprobe is unavailable or the tag is absent.
    """
    ffprobe = shutil.which("ffprobe")
    if not ffprobe:
        return None
    try:
        result = subprocess.run(
            [
                ffprobe, "-v", "quiet",
                "-print_format", "json",
                "-show_format",
                str(path),
            ],
            capture_output=True, text=True, timeout=10,
        )
        if result.returncode != 0:
            return None
        import json
        data = json.loads(result.stdout)
        tags = (data.get("format") or {}).get("tags") or {}
        # ffprobe lowercases tag keys
        return tags.get("svt_id") or tags.get("SVT_ID") or None
    except Exception:
        return None
