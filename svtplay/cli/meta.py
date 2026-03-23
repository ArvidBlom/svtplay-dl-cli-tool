"""svtplay-meta — thin CLI wrapper."""

import json
import sys
from pathlib import Path

import click
from dotenv import load_dotenv

load_dotenv()


def _print_human(result: dict, missing_only: bool) -> None:
    path = Path(result["file"])
    tags = result["tags"]
    missing = result["missing"]

    if missing_only:
        if missing:
            print(f"{path.name}: missing {', '.join(missing)}")
        else:
            print(f"{path.name}: all fields present")
        return

    dur = tags.get("_duration_seconds", 0)
    print(f"File    : {path.name}")
    print(f"Size    : {path.stat().st_size // (1024*1024):.1f} MB")
    print(f"Duration: {dur // 60}m {dur % 60}s  |  {tags.get('_bitrate_kbps', '?')} kbps")
    print()

    rows = [
        ("Title",       tags.get("©nam")),
        ("Show",        tags.get("tvsh")),
        ("Season",      tags.get("tvsn")),
        ("Episode",     tags.get("tves")),
        ("Episode ID",  tags.get("tven")),
        ("Network",     tags.get("tvnn")),
        ("Air date",    tags.get("©day")),
        ("Cover art",   tags.get("covr")),
        ("Description", tags.get("desc")),
    ]
    for label, val in rows:
        status = str(val) if val is not None else "— (missing)"
        print(f"  {label:<12}: {status}")

    print()
    print("  Custom fields:")
    freeform = {
        "SVT ID":       tags.get("----:com.apple.iTunes:SVT_ID"),
        "SVT URL":      tags.get("----:com.apple.iTunes:SVT_URL"),
        "TMDB show ID": tags.get("----:com.apple.iTunes:TMDB_SHOW_ID"),
    }
    for label, val in freeform.items():
        if isinstance(val, list):
            val = val[0] if val else None
        status = str(val) if val is not None else "— (missing)"
        print(f"  {label:<12}: {status}")

    print()
    if missing:
        print(f"  Needs backfill : YES  (missing: {', '.join(missing)})")
    else:
        print(f"  Needs backfill : no")


@click.command()
@click.argument("file", type=click.Path(exists=True, dir_okay=False))
@click.option("--json", "as_json", is_flag=True, help="Output as JSON.")
@click.option("--missing-only", is_flag=True, help="Only print fields that are absent.")
def main(file: str, as_json: bool, missing_only: bool) -> None:
    """Display metadata embedded in a video FILE."""
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")

    from svtplay.meta import read_meta

    try:
        result = read_meta(file)
    except ValueError as exc:
        if as_json:
            json.dump({"error": str(exc), "file": file}, sys.stdout, ensure_ascii=False)
            print()
        else:
            click.echo(f"Error reading {Path(file).name}: {exc}", err=True)
        sys.exit(1)

    if as_json:
        json.dump(result, sys.stdout, ensure_ascii=False, indent=2)
        print()
    else:
        _print_human(result, missing_only)
