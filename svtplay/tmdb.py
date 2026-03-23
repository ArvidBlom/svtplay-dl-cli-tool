"""TMDB matching — plain functions + shared model used by download/backfill."""

from typing import Any, Dict, List, Optional

from pydantic import BaseModel


# ─── Shared model ──────────────────────────────────────────────────────────────

class TMDBMatch(BaseModel):
    tmdb_id: Optional[int]
    tmdb_name: Optional[str]
    original_name: Optional[str]
    first_air_date: Optional[str]
    overview: Optional[str]
    confidence: float
    reasoning: str


# ─── LLM matching (shared helper) ─────────────────────────────────────────────

def _llm_match(
    svt_name: str,
    svt_description: str,
    svt_episode_names: List[str],
    candidates: List[Dict[str, Any]],
    api_key: str,
) -> TMDBMatch:
    """Call Claude to pick the correct TMDB candidate for the SVT show."""
    import anthropic

    candidate_lines = "\n".join(
        f"  [{i+1}] id={c.get('id')}  name={c.get('name')!r}"
        f"  original={c.get('original_name')!r}"
        f"  first_air={c.get('first_air_date', '')[:4]}"
        f"  overview={str(c.get('overview',''))[:120]}"
        for i, c in enumerate(candidates)
    )

    episode_list = ", ".join(f'"{n}"' for n in svt_episode_names) if svt_episode_names else "(none)"

    user_message = f"""SVT Play show to match:
  Name: {svt_name!r}
  Description: {svt_description or '(none)'}
  First episodes on SVT: {episode_list}

TMDB candidates:
{candidate_lines}

Which TMDB candidate is the same show as the SVT Play show above?
Pick the best match, or set tmdb_id to null if none of the candidates match.
"""

    tool_schema = {
        "name": "record_match",
        "description": "Record the TMDB match result",
        "input_schema": {
            "type": "object",
            "properties": {
                "tmdb_id": {"type": ["integer", "null"], "description": "TMDB show ID, or null if no match"},
                "tmdb_name": {"type": ["string", "null"], "description": "TMDB show name"},
                "original_name": {"type": ["string", "null"], "description": "TMDB original name"},
                "first_air_date": {"type": ["string", "null"], "description": "First air date from TMDB"},
                "overview": {"type": ["string", "null"], "description": "TMDB show overview"},
                "confidence": {"type": "number", "description": "Confidence of the match, 0.0 to 1.0"},
                "reasoning": {"type": "string", "description": "One sentence explaining the match decision"},
            },
            "required": ["tmdb_id", "tmdb_name", "original_name", "first_air_date",
                         "overview", "confidence", "reasoning"],
        },
    }

    client = anthropic.Anthropic(api_key=api_key)
    response = client.messages.create(
        model="claude-haiku-4-5-20251001",
        max_tokens=512,
        system=(
            "You are a TV show metadata expert. "
            "You match Swedish streaming show listings to their TMDB database entries. "
            "SVT Play often uses Swedish titles for internationally produced shows."
        ),
        messages=[{"role": "user", "content": user_message}],
        tools=[tool_schema],
        tool_choice={"type": "tool", "name": "record_match"},
    )

    for block in response.content:
        if block.type == "tool_use" and block.name == "record_match":
            return TMDBMatch(**block.input)

    raise RuntimeError("Claude did not return a tool_use block")


# ─── Public plain function ─────────────────────────────────────────────────────

def match_tmdb(
    query: str,
    api_key: str,
    tmdb_key: str,
    no_cache: bool = False,
    threshold: float = 0.55,
) -> Dict[str, Any]:
    """Find the TMDB entry for an SVT Play show using LLM-assisted matching.

    Returns: {query, svt_show, tmdb_match, tmdb_episodes, cached}
    Raises ValueError on failure.
    """
    from svtplay._svt import find_show, fetch_show_episodes
    from svtplay._tmdb_api import search_show, get_all_episodes
    from svtplay._cache import get as cache_get, put as cache_put, get_svt_episodes, patch_svt_episodes

    # Find SVT show
    result = find_show(query, match_threshold=threshold, shows_only=True)
    match = result.get("match")
    if not match:
        raise ValueError(f"No SVT Play show found for '{query}'.")

    svt_name: str = match.get("name", "")
    svt_url: str = match.get("url", "")
    svt_description: str = match.get("description") or match.get("short_description") or ""

    svt_show = {
        "name": svt_name,
        "url": svt_url,
        "description": svt_description,
        "match_score": round(result.get("match_score", 0), 3),
    }

    # Check cache
    if not no_cache:
        cached = cache_get(svt_name)
        if cached:
            return {
                "query": query,
                "svt_show": svt_show,
                "tmdb_match": cached.get("tmdb_match"),
                "tmdb_episodes": cached.get("tmdb_episodes"),
                "cached": True,
            }

    # Fetch SVT episodes for LLM context
    all_svt_episodes = get_svt_episodes(svt_name)
    if all_svt_episodes is None:
        try:
            all_svt_episodes = fetch_show_episodes(svt_url)
        except Exception:
            all_svt_episodes = []
        if all_svt_episodes:
            patch_svt_episodes(svt_name, all_svt_episodes)
    svt_episode_names = [ep.get("name", "") for ep in (all_svt_episodes or [])[:5] if ep.get("name")]

    # Search TMDB
    try:
        candidates = search_show(svt_name, tmdb_key)[:10]
    except Exception as exc:
        raise ValueError(f"TMDB search failed: {exc}") from exc

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
        except Exception as exc:
            raise ValueError(f"LLM matching failed: {exc}") from exc

    tmdb_match = tmdb_match_obj.model_dump()

    # Fetch all TMDB episodes if confident enough
    tmdb_episodes = None
    tmdb_id = tmdb_match.get("tmdb_id")
    if tmdb_id and tmdb_match.get("confidence", 0) >= 0.90:
        try:
            tmdb_episodes = get_all_episodes(tmdb_id, tmdb_key)
        except Exception:
            pass

    cache_put(svt_name, {"svt_name": svt_name, "tmdb_match": tmdb_match, "tmdb_episodes": tmdb_episodes})

    return {
        "query": query,
        "svt_show": svt_show,
        "tmdb_match": tmdb_match,
        "tmdb_episodes": tmdb_episodes,
        "cached": False,
    }
