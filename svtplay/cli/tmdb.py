"""svtplay-tmdb — thin CLI wrapper."""

import json
import sys
from typing import Dict, List, Optional

import click
from dotenv import load_dotenv

load_dotenv()


def _print_human(result: dict) -> None:
    svt = result["svt_show"]
    tmdb = result.get("tmdb_match") or {}
    tmdb_episodes = result.get("tmdb_episodes")
    cached = result.get("cached", False)
    cache_tag = "  (cached)" if cached else ""

    print(f"SVT show : {svt['name']}  ({svt['url']})")
    if not tmdb or tmdb.get("tmdb_id") is None:
        print("TMDB     : no match found")
        return
    ep_count = f"  {len(tmdb_episodes)} episodes" if tmdb_episodes else ""
    print(f"TMDB     : {tmdb['tmdb_name']}  (id={tmdb['tmdb_id']}){ep_count}{cache_tag}")
    if tmdb.get("original_name") and tmdb["original_name"] != tmdb["tmdb_name"]:
        print(f"Original : {tmdb['original_name']}")
    if tmdb.get("first_air_date"):
        print(f"First air: {tmdb['first_air_date']}")
    print(f"Confidence: {tmdb['confidence']:.0%}")
    print(f"Reasoning: {tmdb['reasoning']}")
    if tmdb.get("overview"):
        overview = tmdb["overview"]
        if len(overview) > 120:
            overview = overview[:117] + "..."
        print(f"Overview : {overview}")


@click.command()
@click.argument("query")
@click.option("--json", "as_json", is_flag=True, help="Output as JSON.")
@click.option("--api-key", envvar="ANTHROPIC_API_KEY", help="Anthropic API key.")
@click.option("--tmdb-key", envvar="TMDB_API_KEY", help="TMDB API key.")
@click.option("--no-cache", "no_cache", is_flag=True, help="Skip cache and force fresh lookup.")
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

    from svtplay.tmdb import match_tmdb

    if not tmdb_key:
        click.echo("Error: TMDB_API_KEY not set. Use --tmdb-key or set the env var.", err=True)
        sys.exit(1)
    if not api_key:
        click.echo("Error: ANTHROPIC_API_KEY not set. Use --api-key or set the env var.", err=True)
        sys.exit(1)

    try:
        result = match_tmdb(query, api_key=api_key, tmdb_key=tmdb_key,
                            no_cache=no_cache, threshold=threshold)
    except ValueError as exc:
        click.echo(f"Error: {exc}", err=True)
        sys.exit(1)

    if as_json:
        json.dump(result, sys.stdout, ensure_ascii=False, indent=2)
        print()
    else:
        _print_human(result)
