"""svtplay-episodes — list all episodes of a show on SVT Play."""

import json
import sys

import click
from dotenv import load_dotenv

load_dotenv()


@click.command()
@click.argument("query")
@click.option("--json", "as_json", is_flag=True, help="Output as JSON.")
@click.option("--threshold", default=0.55, show_default=True, help="Match confidence threshold (0-1).")
def main(query: str, as_json: bool, threshold: float) -> None:
    """Find a show matching QUERY and list all its episodes."""
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")

    from svtplay._svt import find_show, fetch_show_episodes
    from svtplay._cache import get_svt_episodes, patch_svt_episodes

    # Step 1: find best-matching show
    result = find_show(query, match_threshold=threshold, shows_only=True)
    match = result.get("match")

    if not match:
        suggestions = result.get("suggestions", [])
        if as_json:
            json.dump({"error": f"No show found for '{query}'", "suggestions": [s.get("name") for s in suggestions]}, sys.stdout, ensure_ascii=False)
            print()
        else:
            print(f"No show found for '{query}'.", file=sys.stderr)
            if suggestions:
                print("Did you mean:", file=sys.stderr)
                for s in suggestions:
                    print(f"  - {s.get('name')} ({s.get('url')})", file=sys.stderr)
        sys.exit(1)

    show_url = match.get("url", "")
    show_name = match.get("name", "")
    match_score = result.get("match_score", 0)

    # Step 2: fetch episodes (cache first, then live)
    episodes = get_svt_episodes(show_name)
    if episodes is None:
        try:
            episodes = fetch_show_episodes(show_url)
        except Exception as exc:
            if as_json:
                json.dump({"error": str(exc)}, sys.stdout, ensure_ascii=False)
                print()
            else:
                print(f"Error fetching episodes: {exc}", file=sys.stderr)
            sys.exit(1)
        if episodes:
            patch_svt_episodes(show_name, episodes)

    if as_json:
        output = {
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
        json.dump(output, sys.stdout, ensure_ascii=False, indent=2)
        print()
        return

    # Human-readable output
    print(f"Show: {show_name}  (matched {round(match_score * 100)}%, {show_url})")
    print(f"Episodes: {len(episodes)}")
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
