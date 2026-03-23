"""svtplay-backfill-info / svtplay-backfill-apply — thin CLI wrappers."""

import json
import sys
from typing import Optional

import click
from dotenv import load_dotenv

load_dotenv()


@click.command(name="svtplay-backfill-info")
@click.argument("show")
@click.option("--files", "-f", multiple=True, type=click.Path(exists=True),
              help="Specific video files to backfill.")
@click.option("--dir", "-d", "scan_dir", default=None, type=click.Path(exists=True),
              help="Scan this directory for video files.")
@click.option("--tmdb-key", envvar="TMDB_API_KEY", default=None, help="TMDB API key.")
@click.option("--api-key", envvar="ANTHROPIC_API_KEY", default=None, help="Anthropic API key.")
@click.option("--threshold", default=0.55, show_default=True, help="SVT show match threshold.")
def info(
    show: str,
    files: tuple,
    scan_dir: Optional[str],
    tmdb_key: Optional[str],
    api_key: Optional[str],
    threshold: float,
) -> None:
    """Output a JSON payload for agent-driven metadata backfill."""
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")

    from svtplay.backfill import backfill_info

    try:
        result = backfill_info(
            show,
            files=list(files),
            scan_dir=scan_dir,
            api_key=api_key,
            tmdb_key=tmdb_key,
            threshold=threshold,
        )
    except ValueError as exc:
        json.dump({"error": str(exc)}, sys.stdout, ensure_ascii=False)
        print()
        sys.exit(1)

    json.dump(result, sys.stdout, ensure_ascii=False, indent=2)
    print()


@click.command(name="svtplay-backfill-apply")
@click.argument("json_input", default="-")
@click.option("--dry-run", is_flag=True, help="Show what would change without modifying files.")
@click.option("--no-rename", is_flag=True, help="Embed metadata only, do not rename files.")
@click.option("--json", "as_json", is_flag=True, help="Machine-readable JSON output.")
def apply(
    json_input: str,
    dry_run: bool,
    no_rename: bool,
    as_json: bool,
) -> None:
    """Embed metadata into video files based on agent-provided match decisions."""
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")

    from svtplay.backfill import backfill_apply

    raw = sys.stdin.read() if json_input == "-" else json_input
    try:
        data = json.loads(raw)
    except json.JSONDecodeError as exc:
        click.echo(f"Error: Invalid JSON: {exc}", err=True)
        sys.exit(1)

    show_name: str = data.get("show", "")
    matches = data.get("matches", [])
    if not show_name or not matches:
        click.echo("Error: JSON must contain 'show' (string) and 'matches' (list).", err=True)
        sys.exit(1)

    result = backfill_apply(show_name, matches, dry_run=dry_run, no_rename=no_rename)

    if as_json:
        json.dump(result, sys.stdout, ensure_ascii=False, indent=2)
        print()
    else:
        print(f"\nDone. Processed: {len(result['processed'])}, errors: {len(result['errors'])}")

    if result["errors"] and not dry_run:
        sys.exit(1)
