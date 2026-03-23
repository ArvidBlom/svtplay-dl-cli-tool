"""svtplay-download — thin CLI wrapper."""

import json
import sys
from pathlib import Path
from typing import Optional

import click
from dotenv import load_dotenv

load_dotenv()

_DEFAULT_OUTPUT_DIR = Path.home() / "Downloads" / "svtplay-dl"


def _print_human(result: dict) -> None:
    if result.get("dry_run"):
        plan = result.get("would_download", [])
        show_dir = _DEFAULT_OUTPUT_DIR / result.get("show", "")
        print(f"\nWould download {len(plan)} episode(s) to: {show_dir}\n")
        for item in plan:
            print(f"  {item['filename']}")
            print(f"    {item['url']}")
        return
    downloaded = result.get("downloaded", [])
    failed = result.get("failed", [])
    skipped = result.get("skipped", 0)
    print(f"\nDone. Downloaded: {len(downloaded)}, failed: {len(failed)}, skipped: {skipped}")
    if failed:
        print(f"\nFailed downloads ({len(failed)}):", file=sys.stderr)
        for f in failed:
            print(f"  {f['name']}: {f['error']}", file=sys.stderr)


@click.command()
@click.argument("query")
@click.option("--output-dir", "-o", default=None, help="Output directory.")
@click.option("--tmdb-key", envvar="TMDB_API_KEY", default=None, help="TMDB API key.")
@click.option("--api-key", envvar="ANTHROPIC_API_KEY", default=None, help="Anthropic API key.")
@click.option("--dry-run", is_flag=True, help="Show what would be downloaded without downloading.")
@click.option("--all", "download_all", is_flag=True, help="Ignore cache and download all episodes.")
@click.option("--quality", default=None, help="Quality to pass to svtplay-dl (e.g. 1080).")
@click.option("--json", "as_json", is_flag=True, help="Machine-readable JSON output.")
@click.option("--threshold", default=0.55, show_default=True, help="SVT show match threshold.")
@click.option("--no-cache", "no_cache", is_flag=True, help="Skip TMDB cache and force fresh lookup.")
def main(
    query: str,
    output_dir: Optional[str],
    tmdb_key: Optional[str],
    api_key: Optional[str],
    dry_run: bool,
    download_all: bool,
    quality: Optional[str],
    as_json: bool,
    threshold: float,
    no_cache: bool,
) -> None:
    """Download new episodes of a show from SVT Play."""
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")

    from svtplay.download import download_show

    try:
        result = download_show(
            query,
            output_dir=output_dir,
            api_key=api_key,
            tmdb_key=tmdb_key,
            download_all=download_all,
            quality=quality,
            dry_run=dry_run,
            threshold=threshold,
            no_cache=no_cache,
        )
    except ValueError as exc:
        click.echo(f"Error: {exc}", err=True)
        sys.exit(1)

    if as_json:
        json.dump(result, sys.stdout, ensure_ascii=False, indent=2)
        print()
    else:
        _print_human(result)

    if result.get("failed") and not as_json:
        sys.exit(1)
