"""Plain-function SVT episode listing."""

from typing import Any, Dict, List, Optional


def list_episodes(query: str, threshold: float = 0.55) -> Dict[str, Any]:
    """Find a show matching *query* and return its episode list.

    Returns: {query, show: {name, url, match_score, type, description, thumbnail_url},
              episode_count, episodes: [...]}
    Raises ValueError if no show found or fetch fails.
    """
    from svtplay._svt import find_show, fetch_show_episodes
    from svtplay._cache import get_svt_episodes, patch_svt_episodes

    result = find_show(query, match_threshold=threshold, shows_only=True)
    match = result.get("match")

    if not match:
        suggestions: List[Optional[str]] = [s.get("name") for s in result.get("suggestions", [])]
        raise ValueError(
            f"No show found for '{query}'."
            + (f" Suggestions: {', '.join(s for s in suggestions if s)}" if suggestions else "")
        )

    show_url: str = match.get("url", "")
    show_name: str = match.get("name", "")
    match_score: float = result.get("match_score", 0)

    episodes = get_svt_episodes(show_name)
    if episodes is None:
        try:
            episodes = fetch_show_episodes(show_url)
        except Exception as exc:
            raise ValueError(f"Failed to fetch episodes: {exc}") from exc
        if episodes:
            patch_svt_episodes(show_name, episodes)

    episodes = episodes or []
    return {
        "query": query,
        "show": {
            "name": show_name,
            "url": show_url,
            "match_score": round(match_score, 3),
            "type": match.get("type"),
            "description": match.get("description"),
            "thumbnail_url": match.get("thumbnail_url"),
        },
        "episode_count": len(episodes),
        "episodes": episodes,
    }
