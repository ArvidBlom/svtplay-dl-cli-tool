"""Plain-function SVT Play search."""

from typing import Any, Dict, List


def search(query: str, limit: int = 10, shows_only: bool = False) -> Dict[str, Any]:
    """Search SVT Play for shows matching *query*.

    Returns: {query, count, results: [{name, type, url, description, is_show, thumbnail_url}]}
    Raises ValueError on failure.
    """
    from svtplay._svt import search as svt_search

    try:
        results: List[Dict[str, Any]] = svt_search(query)
    except Exception as exc:
        raise ValueError(str(exc)) from exc

    if shows_only:
        results = [r for r in results if r.get("is_show")]

    results = results[:limit]
    return {"query": query, "count": len(results), "results": results}
