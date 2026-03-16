"""svtplay-download — download new episodes of a show from SVT Play.

Usage:
    svtplay-download "Bluey"
    svtplay-download "Bluey" --dry-run
    svtplay-download "Bluey" --all          # re-download everything
    svtplay-download "Bluey" --json         # machine-readable output
"""

import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import click
from dotenv import load_dotenv

load_dotenv()

_DEFAULT_OUTPUT_DIR = Path.home() / "Downloads" / "svtplay-dl"


# ─── svtplay-dl invocation ────────────────────────────────────────────────────

def _find_svtplay_dl() -> List[str]:
    """Return the svtplay-dl command prefix."""
    exe = shutil.which("svtplay-dl")
    if exe:
        return [exe]
    return [sys.executable, "-m", "svtplay_dl"]


def _run_download(url: str, output_path: Path) -> Tuple[bool, str]:
    """Invoke svtplay-dl for *url*, writing to *output_path* (without extension).

    svtplay-dl appends the extension itself. Returns (success, error_message).
    """
    cmd = _find_svtplay_dl() + ["--output", str(output_path), url]
    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0:
        return False, result.stderr[-1000:] or result.stdout[-1000:]
    return True, ""


def _find_produced_file(base: Path) -> Optional[Path]:
    """Find the video file svtplay-dl wrote in the temp directory.

    We use a fresh tmpdir per download, so any video file in it is ours.
    svtplay-dl sometimes ignores the --output basename and uses the show title.
    """
    from svtplay._embed import VIDEO_EXTENSIONS
    # Prefer exact stem match first
    for ext in VIDEO_EXTENSIONS:
        candidate = base.with_suffix(ext)
        if candidate.exists():
            return candidate
    # Fall back to any video file in the directory
    for f in base.parent.iterdir():
        if f.is_file() and f.suffix.lower() in VIDEO_EXTENSIONS:
            return f
    return None


# ─── Output helpers ────────────────────────────────────────────────────────────

def _out(as_json: bool, data: Any) -> None:
    if as_json:
        json.dump(data, sys.stdout, ensure_ascii=False, indent=2)
        print()


def _info(as_json: bool, msg: str) -> None:
    if not as_json:
        print(msg)


def _warn(as_json: bool, msg: str) -> None:
    print(f"Warning: {msg}", file=sys.stderr)


def _err(as_json: bool, msg: str) -> None:
    if as_json:
        json.dump({"error": msg}, sys.stdout, ensure_ascii=False)
        print()
    else:
        print(f"Error: {msg}", file=sys.stderr)


# ─── TMDB resolution (optional) ───────────────────────────────────────────────

def _resolve_tmdb(
    svt_name: str,
    svt_url: str,
    svt_description: str,
    svt_episodes: List[Dict],
    api_key: str,
    tmdb_key: str,
    no_cache: bool,
    as_json: bool,
) -> Tuple[Optional[Dict], Optional[List[Dict]]]:
    """Return (tmdb_match_dict, tmdb_episodes_list) or (None, None) on failure."""
    from svtplay._cache import get as cache_get, put as cache_put
    from svtplay._tmdb_api import search_show, get_all_episodes
    from svtplay.tmdb import TMDBMatch, _llm_match

    if not no_cache:
        cached = cache_get(svt_name)
        if cached:
            return cached.get("tmdb_match"), cached.get("tmdb_episodes")

    try:
        candidates = search_show(svt_name, tmdb_key)[:10]
    except Exception as exc:
        _warn(as_json, f"TMDB search failed: {exc}")
        return None, None

    svt_episode_names = [ep.get("name", "") for ep in svt_episodes[:5] if ep.get("name")]

    if not candidates:
        tmdb_match_obj = TMDBMatch(
            tmdb_id=None, tmdb_name=None, original_name=None,
            first_air_date=None, overview=None,
            confidence=0.0, reasoning="No TMDB results found for this title.",
        )
    elif len(candidates) == 1:
        c = candidates[0]
        tmdb_match_obj = TMDBMatch(
            tmdb_id=c.get("id"),
            tmdb_name=c.get("name"),
            original_name=c.get("original_name"),
            first_air_date=c.get("first_air_date"),
            overview=c.get("overview"),
            confidence=1.0,
            reasoning="Only one TMDB result returned; selected automatically.",
        )
    else:
        _info(as_json, f"  Asking Claude to match '{svt_name}' against {len(candidates)} TMDB candidates...")
        try:
            tmdb_match_obj = _llm_match(svt_name, svt_description, svt_episode_names, candidates, api_key)
        except Exception as exc:
            _warn(as_json, f"LLM matching failed: {exc}")
            return None, None

    tmdb_match = tmdb_match_obj.model_dump()
    tmdb_episodes = None
    tmdb_id = tmdb_match.get("tmdb_id")
    if tmdb_id and tmdb_match.get("confidence", 0) >= 0.90:
        try:
            tmdb_episodes = get_all_episodes(tmdb_id, tmdb_key)
        except Exception as exc:
            _warn(as_json, f"Could not fetch TMDB episodes: {exc}")

    cache_put(svt_name, {"svt_name": svt_name, "tmdb_match": tmdb_match, "tmdb_episodes": tmdb_episodes})
    return tmdb_match, tmdb_episodes


# ─── CLI ───────────────────────────────────────────────────────────────────────

@click.command()
@click.argument("query")
@click.option("--output-dir", "-o", default=None, help=f"Output directory. Default: ~/Downloads/svtplay-dl/")
@click.option("--tmdb-key", envvar="TMDB_API_KEY", default=None, help="TMDB API key.")
@click.option("--api-key", envvar="ANTHROPIC_API_KEY", default=None, help="Anthropic API key (for TMDB matching).")
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
    """Download new episodes of a show from SVT Play.

    Tracks downloads in ~/.svtplay-cli/downloads/<show>.json so re-running
    only fetches episodes not yet downloaded. Use --all to ignore the cache.

    Files are saved as: S##E## Episode Name - Show Name.mp4
    Metadata from SVT and TMDB is embedded via ffmpeg, including cover art.
    """
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")

    from svtplay._svt import find_show, fetch_show_episodes
    from svtplay._cache import get_svt_episodes, patch_svt_episodes
    from svtplay._match import match_episodes, episode_filename
    from svtplay._dl_cache import get_downloaded_ids, add_entry
    from svtplay._embed import embed

    # ── 1. Find SVT show ──────────────────────────────────────────────────────
    _info(as_json, f"Searching SVT Play for '{query}'...")
    result = find_show(query, match_threshold=threshold, shows_only=True)
    match = result.get("match")
    if not match:
        _err(as_json, f"No SVT Play show found for '{query}'.")
        sys.exit(1)

    svt_name: str = match["name"]
    svt_show_url: str = match["url"]
    svt_description: str = match.get("description") or match.get("short_description") or ""
    svt_thumbnail: Optional[str] = match.get("thumbnail_url")
    _info(as_json, f"Found: {svt_name}  ({svt_show_url})")

    # ── 2. Fetch episode list (cache first, then live) ────────────────────────
    svt_episodes = get_svt_episodes(svt_name)
    if svt_episodes is None:
        _info(as_json, "Fetching episode list...")
        try:
            svt_episodes = fetch_show_episodes(svt_show_url)
        except Exception as exc:
            _err(as_json, f"Failed to fetch episodes: {exc}")
            sys.exit(1)
        if svt_episodes:
            patch_svt_episodes(svt_name, svt_episodes)
    else:
        _info(as_json, f"Episode list loaded from cache.")

    if not svt_episodes:
        _err(as_json, "No episodes found on SVT Play for this show.")
        sys.exit(1)

    _info(as_json, f"Found {len(svt_episodes)} episode(s) on SVT Play.")

    # ── 3. Resolve TMDB (optional) ────────────────────────────────────────────
    tmdb_match: Optional[Dict] = None
    tmdb_episodes: Optional[List[Dict]] = None
    tmdb_show_id: Optional[int] = None

    if api_key and tmdb_key:
        _info(as_json, "Resolving TMDB match...")
        tmdb_match, tmdb_episodes = _resolve_tmdb(
            svt_name, svt_show_url, svt_description,
            svt_episodes, api_key, tmdb_key, no_cache, as_json,
        )
        if tmdb_match:
            tmdb_show_id = tmdb_match.get("tmdb_id")
            confidence = tmdb_match.get("confidence", 0)
            _info(as_json, f"TMDB: {tmdb_match.get('tmdb_name')}  (confidence={confidence:.0%})")
    else:
        _info(as_json, "  (Skipping TMDB — set ANTHROPIC_API_KEY + TMDB_API_KEY to enable S##E## naming.)")

    # ── 4. Match SVT↔TMDB episodes for S##E## ────────────────────────────────
    ep_season_map: Dict[str, Tuple[Optional[int], Optional[int]]] = {}
    if tmdb_episodes:
        ep_season_map = match_episodes(svt_episodes, tmdb_episodes)

    # ── 5. Output directory ───────────────────────────────────────────────────
    from svtplay._match import safe_filename
    base_dir = Path(output_dir) if output_dir else _DEFAULT_OUTPUT_DIR
    show_dir = base_dir / safe_filename(svt_name)

    # ── 6. Determine which episodes to download ───────────────────────────────
    if download_all:
        downloaded_ids = set()
    else:
        downloaded_ids = get_downloaded_ids(svt_name, show_dir)
        if downloaded_ids:
            _info(as_json, f"Cache: {len(downloaded_ids)} episode(s) already downloaded.")

    to_download = [
        ep for ep in svt_episodes
        if ep.get("svt_id") not in downloaded_ids and ep.get("available", False)
    ]
    unavailable = [ep for ep in svt_episodes if not ep.get("available", False)]
    skipped = len(svt_episodes) - len(to_download) - len(unavailable)

    _info(as_json, f"Episodes to download: {len(to_download)}  (skipping {skipped} already done, {len(unavailable)} not yet aired)")

    if not to_download:
        _info(as_json, "Nothing new to download.")
        if as_json:
            _out(as_json, {"query": query, "show": svt_name, "downloaded": [], "skipped": skipped})
        return

    # ── 7. Dry run ────────────────────────────────────────────────────────────
    if dry_run:
        plan = []
        for ep in to_download:
            svt_id = ep["svt_id"]
            season, episode = ep_season_map.get(svt_id, (None, None))
            fname = episode_filename(ep.get("name", svt_id), svt_name, season, episode)
            plan.append({"svt_id": svt_id, "name": ep.get("name"), "filename": fname,
                         "season": season, "episode": episode, "url": ep["url"]})
        if as_json:
            _out(as_json, {"query": query, "show": svt_name, "dry_run": True,
                           "would_download": plan, "skipped": skipped})
        else:
            print(f"\nWould download {len(plan)} episode(s) to: {show_dir}\n")
            for item in plan:
                print(f"  {item['filename']}")
                print(f"    {item['url']}")
        return

    # ── 8. Download loop ──────────────────────────────────────────────────────
    show_dir.mkdir(parents=True, exist_ok=True)
    downloaded_results = []
    failed_results = []

    for i, ep in enumerate(to_download, 1):
        svt_id = ep["svt_id"]
        ep_name = ep.get("name") or svt_id
        ep_url = ep["url"]
        season, episode_num = ep_season_map.get(svt_id, (None, None))
        final_name = episode_filename(ep_name, svt_name, season, episode_num)
        final_path = show_dir / final_name

        _info(as_json, f"\n[{i}/{len(to_download)}] {final_name}")
        _info(as_json, f"  {ep_url}")

        # Skip if final file already exists on disk (safety net)
        if final_path.exists():
            _info(as_json, f"  Already exists, skipping.")
            downloaded_ids.add(svt_id)
            continue

        # Download to temp location so we can rename cleanly
        with tempfile.TemporaryDirectory(prefix="svtplay-dl-") as tmpdir:
            tmp_base = Path(tmpdir) / "episode"
            _info(as_json, "  Downloading...")

            # Pass quality flag if requested
            extra: List[str] = []
            if quality:
                extra += ["-q", quality]

            cmd = _find_svtplay_dl() + extra + ["--output", str(tmp_base), ep_url]
            dl_result = subprocess.run(cmd, capture_output=True, text=True)

            if dl_result.returncode != 0:
                msg = dl_result.stderr[-500:] or dl_result.stdout[-500:]
                _warn(as_json, f"svtplay-dl failed for {ep_url}: {msg}")
                failed_results.append({"svt_id": svt_id, "name": ep_name, "error": msg})
                continue

            produced = _find_produced_file(tmp_base)
            if not produced:
                _warn(as_json, f"Could not find output file after download for {ep_url}")
                failed_results.append({"svt_id": svt_id, "name": ep_name, "error": "output file not found"})
                continue

            ext = produced.suffix
            final_name = episode_filename(ep_name, svt_name, season, episode_num, ext=ext)
            final_path = show_dir / final_name

            # Embed metadata + cover art
            _info(as_json, "  Embedding metadata...")
            ep_thumbnail = ep.get("thumbnail_url") or svt_thumbnail
            try:
                embed(
                    produced,
                    title=ep_name,
                    show=svt_name,
                    season=season,
                    episode=episode_num,
                    description=ep.get("description"),
                    air_date=ep.get("air_date"),
                    svt_id=svt_id,
                    svt_url=ep_url,
                    tmdb_show_id=tmdb_show_id,
                    thumbnail_url=ep_thumbnail,
                )
            except Exception as exc:
                _warn(as_json, f"Metadata embedding failed (file saved without tags): {exc}")

            # Move to final location
            shutil.move(str(produced), str(final_path))

        _info(as_json, f"  Saved: {final_path}")

        # Update download cache
        add_entry(
            svt_name,
            svt_id=svt_id,
            filename=final_name,
            season=season,
            episode=episode_num,
            episode_title=ep_name,
            svt_url=ep_url,
            tmdb_show_id=tmdb_show_id,
        )

        downloaded_results.append({
            "svt_id": svt_id,
            "name": ep_name,
            "filename": final_name,
            "season": season,
            "episode": episode_num,
            "path": str(final_path),
        })

    # ── 9. Summary ────────────────────────────────────────────────────────────
    _info(as_json, f"\nDone. Downloaded: {len(downloaded_results)}, failed: {len(failed_results)}, skipped: {skipped}")

    if as_json:
        _out(as_json, {
            "query": query,
            "show": svt_name,
            "downloaded": downloaded_results,
            "failed": failed_results,
            "skipped": skipped,
        })

    if failed_results and not as_json:
        print(f"\nFailed downloads ({len(failed_results)}):", file=sys.stderr)
        for f in failed_results:
            print(f"  {f['name']}: {f['error']}", file=sys.stderr)
        sys.exit(1)
