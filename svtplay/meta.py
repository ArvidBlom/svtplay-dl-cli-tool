"""svtplay-meta — read and display metadata embedded in a video file."""

import json
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional

import click
from dotenv import load_dotenv

load_dotenv()

# Fields we expect to be present after a full embed
_EXPECTED = {
    "©nam": "title",
    "tvsh": "show",
    "tvsn": "season",
    "tves": "episode",
    "tven": "episode_id",
    "tvnn": "network",
    "©day": "air_date",
    "desc": "description",
    "covr": "cover_art",
    "----:com.apple.iTunes:SVT_ID": "svt_id",
    "----:com.apple.iTunes:SVT_URL": "svt_url",
    "----:com.apple.iTunes:TMDB_SHOW_ID": "tmdb_show_id",
}


def _read_tags(path: Path) -> Dict[str, Any]:
    """Read all MP4 tags from *path* via mutagen. Returns flat dict."""
    from mutagen.mp4 import MP4

    f = MP4(str(path))
    tags: Dict[str, Any] = {}
    if not f.tags:
        return tags
    for k, v in f.tags.items():
        if k == "covr":
            tags[k] = f"[cover art, {len(v[0])} bytes]"
        elif k.startswith("----"):
            # freeform atoms — decode bytes
            tags[k] = [bytes(x).decode("utf-8", errors="replace") for x in v]
        elif isinstance(v, list) and len(v) == 1:
            tags[k] = v[0]
        else:
            tags[k] = v
    tags["_duration_seconds"] = round(f.info.length)
    tags["_bitrate_kbps"] = f.info.bitrate // 1000
    return tags


def _missing(tags: Dict[str, Any]) -> List[str]:
    """Return list of expected field names that are absent."""
    return [label for key, label in _EXPECTED.items() if key not in tags]


@click.command()
@click.argument("file", type=click.Path(exists=True, dir_okay=False))
@click.option("--json", "as_json", is_flag=True, help="Output as JSON.")
@click.option("--missing-only", is_flag=True, help="Only print fields that are absent.")
def main(file: str, as_json: bool, missing_only: bool) -> None:
    """Display metadata embedded in a video FILE.

    Reports which expected fields (title, S/E numbers, SVT URL, etc.) are
    present or missing — useful for deciding whether backfilling is needed.
    """
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")

    path = Path(file)
    try:
        tags = _read_tags(path)
    except Exception as exc:
        if as_json:
            json.dump({"error": str(exc), "file": str(path)}, sys.stdout, ensure_ascii=False)
            print()
        else:
            print(f"Error reading {path.name}: {exc}", file=sys.stderr)
        sys.exit(1)

    missing = _missing(tags)
    needs_backfill = len(missing) > 0

    if as_json:
        json.dump(
            {
                "file": str(path),
                "tags": tags,
                "missing": missing,
                "needs_backfill": needs_backfill,
            },
            sys.stdout,
            ensure_ascii=False,
            indent=2,
        )
        print()
        return

    if missing_only:
        if missing:
            print(f"{path.name}: missing {', '.join(missing)}")
        else:
            print(f"{path.name}: all fields present")
        return

    # Human-readable full output
    dur = tags.get("_duration_seconds", 0)
    print(f"File    : {path.name}")
    print(f"Size    : {path.stat().st_size // (1024*1024):.1f} MB")
    print(f"Duration: {dur // 60}m {dur % 60}s  |  {tags.get('_bitrate_kbps', '?')} kbps")
    print()

    # Standard fields
    rows = [
        ("Title",      tags.get("©nam")),
        ("Show",       tags.get("tvsh")),
        ("Season",     tags.get("tvsn")),
        ("Episode",    tags.get("tves")),
        ("Episode ID", tags.get("tven")),
        ("Network",    tags.get("tvnn")),
        ("Air date",   tags.get("©day")),
        ("Cover art",  tags.get("covr")),
        ("Description",tags.get("desc")),
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
