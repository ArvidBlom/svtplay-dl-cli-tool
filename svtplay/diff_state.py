"""Three-way episode diff: local files vs SVT Play vs TMDB."""

from typing import Any, Dict, List, Optional, Tuple


def _local_map(episodes: List[Dict]) -> Dict[Tuple[int, int], Dict]:
    """Index local episode records by (season, episode)."""
    result = {}
    for ep in episodes:
        s, e = ep.get("season"), ep.get("episode")
        if s is not None and e is not None:
            result[(int(s), int(e))] = ep
    return result


def diff_show(
    folder: str,
    show_query: str,
    tmdb_api_key: str,
    *,
    svt_url: Optional[str] = None,
) -> Dict[str, Any]:
    """Three-way diff for a show against local folder, SVT Play, and TMDB.

    Returns::

        {
            "show_name": str,
            "svt_url": str | None,
            "tmdb_show_id": int | None,
            "tmdb_show_name": str | None,
            "episodes": [
                {
                    "season": int,
                    "episode": int,
                    "title": str,
                    "air_date": str | None,
                    "local": bool,
                    "local_file": str | None,
                    "svt_available": bool,
                    "svt_id": str | None,
                }
            ],
            "summary": {
                "total_tmdb": int,
                "have_locally": int,
                "available_on_svt": int,
                "missing_downloadable": int,
                "missing_gone": int,
            },
        }
    """
    from svtplay.scan import scan_folder
    from svtplay._svt import find_show, fetch_show_episodes
    from svtplay._tmdb_api import get_all_episodes
    from svtplay._match import match_episodes
    from svtplay import _cache

    # ── 1. Scan local folder ──────────────────────────────────────────────────
    scan = scan_folder(folder)

    local_show: Optional[Dict] = None
    matched_show_name: Optional[str] = None
    query_lower = show_query.lower()
    for name, data in scan["shows"].items():
        if name.lower() == query_lower or query_lower in name.lower():
            local_show = data
            matched_show_name = name
            break

    local_episodes: List[Dict] = local_show["episodes"] if local_show else []
    local_tmdb_id: Optional[int] = local_show["tmdb_show_id"] if local_show else None

    # ── 2. SVT Play ───────────────────────────────────────────────────────────
    actual_svt_url: Optional[str] = svt_url
    svt_show_name: Optional[str] = None

    if not actual_svt_url:
        found = find_show(show_query, shows_only=True)
        match = found.get("match")
        actual_svt_url = match["url"] if match else None
        svt_show_name = match["name"] if match else None

    cache_key = svt_show_name or matched_show_name or show_query

    svt_episodes: List[Dict] = []
    if actual_svt_url:
        cached_svt = _cache.get_svt_episodes(cache_key)
        if cached_svt is not None:
            svt_episodes = cached_svt
        else:
            svt_episodes = fetch_show_episodes(actual_svt_url)
            _cache.patch_svt_episodes(cache_key, svt_episodes)

    # ── 3. TMDB ───────────────────────────────────────────────────────────────
    tmdb_show_id: Optional[int] = local_tmdb_id
    tmdb_show_name: Optional[str] = None
    tmdb_all_episodes: List[Dict] = []

    cached = _cache.get(cache_key)
    if cached:
        tmdb_match = cached.get("tmdb_match") or {}
        if not tmdb_show_id:
            tmdb_show_id = tmdb_match.get("tmdb_id")
        tmdb_show_name = tmdb_match.get("tmdb_name")
        tmdb_all_episodes = cached.get("tmdb_episodes") or []

    if not tmdb_all_episodes and tmdb_show_id:
        tmdb_all_episodes = get_all_episodes(tmdb_show_id, tmdb_api_key)

    # ── 4. Match SVT episodes → TMDB S/E numbers ─────────────────────────────
    svt_se_map: Dict[Tuple[int, int], str] = {}  # (season, episode) → svt_id

    if svt_episodes and tmdb_all_episodes:
        svt_to_se = match_episodes(svt_episodes, tmdb_all_episodes)
        for svt_ep in svt_episodes:
            svt_id = svt_ep.get("svt_id")
            se = svt_to_se.get(svt_id, (None, None))
            if se[0] is not None and se[1] is not None:
                svt_se_map[(se[0], se[1])] = svt_id

    # ── 5. Build three-way table ──────────────────────────────────────────────
    local_index = _local_map(local_episodes)
    episodes_out: List[Dict] = []

    for tmdb_ep in tmdb_all_episodes:
        s = tmdb_ep.get("season_number")
        e = tmdb_ep.get("episode_number")
        if s is None or e is None:
            continue
        key = (int(s), int(e))
        local_rec = local_index.get(key)
        svt_id = svt_se_map.get(key)
        episodes_out.append(
            {
                "season": s,
                "episode": e,
                "title": tmdb_ep.get("name") or "",
                "air_date": tmdb_ep.get("air_date"),
                "local": local_rec is not None,
                "local_file": local_rec["file"] if local_rec else None,
                "svt_available": svt_id is not None,
                "svt_id": svt_id,
            }
        )

    have_locally = sum(1 for ep in episodes_out if ep["local"])
    available_on_svt = sum(1 for ep in episodes_out if ep["svt_available"])
    missing_downloadable = sum(
        1 for ep in episodes_out if not ep["local"] and ep["svt_available"]
    )
    missing_gone = sum(
        1 for ep in episodes_out if not ep["local"] and not ep["svt_available"]
    )

    return {
        "show_name": matched_show_name or show_query,
        "svt_url": actual_svt_url,
        "tmdb_show_id": tmdb_show_id,
        "tmdb_show_name": tmdb_show_name,
        "episodes": episodes_out,
        "summary": {
            "total_tmdb": len(episodes_out),
            "have_locally": have_locally,
            "available_on_svt": available_on_svt,
            "missing_downloadable": missing_downloadable,
            "missing_gone": missing_gone,
        },
    }
