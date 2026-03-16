"""svtplay-tmdb — find the TMDB entry for an SVT Play show using LLM matching."""

import json
import os
import sys
from typing import Any, Dict, List, Optional

import click
from dotenv import load_dotenv
from pydantic import BaseModel

load_dotenv()


# ─── Pydantic model ────────────────────────────────────────────────────────────

class TMDBMatch(BaseModel):
    tmdb_id: Optional[int]         # None if no confident match found
    tmdb_name: Optional[str]
    original_name: Optional[str]
    first_air_date: Optional[str]
    overview: Optional[str]
    confidence: float              # 0.0 – 1.0
    reasoning: str                 # one-sentence explanation


# ─── LLM matching ─────────────────────────────────────────────────────────────

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
                "tmdb_id": {
                    "type": ["integer", "null"],
                    "description": "TMDB show ID, or null if no match",
                },
                "tmdb_name": {"type": ["string", "null"], "description": "TMDB show name"},
                "original_name": {"type": ["string", "null"], "description": "TMDB original name"},
                "first_air_date": {"type": ["string", "null"], "description": "First air date from TMDB"},
                "overview": {"type": ["string", "null"], "description": "TMDB show overview"},
                "confidence": {
                    "type": "number",
                    "description": "Confidence of the match, 0.0 to 1.0",
                },
                "reasoning": {
                    "type": "string",
                    "description": "One sentence explaining the match decision",
                },
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


# ─── CLI ───────────────────────────────────────────────────────────────────────

@click.command()
@click.argument("query")
@click.option("--json", "as_json", is_flag=True, help="Output as JSON.")
@click.option("--api-key", envvar="ANTHROPIC_API_KEY", help="Anthropic API key.")
@click.option("--tmdb-key", envvar="TMDB_API_KEY", help="TMDB API key.")
@click.option("--no_cache", is_flag=True, help="Skip cache and force fresh lookup.")
@click.option("--threshold", default=0.55, show_default=True, help="SVT show match threshold.")
def main(
    query: str,
    as_json: bool,
    api_key: Optional[str],
    tmdb_key: Optional[str],
    no_cache: bool,
    threshold: float,
) -> None:
    """Find the TMDB entry for an SVT Play show using LLM-assisted matching."""
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")

    from svtplay._svt import find_show, fetch_show_episodes
    from svtplay._tmdb_api import search_show
    from svtplay._cache import get as cache_get, put as cache_put, get_svt_episodes, patch_svt_episodes

    # Validate API keys
    if not tmdb_key:
        _err(as_json, "TMDB_API_KEY not set. Use --tmdb-key or set the env var.")
        sys.exit(1)
    if not api_key:
        _err(as_json, "ANTHROPIC_API_KEY not set. Use --api-key or set the env var.")
        sys.exit(1)

    # Step 1: find SVT show
    result = find_show(query, match_threshold=threshold, shows_only=True)
    match = result.get("match")
    if not match:
        _err(as_json, f"No SVT Play show found for '{query}'.")
        sys.exit(1)

    svt_name = match.get("name", "")
    svt_url = match.get("url", "")
    svt_description = match.get("description") or match.get("short_description") or ""
    svt_match_score = result.get("match_score", 0)

    svt_show = {
        "name": svt_name,
        "url": svt_url,
        "description": svt_description,
        "match_score": round(svt_match_score, 3),
    }

    # Step 2: check cache
    if not no_cache:
        cached = cache_get(svt_name)
        if cached:
            tmdb_match = cached.get("tmdb_match")
            tmdb_episodes = cached.get("tmdb_episodes")
            if as_json:
                _out_json({"query": query, "svt_show": svt_show, "tmdb_match": tmdb_match,
                           "tmdb_episodes": tmdb_episodes, "cached": True})
            else:
                _print_human(svt_show, tmdb_match, tmdb_episodes, cached=True)
            return

    # Step 3: fetch SVT episodes for context (cache first, then live)
    all_svt_episodes = get_svt_episodes(svt_name)
    if all_svt_episodes is None:
        try:
            all_svt_episodes = fetch_show_episodes(svt_url)
        except Exception:
            all_svt_episodes = []
        if all_svt_episodes:
            patch_svt_episodes(svt_name, all_svt_episodes)
    svt_episode_names = [ep.get("name", "") for ep in all_svt_episodes[:5] if ep.get("name")]

    # Step 4: search TMDB
    try:
        candidates = search_show(svt_name, tmdb_key)[:10]
    except Exception as exc:
        _err(as_json, f"TMDB search failed: {exc}")
        sys.exit(1)

    if not candidates:
        tmdb_match_obj = TMDBMatch(
            tmdb_id=None, tmdb_name=None, original_name=None,
            first_air_date=None, overview=None,
            confidence=0.0, reasoning="No TMDB results found for this title.",
        )
    elif len(candidates) == 1:
        c = candidates[0]
        tmdb_match_obj = TMDBMatch(
            tmdb_id=c.get("id"),
            tmdb_name=c.get("name"),
            original_name=c.get("original_name"),
            first_air_date=c.get("first_air_date"),
            overview=c.get("overview"),
            confidence=1.0,
            reasoning="Only one TMDB result returned; selected automatically.",
        )
    else:
        # Step 5: LLM match
        if not as_json:
            print(f"Asking Claude to match '{svt_name}' against {len(candidates)} TMDB candidates...", file=sys.stderr)
        try:
            tmdb_match_obj = _llm_match(svt_name, svt_description, svt_episode_names, candidates, api_key)
        except Exception as exc:
            _err(as_json, f"LLM matching failed: {exc}")
            sys.exit(1)

    tmdb_match = tmdb_match_obj.model_dump()

    # Step 6: fetch all TMDB episodes if match is confident enough
    tmdb_episodes = None
    tmdb_id = tmdb_match.get("tmdb_id")
    if tmdb_id and tmdb_match.get("confidence", 0) >= 0.90:
        if not as_json:
            print(f"Fetching all TMDB episodes for show id={tmdb_id}...", file=sys.stderr)
        try:
            from svtplay._tmdb_api import get_all_episodes
            tmdb_episodes = get_all_episodes(tmdb_id, tmdb_key)
        except Exception as exc:
            if not as_json:
                print(f"Warning: could not fetch TMDB episodes: {exc}", file=sys.stderr)

    # Step 7: cache result
    cache_put(svt_name, {"svt_name": svt_name, "tmdb_match": tmdb_match, "tmdb_episodes": tmdb_episodes})

    # Step 8: output
    if as_json:
        _out_json({"query": query, "svt_show": svt_show, "tmdb_match": tmdb_match,
                   "tmdb_episodes": tmdb_episodes, "cached": False})
    else:
        _print_human(svt_show, tmdb_match, tmdb_episodes, cached=False)


# ─── Output helpers ────────────────────────────────────────────────────────────

def _out_json(data: Dict[str, Any]) -> None:
    json.dump(data, sys.stdout, ensure_ascii=False, indent=2)
    print()


def _err(as_json: bool, msg: str) -> None:
    if as_json:
        json.dump({"error": msg}, sys.stdout, ensure_ascii=False)
        print()
    else:
        print(f"Error: {msg}", file=sys.stderr)


def _print_human(svt_show: Dict, tmdb_match: Optional[Dict], tmdb_episodes: Optional[List], cached: bool) -> None:
    cache_tag = "  (cached)" if cached else ""
    print(f"SVT show : {svt_show['name']}  ({svt_show['url']})")
    if not tmdb_match or tmdb_match.get("tmdb_id") is None:
        print("TMDB     : no match found")
        return
    ep_count = f"  {len(tmdb_episodes)} episodes" if tmdb_episodes else ""
    print(f"TMDB     : {tmdb_match['tmdb_name']}  (id={tmdb_match['tmdb_id']}){ep_count}{cache_tag}")
    if tmdb_match.get("original_name") and tmdb_match["original_name"] != tmdb_match["tmdb_name"]:
        print(f"Original : {tmdb_match['original_name']}")
    if tmdb_match.get("first_air_date"):
        print(f"First air: {tmdb_match['first_air_date']}")
    print(f"Confidence: {tmdb_match['confidence']:.0%}")
    print(f"Reasoning: {tmdb_match['reasoning']}")
    if tmdb_match.get("overview"):
        overview = tmdb_match["overview"]
        if len(overview) > 120:
            overview = overview[:117] + "..."
        print(f"Overview : {overview}")
