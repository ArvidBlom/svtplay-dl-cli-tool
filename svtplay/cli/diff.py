"""svtplay-diff — three-way episode diff: local folder vs SVT Play vs TMDB."""

import json
import os
import sys

import click
from dotenv import load_dotenv

load_dotenv()


@click.command()
@click.argument("folder", type=click.Path(exists=True, file_okay=False))
@click.argument("show")
@click.option("--svt-url", default=None, help="SVT Play show URL (skips search).")
@click.option(
    "--missing-only",
    is_flag=True,
    help="Only show episodes not present in local folder.",
)
@click.option(
    "--downloadable-only",
    is_flag=True,
    help="Only show missing episodes that are currently available on SVT Play.",
)
def main(
    folder: str,
    show: str,
    svt_url: str,
    missing_only: bool,
    downloadable_only: bool,
) -> None:
    """Three-way diff for SHOW: local FOLDER vs SVT Play vs TMDB.

    Outputs JSON with every TMDB episode annotated with:
    - local: whether you have it as a file in FOLDER
    - svt_available: whether it is currently streamable on SVT Play

    The summary block shows counts for each category.
    """
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")

    api_key = os.environ.get("TMDB_API_KEY", "")
    if not api_key:
        click.echo("Error: TMDB_API_KEY is not set.", err=True)
        sys.exit(1)

    from svtplay.diff_state import diff_show

    result = diff_show(folder, show, api_key, svt_url=svt_url or None)

    if downloadable_only:
        result["episodes"] = [
            ep for ep in result["episodes"] if not ep["local"] and ep["svt_available"]
        ]
    elif missing_only:
        result["episodes"] = [ep for ep in result["episodes"] if not ep["local"]]

    json.dump(result, sys.stdout, ensure_ascii=False, indent=2)
    print()
