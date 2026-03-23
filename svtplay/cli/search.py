"""svtplay-search — thin CLI wrapper."""

import json
import sys

import click
from dotenv import load_dotenv

load_dotenv()


def _print_human(result: dict) -> None:
    results = result["results"]
    if not results:
        print(f"No results for '{result['query']}'.")
        return
    for i, r in enumerate(results, 1):
        name = r.get("name") or ""
        kind = r.get("type") or ""
        desc = r.get("short_description") or r.get("description") or ""
        url = r.get("url") or ""
        if len(desc) > 80:
            desc = desc[:77] + "..."
        kind_tag = f"  [{kind}]" if kind else ""
        print(f"{i}. {name}{kind_tag}")
        if desc:
            print(f"   {desc}")
        if url:
            print(f"   {url}")
        print()


@click.command()
@click.argument("query")
@click.option("--limit", default=10, show_default=True, help="Maximum results to show.")
@click.option("--shows-only", is_flag=True, help="Only return series/shows.")
@click.option("--json", "as_json", is_flag=True, help="Output as JSON.")
def main(query: str, limit: int, shows_only: bool, as_json: bool) -> None:
    """Search SVT Play for QUERY."""
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")

    from svtplay.search import search

    try:
        result = search(query, limit=limit, shows_only=shows_only)
    except ValueError as exc:
        click.echo(f"Error: {exc}", err=True)
        sys.exit(1)

    if as_json:
        json.dump(result, sys.stdout, ensure_ascii=False, indent=2)
        print()
    else:
        _print_human(result)
