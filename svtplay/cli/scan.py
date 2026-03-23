"""svtplay-scan — scan a folder and dump embedded metadata as JSON."""

import json
import sys

import click
from dotenv import load_dotenv

load_dotenv()


@click.command()
@click.argument("folder", type=click.Path(exists=True, file_okay=False))
@click.option("--show", default=None, help="Filter output to a single show name.")
@click.option("--no-recursive", is_flag=True, help="Only scan top-level folder.")
def main(folder: str, show: str, no_recursive: bool) -> None:
    """Scan FOLDER for .mp4 files and dump embedded metadata as JSON."""
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")

    from svtplay.scan import scan_folder

    result = scan_folder(folder, recursive=not no_recursive)

    if show:
        show_lower = show.lower()
        result["shows"] = {
            k: v for k, v in result["shows"].items() if show_lower in k.lower()
        }

    json.dump(result, sys.stdout, ensure_ascii=False, indent=2)
    print()
