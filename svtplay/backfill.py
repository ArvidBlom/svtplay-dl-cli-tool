"""Plain functions for agent-driven metadata backfill."""

import shutil
from pathlib import Path
from typing import Any, Dict, List, Optional

from svtplay._embed import VIDEO_EXTENSIONS, embed
from svtplay._match import episode_filename


# ─── backfill_info ────────────────────────────────────────────────────────────

def backfill_info(
    show: str,
    files: Optional[List[str]] = None,
    scan_dir: Optional[str] = None,
    api_key: Optional[str] = None,
    tmdb_key: Optional[str] = None,
    threshold: float = 0.55,
) -> Dict[str, Any]:
    """Build a payload for agent-driven metadata backfill.

    Returns: {show, svt_show_url, tmdb_show_id, files, svt_episodes, tmdb_episodes, instructions}
    Raises ValueError on failure.
    """
    from svtplay._svt import find_show, fetch_show_episodes
    from svtplay._cache import get as cache_get, get_svt_episodes, patch_svt_episodes

    # Collect file list
    file_paths: List[Path] = []
    for f in (files or []):
        p = Path(f)
        if p.suffix.lower() in VIDEO_EXTENSIONS:
            file_paths.append(p.resolve())

    if scan_dir:
        d = Path(scan_dir)
        for f in sorted(d.iterdir()):
            if f.is_file() and f.suffix.lower() in VIDEO_EXTENSIONS:
                file_paths.append(f.resolve())

    if not file_paths:
        raise ValueError("No video files provided. Use files or scan_dir.")

    # Find SVT show
    svt_result = find_show(show, match_threshold=threshold, shows_only=True)
    svt_match = svt_result.get("match")
    if not svt_match:
        raise ValueError(f"No SVT Play show found for '{show}'.")

    svt_name: str = svt_match["name"]
    svt_show_url: str = svt_match["url"]

    # Fetch SVT episodes (cache first, then live)
    svt_episodes = get_svt_episodes(svt_name)
    if svt_episodes is None:
        try:
            svt_episodes = fetch_show_episodes(svt_show_url)
        except Exception as exc:
            raise ValueError(f"Failed to fetch SVT episodes: {exc}") from exc
        if svt_episodes:
            patch_svt_episodes(svt_name, svt_episodes)

    # TMDB episodes from cache or fresh lookup
    tmdb_episodes: Optional[List[Dict]] = None
    tmdb_show_id: Optional[int] = None
    tmdb_cached = cache_get(svt_name)

    if tmdb_cached:
        tmdb_episodes = tmdb_cached.get("tmdb_episodes")
        tmdb_match_data = tmdb_cached.get("tmdb_match") or {}
        tmdb_show_id = tmdb_match_data.get("tmdb_id")
    elif tmdb_key and api_key:
        from svtplay._tmdb_api import search_show, get_all_episodes
        from svtplay._cache import put as cache_put
        from svtplay.tmdb import TMDBMatch, _llm_match

        svt_description = svt_match.get("description") or ""
        svt_episode_names = [ep.get("name", "") for ep in (svt_episodes or [])[:5] if ep.get("name")]
        candidates = search_show(svt_name, tmdb_key)[:10]

        if candidates:
            if len(candidates) == 1:
                c = candidates[0]
                tmdb_obj = TMDBMatch(
                    tmdb_id=c.get("id"), tmdb_name=c.get("name"),
                    original_name=c.get("original_name"), first_air_date=c.get("first_air_date"),
                    overview=c.get("overview"), confidence=1.0,
                    reasoning="Only one TMDB result; selected automatically.",
                )
            else:
                tmdb_obj = _llm_match(svt_name, svt_description, svt_episode_names, candidates, api_key)

            tmdb_match_dict = tmdb_obj.model_dump()
            tmdb_show_id = tmdb_match_dict.get("tmdb_id")
            if tmdb_show_id and tmdb_match_dict.get("confidence", 0) >= 0.90:
                tmdb_episodes = get_all_episodes(tmdb_show_id, tmdb_key)
            cache_put(svt_name, {"svt_name": svt_name, "tmdb_match": tmdb_match_dict,
                                  "tmdb_episodes": tmdb_episodes})

    return {
        "show": svt_name,
        "svt_show_url": svt_show_url,
        "tmdb_show_id": tmdb_show_id,
        "files": [{"path": str(p), "filename": p.name} for p in file_paths],
        "svt_episodes": [
            {
                "svt_id": ep.get("svt_id"),
                "name": ep.get("name"),
                "url": ep.get("url"),
                "thumbnail_url": ep.get("thumbnail_url"),
                "air_date": ep.get("air_date"),
                "duration_seconds": ep.get("duration_seconds"),
            }
            for ep in (svt_episodes or [])
        ],
        "tmdb_episodes": tmdb_episodes,
        "instructions": (
            "You are an agent. Match each entry in 'files' to the best matching entries in "
            "'svt_episodes' (for svt_id, svt_url, thumbnail_url) and 'tmdb_episodes' (for "
            "season_number, episode_number). Use filename and episode name similarity. "
            "Then call svtplay-backfill-apply with a JSON object containing 'show' and 'matches' "
            "(list of match dicts with keys: file, svt_id, svt_url, season, episode, "
            "episode_title, air_date, thumbnail_url, tmdb_show_id)."
        ),
    }


# ─── backfill_apply ───────────────────────────────────────────────────────────

def backfill_apply(
    show: str,
    matches: List[Dict[str, Any]],
    dry_run: bool = False,
    no_rename: bool = False,
) -> Dict[str, Any]:
    """Embed metadata into video files based on agent-provided match decisions.

    Returns: {show, processed: [...], errors: [...], dry_run}
    """
    from svtplay._dl_cache import add_entry

    results = []
    errors = []

    for m in matches:
        file_path = Path(m.get("file", ""))
        if not file_path.exists():
            errors.append({"file": str(file_path), "error": "File not found"})
            continue

        svt_id: Optional[str] = m.get("svt_id")
        svt_url: Optional[str] = m.get("svt_url")
        season: Optional[int] = m.get("season")
        episode_num: Optional[int] = m.get("episode")
        episode_title: str = m.get("episode_title") or file_path.stem
        air_date: Optional[str] = m.get("air_date")
        thumbnail_url: Optional[str] = m.get("thumbnail_url")
        tmdb_show_id: Optional[int] = m.get("tmdb_show_id")

        canonical = episode_filename(episode_title, show, season, episode_num, ext=file_path.suffix)
        new_path = file_path.parent / canonical

        if dry_run:
            results.append({"file": str(file_path),
                             "would_rename_to": str(new_path) if not no_rename else None,
                             "season": season, "episode": episode_num})
            continue

        try:
            embed(
                file_path,
                title=episode_title,
                show=show,
                season=season,
                episode=episode_num,
                air_date=air_date,
                svt_id=svt_id,
                svt_url=svt_url,
                tmdb_show_id=tmdb_show_id,
                thumbnail_url=thumbnail_url,
            )
        except Exception as exc:
            errors.append({"file": str(file_path), "error": f"embed failed: {exc}"})

        if not no_rename and new_path != file_path and not new_path.exists():
            shutil.move(str(file_path), str(new_path))
            file_path = new_path

        if svt_id:
            try:
                add_entry(
                    show,
                    svt_id=svt_id,
                    filename=file_path.name,
                    season=season,
                    episode=episode_num,
                    episode_title=episode_title,
                    svt_url=svt_url,
                    tmdb_show_id=tmdb_show_id,
                )
            except Exception:
                pass

        results.append({
            "file": str(file_path),
            "season": season,
            "episode": episode_num,
            "episode_title": episode_title,
        })

    return {"show": show, "processed": results, "errors": errors, "dry_run": dry_run}
