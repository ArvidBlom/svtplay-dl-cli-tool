"""svtplay-episodes — thin CLI wrapper."""

import json
import sys

import click
from dotenv import load_dotenv

load_dotenv()


def _print_human(result: dict) -> None:
    show = result["show"]
    episodes = result["episodes"]
    print(f"Show: {show['name']}  (matched {round(show['match_score'] * 100)}%, {show['url']})")
    print(f"Episodes: {result['episode_count']}")
    print()
    for i, ep in enumerate(episodes, 1):
        name = ep.get("name") or ""
        sub = ep.get("sub_heading") or ""
        url = ep.get("url") or ""
        dur = ep.get("duration_seconds")
        dur_str = f"  ({dur // 60} min)" if dur else ""
        print(f"{i}. {name}{dur_str}")
        if sub:
            print(f"   {sub}")
        print(f"   {url}")
        print()


@click.command()
@click.argument("query")
@click.option("--json", "as_json", is_flag=True, help="Output as JSON.")
@click.option("--threshold", default=0.55, show_default=True, help="Match confidence threshold (0-1).")
def main(query: str, as_json: bool, threshold: float) -> None:
    """Find a show matching QUERY and list all its episodes."""
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")

    from svtplay.episodes import list_episodes

    try:
        result = list_episodes(query, threshold=threshold)
    except ValueError as exc:
        click.echo(f"Error: {exc}", err=True)
        sys.exit(1)

    if as_json:
        json.dump(result, sys.stdout, ensure_ascii=False, indent=2)
        print()
    else:
        _print_human(result)
