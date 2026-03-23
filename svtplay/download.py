"""Plain-function SVT Play episode downloader."""

import shutil
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

_DEFAULT_OUTPUT_DIR = Path.home() / "Downloads" / "svtplay-dl"


# ─── Private helpers ──────────────────────────────────────────────────────────

def _find_svtplay_dl() -> List[str]:
    exe = shutil.which("svtplay-dl")
    if exe:
        return [exe]
    return [sys.executable, "-m", "svtplay_dl"]


def _find_produced_file(base: Path) -> Optional[Path]:
    """Find the video file svtplay-dl wrote in a temp directory."""
    from svtplay._embed import VIDEO_EXTENSIONS
    for ext in VIDEO_EXTENSIONS:
        candidate = base.with_suffix(ext)
        if candidate.exists():
            return candidate
    for f in base.parent.iterdir():
        if f.is_file() and f.suffix.lower() in VIDEO_EXTENSIONS:
            return f
    return None


def _resolve_tmdb(
    svt_name: str,
    svt_url: str,
    svt_description: str,
    svt_episodes: List[Dict],
    api_key: str,
    tmdb_key: str,
    no_cache: bool,
) -> Tuple[Optional[Dict], Optional[List[Dict]]]:
    """Return (tmdb_match_dict, tmdb_episodes_list) or (None, None) on failure."""
    from svtplay._cache import get as cache_get, put as cache_put
    from svtplay._tmdb_api import search_show, get_all_episodes
    from svtplay.tmdb import TMDBMatch, _llm_match

    if not no_cache:
        cached = cache_get(svt_name)
        if cached:
            return cached.get("tmdb_match"), cached.get("tmdb_episodes")

    try:
        candidates = search_show(svt_name, tmdb_key)[:10]
    except Exception:
        return None, None

    svt_episode_names = [ep.get("name", "") for ep in svt_episodes[:5] if ep.get("name")]

    if not candidates:
        tmdb_match_obj = TMDBMatch(
            tmdb_id=None, tmdb_name=None, original_name=None,
            first_air_date=None, overview=None,
            confidence=0.0, reasoning="No TMDB results found for this title.",
        )
    elif len(candidates) == 1:
        c = candidates[0]
        tmdb_match_obj = TMDBMatch(
            tmdb_id=c.get("id"), tmdb_name=c.get("name"),
            original_name=c.get("original_name"), first_air_date=c.get("first_air_date"),
            overview=c.get("overview"), confidence=1.0,
            reasoning="Only one TMDB result returned; selected automatically.",
        )
    else:
        try:
            tmdb_match_obj = _llm_match(svt_name, svt_description, svt_episode_names, candidates, api_key)
        except Exception:
            return None, None

    tmdb_match = tmdb_match_obj.model_dump()
    tmdb_episodes = None
    tmdb_id = tmdb_match.get("tmdb_id")
    if tmdb_id and tmdb_match.get("confidence", 0) >= 0.90:
        try:
            tmdb_episodes = get_all_episodes(tmdb_id, tmdb_key)
        except Exception:
            pass

    cache_put(svt_name, {"svt_name": svt_name, "tmdb_match": tmdb_match, "tmdb_episodes": tmdb_episodes})
    return tmdb_match, tmdb_episodes


# ─── Public plain function ─────────────────────────────────────────────────────

def download_show(
    query: str,
    output_dir: Optional[str] = None,
    api_key: Optional[str] = None,
    tmdb_key: Optional[str] = None,
    download_all: bool = False,
    quality: Optional[str] = None,
    dry_run: bool = False,
    threshold: float = 0.55,
    no_cache: bool = False,
) -> Dict[str, Any]:
    """Download new episodes of a show from SVT Play.

    Returns: {query, show, downloaded: [...], failed: [...], skipped: int}
    Raises ValueError on failure.
    """
    from svtplay._svt import find_show, fetch_show_episodes
    from svtplay._cache import get_svt_episodes, patch_svt_episodes
    from svtplay._match import match_episodes, episode_filename, safe_filename
    from svtplay._dl_cache import get_downloaded_ids, add_entry
    from svtplay._embed import embed

    # 1. Find SVT show
    result = find_show(query, match_threshold=threshold, shows_only=True)
    match = result.get("match")
    if not match:
        raise ValueError(f"No SVT Play show found for '{query}'.")

    svt_name: str = match["name"]
    svt_show_url: str = match["url"]
    svt_description: str = match.get("description") or match.get("short_description") or ""
    svt_thumbnail: Optional[str] = match.get("thumbnail_url")

    # 2. Fetch episode list (cache first, then live)
    svt_episodes = get_svt_episodes(svt_name)
    if svt_episodes is None:
        try:
            svt_episodes = fetch_show_episodes(svt_show_url)
        except Exception as exc:
            raise ValueError(f"Failed to fetch episodes: {exc}") from exc
        if svt_episodes:
            patch_svt_episodes(svt_name, svt_episodes)

    if not svt_episodes:
        raise ValueError("No episodes found on SVT Play for this show.")

    # 3. Resolve TMDB (optional)
    tmdb_match: Optional[Dict] = None
    tmdb_episodes: Optional[List[Dict]] = None
    tmdb_show_id: Optional[int] = None

    if api_key and tmdb_key:
        tmdb_match, tmdb_episodes = _resolve_tmdb(
            svt_name, svt_show_url, svt_description,
            svt_episodes, api_key, tmdb_key, no_cache,
        )
        if tmdb_match:
            tmdb_show_id = tmdb_match.get("tmdb_id")

    # 4. Match SVT↔TMDB episodes for S##E##
    ep_season_map: Dict[str, Tuple[Optional[int], Optional[int]]] = {}
    if tmdb_episodes:
        ep_season_map = match_episodes(svt_episodes, tmdb_episodes)

    # 5. Output directory
    base_dir = Path(output_dir) if output_dir else _DEFAULT_OUTPUT_DIR
    show_dir = base_dir / safe_filename(svt_name)

    # 6. Determine which episodes to download
    if download_all:
        downloaded_ids: set = set()
    else:
        downloaded_ids = get_downloaded_ids(svt_name, show_dir)

    to_download = [
        ep for ep in svt_episodes
        if ep.get("svt_id") not in downloaded_ids and ep.get("available", False)
    ]
    unavailable = [ep for ep in svt_episodes if not ep.get("available", False)]
    skipped = len(svt_episodes) - len(to_download) - len(unavailable)

    if not to_download:
        return {"query": query, "show": svt_name, "downloaded": [], "failed": [], "skipped": skipped}

    # 7. Dry run
    if dry_run:
        plan = []
        for ep in to_download:
            svt_id = ep["svt_id"]
            season, episode = ep_season_map.get(svt_id, (None, None))
            fname = episode_filename(ep.get("name", svt_id), svt_name, season, episode)
            final_path = show_dir / fname
            if final_path.exists():
                skipped += 1
                continue
            plan.append({"svt_id": svt_id, "name": ep.get("name"), "filename": fname,
                         "season": season, "episode": episode, "url": ep["url"]})
        return {"query": query, "show": svt_name, "dry_run": True,
                "would_download": plan, "skipped": skipped}

    # 8. Download loop
    show_dir.mkdir(parents=True, exist_ok=True)
    downloaded_results = []
    failed_results = []

    for ep in to_download:
        svt_id = ep["svt_id"]
        ep_name = ep.get("name") or svt_id
        ep_url = ep["url"]
        season, episode_num = ep_season_map.get(svt_id, (None, None))
        final_name = episode_filename(ep_name, svt_name, season, episode_num)
        final_path = show_dir / final_name

        if final_path.exists():
            downloaded_ids.add(svt_id)
            continue

        with tempfile.TemporaryDirectory(prefix="svtplay-dl-") as tmpdir:
            tmp_base = Path(tmpdir) / "episode"
            extra: List[str] = []
            if quality:
                extra += ["-q", quality]

            cmd = _find_svtplay_dl() + extra + ["--output", str(tmp_base), ep_url]
            dl_result = subprocess.run(cmd, capture_output=True, text=True)

            if dl_result.returncode != 0:
                msg = dl_result.stderr[-500:] or dl_result.stdout[-500:]
                failed_results.append({"svt_id": svt_id, "name": ep_name, "error": msg})
                continue

            produced = _find_produced_file(tmp_base)
            if not produced:
                failed_results.append({"svt_id": svt_id, "name": ep_name,
                                       "error": "output file not found"})
                continue

            ext = produced.suffix
            final_name = episode_filename(ep_name, svt_name, season, episode_num, ext=ext)
            final_path = show_dir / final_name

            ep_thumbnail = ep.get("thumbnail_url") or svt_thumbnail
            try:
                embed(
                    produced,
                    title=ep_name,
                    show=svt_name,
                    season=season,
                    episode=episode_num,
                    description=ep.get("description"),
                    air_date=ep.get("air_date"),
                    svt_id=svt_id,
                    svt_url=ep_url,
                    tmdb_show_id=tmdb_show_id,
                    thumbnail_url=ep_thumbnail,
                )
            except Exception:
                pass  # non-fatal — file is still saved

            shutil.move(str(produced), str(final_path))

        add_entry(
            svt_name,
            svt_id=svt_id,
            filename=final_name,
            season=season,
            episode=episode_num,
            episode_title=ep_name,
            svt_url=ep_url,
            tmdb_show_id=tmdb_show_id,
        )

        downloaded_results.append({
            "svt_id": svt_id,
            "name": ep_name,
            "filename": final_name,
            "season": season,
            "episode": episode_num,
            "path": str(final_path),
        })

    return {
        "query": query,
        "show": svt_name,
        "downloaded": downloaded_results,
        "failed": failed_results,
        "skipped": skipped,
    }


def download_missing(
    folder: str,
    query: str,
    output_dir: Optional[str] = None,
    api_key: Optional[str] = None,
    tmdb_key: Optional[str] = None,
    quality: Optional[str] = None,
    dry_run: bool = False,
    threshold: float = 0.55,
    no_cache: bool = False,
) -> Dict[str, Any]:
    """Download episodes that are on SVT Play but not in *folder*.

    Uses SVT_URL embedded in local file metadata as the ground-truth "already
    have" fingerprint — no filename matching required.

    Returns: {query, show, downloaded: [...], failed: [...], skipped: int}
    """
    from svtplay.scan import scan_folder
    from svtplay._svt import find_show, fetch_show_episodes
    from svtplay._cache import get_svt_episodes, patch_svt_episodes
    from svtplay._match import match_episodes, episode_filename, safe_filename
    from svtplay._embed import embed

    # ── 1. Build set of SVT IDs already present locally (from embedded metadata) ──
    scan = scan_folder(folder)
    local_svt_ids: set = set()
    local_tmdb_id: Optional[int] = None
    for show_data in scan["shows"].values():
        if not local_tmdb_id:
            local_tmdb_id = show_data.get("tmdb_show_id")
        for ep in show_data["episodes"]:
            svt_url = ep.get("svt_url") or ""
            svt_id = ep.get("svt_id") or ""
            # svt_url is "https://www.svtplay.se/video/<id>" — extract the id
            if svt_url:
                local_svt_ids.add(svt_url.rstrip("/").split("/")[-1])
            if svt_id:
                local_svt_ids.add(svt_id)

    # ── 2. Find show on SVT Play ──────────────────────────────────────────────
    result = find_show(query, match_threshold=threshold, shows_only=True)
    match = result.get("match")
    if not match:
        raise ValueError(f"No SVT Play show found for '{query}'.")

    svt_name: str = match["name"]
    svt_show_url: str = match["url"]
    svt_description: str = match.get("description") or match.get("short_description") or ""
    svt_thumbnail: Optional[str] = match.get("thumbnail_url")

    # ── 3. Fetch SVT episode list ─────────────────────────────────────────────
    svt_episodes = get_svt_episodes(svt_name) if not no_cache else None
    if svt_episodes is None:
        svt_episodes = fetch_show_episodes(svt_show_url)
        if svt_episodes:
            patch_svt_episodes(svt_name, svt_episodes)

    if not svt_episodes:
        raise ValueError("No episodes found on SVT Play for this show.")

    # ── 4. Resolve TMDB ───────────────────────────────────────────────────────
    tmdb_match: Optional[Dict] = None
    tmdb_episodes: Optional[List[Dict]] = None
    tmdb_show_id: Optional[int] = local_tmdb_id  # prefer what's already embedded

    if api_key and tmdb_key:
        tmdb_match, tmdb_episodes = _resolve_tmdb(
            svt_name, svt_show_url, svt_description,
            svt_episodes, api_key, tmdb_key, no_cache,
        )
        if tmdb_match and not tmdb_show_id:
            tmdb_show_id = tmdb_match.get("tmdb_id")

    # ── 5. Match SVT ↔ TMDB for S##E## numbers ───────────────────────────────
    ep_season_map: Dict[str, Tuple[Optional[int], Optional[int]]] = {}
    if tmdb_episodes:
        ep_season_map = match_episodes(svt_episodes, tmdb_episodes)

    # ── 6. Filter to episodes not already on disk ─────────────────────────────
    to_download = [
        ep for ep in svt_episodes
        if ep.get("svt_id") not in local_svt_ids and ep.get("available", False)
    ]
    skipped_episodes = [
        {"svt_id": ep.get("svt_id"), "name": ep.get("name")}
        for ep in svt_episodes
        if ep.get("svt_id") in local_svt_ids
    ]
    skipped = len(svt_episodes) - len(to_download)

    base_dir = Path(output_dir) if output_dir else _DEFAULT_OUTPUT_DIR
    show_dir = base_dir / safe_filename(svt_name)

    # ── 7. Dry run ────────────────────────────────────────────────────────────
    if dry_run:
        plan = []
        for ep in to_download:
            svt_id = ep["svt_id"]
            season, episode = ep_season_map.get(svt_id, (None, None))
            fname = episode_filename(ep.get("name", svt_id), svt_name, season, episode)
            plan.append({
                "svt_id": svt_id,
                "name": ep.get("name"),
                "filename": fname,
                "season": season,
                "episode": episode,
                "url": ep["url"],
            })
        return {"query": query, "show": svt_name, "dry_run": True,
                "would_download": plan, "skipped": skipped,
                "skipped_episodes": skipped_episodes}

    # ── 8. Download loop ──────────────────────────────────────────────────────
    show_dir.mkdir(parents=True, exist_ok=True)
    downloaded_results = []
    failed_results = []

    for ep in to_download:
        svt_id = ep["svt_id"]
        ep_name = ep.get("name") or svt_id
        ep_url = ep["url"]
        season, episode_num = ep_season_map.get(svt_id, (None, None))
        final_name = episode_filename(ep_name, svt_name, season, episode_num)
        final_path = show_dir / final_name

        with tempfile.TemporaryDirectory(prefix="svtplay-dl-") as tmpdir:
            tmp_base = Path(tmpdir) / "episode"
            extra: List[str] = []
            if quality:
                extra += ["-q", quality]

            cmd = _find_svtplay_dl() + extra + ["--output", str(tmp_base), ep_url]
            dl_result = subprocess.run(cmd, capture_output=True, text=True)

            if dl_result.returncode != 0:
                msg = dl_result.stderr[-500:] or dl_result.stdout[-500:]
                failed_results.append({"svt_id": svt_id, "name": ep_name, "error": msg})
                continue

            produced = _find_produced_file(tmp_base)
            if not produced:
                failed_results.append({"svt_id": svt_id, "name": ep_name,
                                       "error": "output file not found"})
                continue

            ext = produced.suffix
            final_name = episode_filename(ep_name, svt_name, season, episode_num, ext=ext)
            final_path = show_dir / final_name

            ep_thumbnail = ep.get("thumbnail_url") or svt_thumbnail
            try:
                embed(
                    produced,
                    title=ep_name,
                    show=svt_name,
                    season=season,
                    episode=episode_num,
                    description=ep.get("description"),
                    air_date=ep.get("air_date"),
                    svt_id=svt_id,
                    svt_url=ep_url,
                    tmdb_show_id=tmdb_show_id,
                    thumbnail_url=ep_thumbnail,
                )
            except Exception:
                pass

            shutil.move(str(produced), str(final_path))

        downloaded_results.append({
            "svt_id": svt_id,
            "name": ep_name,
            "filename": final_name,
            "season": season,
            "episode": episode_num,
            "path": str(final_path),
        })

    return {
        "query": query,
        "show": svt_name,
        "downloaded": downloaded_results,
        "failed": failed_results,
        "skipped": skipped,
        "skipped_episodes": skipped_episodes,
    }
