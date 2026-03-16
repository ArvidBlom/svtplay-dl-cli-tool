"""svtplay-search — search SVT Play for shows and episodes."""

import json
import sys

import click
from dotenv import load_dotenv

load_dotenv()


@click.command()
@click.argument("query")
@click.option("--limit", default=10, show_default=True, help="Maximum results to show.")
@click.option("--shows-only", is_flag=True, help="Only return series/shows.")
@click.option("--json", "as_json", is_flag=True, help="Output as JSON.")
def main(query: str, limit: int, shows_only: bool, as_json: bool) -> None:
    """Search SVT Play for QUERY."""
    # Force UTF-8 output on Windows (Swedish characters)
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")

    from svtplay._svt import search as svt_search

    try:
        results = svt_search(query)
    except Exception as exc:
        if as_json:
            json.dump({"error": str(exc)}, sys.stdout, ensure_ascii=False)
            print()
        else:
            print(f"Error: {exc}", file=sys.stderr)
        sys.exit(1)

    if shows_only:
        results = [r for r in results if r.get("is_show")]

    results = results[:limit]

    if as_json:
        output = {"query": query, "count": len(results), "results": results}
        json.dump(output, sys.stdout, ensure_ascii=False, indent=2)
        print()
        return

    if not results:
        print(f"No results for '{query}'.")
        return

    for i, r in enumerate(results, 1):
        name = r.get("name") or ""
        kind = r.get("type") or ""
        desc = r.get("short_description") or r.get("description") or ""
        url = r.get("url") or ""

        # Truncate long descriptions
        if len(desc) > 80:
            desc = desc[:77] + "..."

        kind_tag = f"  [{kind}]" if kind else ""
        print(f"{i}. {name}{kind_tag}")
        if desc:
            print(f"   {desc}")
        if url:
            print(f"   {url}")
        print()
