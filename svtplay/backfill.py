"""svtplay-backfill-info / svtplay-backfill-apply — agent-driven metadata backfill.

Workflow:
  1. svtplay-backfill-info "Bluey" --dir ~/Videos/Bluey
     → JSON payload: filenames + SVT episodes + TMDB episodes

  2. Agent (LLM) matches filenames to SVT/TMDB episodes using the payload

  3. svtplay-backfill-apply '{"show":"Bluey","matches":[...]}'
     → embeds metadata, renames files, updates download cache
"""

import json
import re
import shutil
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional

import click
from dotenv import load_dotenv

load_dotenv()

from svtplay._embed import VIDEO_EXTENSIONS, embed
from svtplay._match import episode_filename, safe_filename


# ─── backfill-info ────────────────────────────────────────────────────────────

@click.command(name="svtplay-backfill-info")
@click.argument("show")
@click.option("--files", "-f", multiple=True, type=click.Path(exists=True),
              help="Specific video files to backfill.")
@click.option("--dir", "-d", "scan_dir", default=None, type=click.Path(exists=True),
              help="Scan this directory for video files.")
@click.option("--tmdb-key", envvar="TMDB_API_KEY", default=None, help="TMDB API key.")
@click.option("--api-key", envvar="ANTHROPIC_API_KEY", default=None,
              help="Anthropic API key (needed if TMDB not yet cached).")
@click.option("--threshold", default=0.55, show_default=True, help="SVT show match threshold.")
def info(
    show: str,
    files: tuple,
    scan_dir: Optional[str],
    tmdb_key: Optional[str],
    api_key: Optional[str],
    threshold: float,
) -> None:
    """Output a JSON payload for agent-driven metadata backfill.

    The agent uses the payload to match filenames to SVT/TMDB episodes, then
    calls svtplay-backfill-apply with its decisions.
    """
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")

    from svtplay._svt import find_show, fetch_show_episodes
    from svtplay._cache import get as cache_get, get_svt_episodes, patch_svt_episodes

    # ── Collect file list ─────────────────────────────────────────────────────
    file_paths: List[Path] = []
    for f in files:
        p = Path(f)
        if p.suffix.lower() in VIDEO_EXTENSIONS:
            file_paths.append(p.resolve())

    if scan_dir:
        d = Path(scan_dir)
        for f in sorted(d.iterdir()):
            if f.is_file() and f.suffix.lower() in VIDEO_EXTENSIONS:
                file_paths.append(f.resolve())

    if not file_paths:
        json.dump({"error": "No video files provided. Use --files or --dir."}, sys.stdout, ensure_ascii=False)
        print()
        sys.exit(1)

    # ── Find SVT show ─────────────────────────────────────────────────────────
    svt_result = find_show(show, match_threshold=threshold, shows_only=True)
    svt_match = svt_result.get("match")
    if not svt_match:
        json.dump({"error": f"No SVT Play show found for '{show}'."}, sys.stdout, ensure_ascii=False)
        print()
        sys.exit(1)

    svt_name: str = svt_match["name"]
    svt_show_url: str = svt_match["url"]

    # ── Fetch SVT episodes (cache first, then live) ───────────────────────────
    svt_episodes = get_svt_episodes(svt_name)
    if svt_episodes is None:
        try:
            svt_episodes = fetch_show_episodes(svt_show_url)
        except Exception as exc:
            json.dump({"error": f"Failed to fetch SVT episodes: {exc}"}, sys.stdout, ensure_ascii=False)
            print()
            sys.exit(1)
        if svt_episodes:
            patch_svt_episodes(svt_name, svt_episodes)

    # ── TMDB episodes from cache ──────────────────────────────────────────────
    tmdb_episodes: Optional[List[Dict]] = None
    tmdb_show_id: Optional[int] = None
    tmdb_cached = cache_get(svt_name)

    if tmdb_cached:
        tmdb_episodes = tmdb_cached.get("tmdb_episodes")
        tmdb_match_data = tmdb_cached.get("tmdb_match") or {}
        tmdb_show_id = tmdb_match_data.get("tmdb_id")
    elif tmdb_key and api_key:
        # Trigger a fresh TMDB lookup and cache it
        from svtplay._tmdb_api import search_show, get_all_episodes
        from svtplay._cache import put as cache_put
        from svtplay.tmdb import TMDBMatch, _llm_match

        svt_description = svt_match.get("description") or ""
        svt_episode_names = [ep.get("name", "") for ep in svt_episodes[:5] if ep.get("name")]
        candidates = search_show(svt_name, tmdb_key)[:10]

        if candidates:
            if len(candidates) == 1:
                c = candidates[0]
                tmdb_obj = TMDBMatch(
                    tmdb_id=c.get("id"), tmdb_name=c.get("name"),
                    original_name=c.get("original_name"), first_air_date=c.get("first_air_date"),
                    overview=c.get("overview"), confidence=1.0,
                    reasoning="Only one TMDB result; selected automatically.",
                )
            else:
                tmdb_obj = _llm_match(svt_name, svt_description, svt_episode_names, candidates, api_key)

            tmdb_match_dict = tmdb_obj.model_dump()
            tmdb_show_id = tmdb_match_dict.get("tmdb_id")
            if tmdb_show_id and tmdb_match_dict.get("confidence", 0) >= 0.90:
                tmdb_episodes = get_all_episodes(tmdb_show_id, tmdb_key)
            cache_put(svt_name, {"svt_name": svt_name, "tmdb_match": tmdb_match_dict, "tmdb_episodes": tmdb_episodes})

    # ── Build payload ─────────────────────────────────────────────────────────
    payload: Dict[str, Any] = {
        "show": svt_name,
        "svt_show_url": svt_show_url,
        "tmdb_show_id": tmdb_show_id,
        "files": [
            {"path": str(p), "filename": p.name}
            for p in file_paths
        ],
        "svt_episodes": [
            {
                "svt_id": ep.get("svt_id"),
                "name": ep.get("name"),
                "url": ep.get("url"),
                "thumbnail_url": ep.get("thumbnail_url"),
                "air_date": ep.get("air_date"),
                "duration_seconds": ep.get("duration_seconds"),
            }
            for ep in svt_episodes
        ],
        "tmdb_episodes": tmdb_episodes,
        "instructions": (
            "You are an agent. Match each entry in 'files' to the best matching entries in "
            "'svt_episodes' (for svt_id, svt_url, thumbnail_url) and 'tmdb_episodes' (for "
            "season_number, episode_number). Use filename and episode name similarity. "
            "Then call svtplay-backfill-apply with a JSON object containing 'show' and 'matches' "
            "(list of match dicts with keys: file, svt_id, svt_url, season, episode, "
            "episode_title, air_date, thumbnail_url, tmdb_show_id)."
        ),
    }

    json.dump(payload, sys.stdout, ensure_ascii=False, indent=2)
    print()


# ─── backfill-apply ───────────────────────────────────────────────────────────

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
    """Embed metadata into video files based on agent-provided match decisions.

    JSON_INPUT is either a JSON string or '-' to read from stdin.

    Expected JSON shape:
    {
      "show": "Bluey",
      "matches": [
        {
          "file": "/abs/path/episode.mp4",
          "svt_id": "eXY5Eqr",
          "svt_url": "https://www.svtplay.se/video/eXY5Eqr",
          "season": 1,
          "episode": 3,
          "episode_title": "Burgarhund",
          "air_date": "2018-10-15",
          "thumbnail_url": "https://...",
          "tmdb_show_id": 82728
        }
      ]
    }
    """
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")

    from svtplay._dl_cache import add_entry

    # ── Parse input ───────────────────────────────────────────────────────────
    if json_input == "-":
        raw = sys.stdin.read()
    else:
        raw = json_input

    try:
        data = json.loads(raw)
    except json.JSONDecodeError as exc:
        _err(as_json, f"Invalid JSON: {exc}")
        sys.exit(1)

    show_name: str = data.get("show", "")
    matches: List[Dict] = data.get("matches", [])

    if not show_name or not matches:
        _err(as_json, "JSON must contain 'show' (string) and 'matches' (list).")
        sys.exit(1)

    # ── Process each match ────────────────────────────────────────────────────
    results = []
    errors = []

    for i, m in enumerate(matches, 1):
        file_path = Path(m.get("file", ""))
        if not file_path.exists():
            errors.append({"file": str(file_path), "error": "File not found"})
            if not as_json:
                print(f"[{i}/{len(matches)}] SKIP (not found): {file_path}", file=sys.stderr)
            continue

        svt_id: Optional[str] = m.get("svt_id")
        svt_url: Optional[str] = m.get("svt_url")
        season: Optional[int] = m.get("season")
        episode_num: Optional[int] = m.get("episode")
        episode_title: str = m.get("episode_title") or file_path.stem
        air_date: Optional[str] = m.get("air_date")
        thumbnail_url: Optional[str] = m.get("thumbnail_url")
        tmdb_show_id: Optional[int] = m.get("tmdb_show_id")

        canonical = episode_filename(episode_title, show_name, season, episode_num, ext=file_path.suffix)
        new_path = file_path.parent / canonical

        if not as_json:
            print(f"[{i}/{len(matches)}] {file_path.name}")
            if not no_rename and new_path != file_path:
                print(f"  → rename: {canonical}")
            print(f"  → embed: title={episode_title!r}  S{season:02d}E{episode_num:02d}" if season and episode_num else f"  → embed: title={episode_title!r}")

        if dry_run:
            results.append({"file": str(file_path), "would_rename_to": str(new_path) if not no_rename else None,
                             "season": season, "episode": episode_num})
            continue

        # Embed metadata
        try:
            embed(
                file_path,
                title=episode_title,
                show=show_name,
                season=season,
                episode=episode_num,
                air_date=air_date,
                svt_id=svt_id,
                svt_url=svt_url,
                tmdb_show_id=tmdb_show_id,
                thumbnail_url=thumbnail_url,
            )
        except Exception as exc:
            errors.append({"file": str(file_path), "error": f"embed failed: {exc}"})
            if not as_json:
                print(f"  WARNING: metadata embedding failed: {exc}", file=sys.stderr)
            # Continue — still rename if possible

        # Rename
        if not no_rename and new_path != file_path:
            if new_path.exists():
                if not as_json:
                    print(f"  WARNING: target already exists, skipping rename: {new_path}", file=sys.stderr)
            else:
                shutil.move(str(file_path), str(new_path))
                file_path = new_path

        # Update download cache
        if svt_id:
            try:
                add_entry(
                    show_name,
                    svt_id=svt_id,
                    filename=file_path.name,
                    season=season,
                    episode=episode_num,
                    episode_title=episode_title,
                    svt_url=svt_url,
                    tmdb_show_id=tmdb_show_id,
                )
            except Exception:
                pass  # non-fatal

        results.append({
            "file": str(file_path),
            "season": season,
            "episode": episode_num,
            "episode_title": episode_title,
        })

    # ── Summary ───────────────────────────────────────────────────────────────
    if not as_json:
        print(f"\nDone. Processed: {len(results)}, errors: {len(errors)}")
    else:
        json.dump({"show": show_name, "processed": results, "errors": errors,
                   "dry_run": dry_run}, sys.stdout, ensure_ascii=False, indent=2)
        print()

    if errors and not dry_run:
        sys.exit(1)


# ─── Helpers ──────────────────────────────────────────────────────────────────

def _err(as_json: bool, msg: str) -> None:
    if as_json:
        json.dump({"error": msg}, sys.stdout, ensure_ascii=False)
        print()
    else:
        print(f"Error: {msg}", file=sys.stderr)
