"""svtplay-download-missing — download episodes not already in a local folder."""

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
        print(f"\nWould download {len(plan)} episode(s)  (skipped {result.get('skipped', 0)} already on disk)\n")
        for item in plan:
            print(f"  {item['filename']}")
            print(f"    {item['url']}")
        return
    downloaded = result.get("downloaded", [])
    failed = result.get("failed", [])
    skipped_eps = result.get("skipped_episodes", [])
    print(f"\nDone. Downloaded: {len(downloaded)}, failed: {len(failed)}, skipped: {len(skipped_eps)}")
    if skipped_eps:
        print("\nSkipped (already on disk):")
        for ep in skipped_eps:
            print(f"  {ep['name']}")
    if failed:
        print(f"\nFailed ({len(failed)}):", file=sys.stderr)
        for f in failed:
            print(f"  {f['name']}: {f['error']}", file=sys.stderr)


def _infer_show(folder: str) -> str:
    """Infer show name from embedded tvsh metadata, falling back to folder name."""
    from svtplay.meta import read_meta

    folder_path = Path(folder)
    for f in sorted(folder_path.iterdir()):
        if f.suffix.lower() in {".mp4", ".m4v", ".mkv", ".mov"}:
            try:
                result = read_meta(str(f))
                tvsh = result.get("tags", {}).get("tvsh")
                if tvsh:
                    return tvsh
            except Exception:
                continue
    return folder_path.name


@click.command()
@click.argument("folder", type=click.Path(exists=True, file_okay=False))
@click.argument("show", required=False, default=None)
@click.option("--output-dir", "-o", default=None, help="Output directory (default: same as FOLDER's parent).")
@click.option("--tmdb-key", envvar="TMDB_API_KEY", default=None, help="TMDB API key.")
@click.option("--api-key", envvar="ANTHROPIC_API_KEY", default=None, help="Anthropic API key.")
@click.option("--dry-run", is_flag=True, help="Show what would be downloaded without downloading.")
@click.option("--quality", default=None, help="Quality to pass to svtplay-dl (e.g. 1080).")
@click.option("--json", "as_json", is_flag=True, help="Machine-readable JSON output.")
@click.option("--no-cache", "no_cache", is_flag=True, help="Skip TMDB cache and force fresh lookup.")
def main(
    folder: str,
    show: Optional[str],
    output_dir: Optional[str],
    tmdb_key: Optional[str],
    api_key: Optional[str],
    dry_run: bool,
    quality: Optional[str],
    as_json: bool,
    no_cache: bool,
) -> None:
    """Download episodes of SHOW that are on SVT Play but missing from FOLDER.

    SHOW is optional — if omitted, the show name is read from the tvsh metadata
    tag of existing files in FOLDER, falling back to the folder name itself.

    Uses SVT_URL embedded in local file metadata as ground truth — no
    fragile filename matching.
    """
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")

    if not show:
        show = _infer_show(folder)
        click.echo(f"Inferred show: {show}", err=True)

    # Default output dir: same parent as the folder being scanned
    resolved_output = output_dir or str(Path(folder).parent)

    from svtplay.download import download_missing

    try:
        result = download_missing(
            folder,
            show,
            output_dir=resolved_output,
            api_key=api_key,
            tmdb_key=tmdb_key,
            quality=quality,
            dry_run=dry_run,
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
