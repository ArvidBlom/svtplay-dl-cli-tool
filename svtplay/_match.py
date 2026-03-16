"""Match SVT Play episode names to TMDB season/episode numbers.

Strategy (in priority order):
1. Exact name match after lowercasing + stripping punctuation
2. Difflib SequenceMatcher similarity >= 0.75
3. No match → (None, None); episode is still downloaded, just no S##E## prefix

Minisodes (duration < MINISODE_THRESHOLD) are never matched against TMDB
full-length episodes — they share names with real episodes (e.g. "Bingo",
"Fårhund") but are different content. They get no S##E## prefix.
"""

MINISODE_THRESHOLD = 240  # seconds — episodes shorter than this are minisodes

import re
import unicodedata
from difflib import SequenceMatcher
from typing import Dict, List, Optional, Tuple


def _normalise(text: str) -> str:
    """Lowercase, strip diacritics, collapse whitespace and punctuation."""
    text = text.lower()
    text = unicodedata.normalize("NFD", text)
    text = "".join(c for c in text if unicodedata.category(c) != "Mn")
    text = re.sub(r"[^a-z0-9\s]", " ", text)
    return re.sub(r"\s+", " ", text).strip()


def _similarity(a: str, b: str) -> float:
    na, nb = _normalise(a), _normalise(b)
    if not na or not nb:
        return 0.0
    return SequenceMatcher(None, na, nb).ratio()


def match_episodes(
    svt_episodes: List[Dict],
    tmdb_episodes: List[Dict],
    threshold: float = 0.75,
) -> Dict[str, Tuple[Optional[int], Optional[int]]]:
    """Return {svt_id: (season_number, episode_number)} for each SVT episode.

    svt_episodes: list of dicts with at least {svt_id, name}
    tmdb_episodes: list of dicts with at least {season_number, episode_number, name}
    """
    result: Dict[str, Tuple[Optional[int], Optional[int]]] = {}

    if not tmdb_episodes:
        for ep in svt_episodes:
            result[ep["svt_id"]] = (None, None)
        return result

    # Pre-normalise TMDB names
    tmdb_normalised = [
        (_normalise(ep.get("name", "")), ep)
        for ep in tmdb_episodes
    ]

    for svt_ep in svt_episodes:
        svt_id = svt_ep.get("svt_id")
        if not svt_id:
            continue

        # Skip TMDB matching for minisodes — they share names with full episodes
        # but are completely different content, causing false-positive matches.
        duration = svt_ep.get("duration_seconds") or 0
        if duration and duration < MINISODE_THRESHOLD:
            result[svt_id] = (None, None)
            continue

        svt_name = svt_ep.get("name") or ""
        svt_norm = _normalise(svt_name)

        best_score = 0.0
        best_tmdb: Optional[Dict] = None

        for tmdb_norm, tmdb_ep in tmdb_normalised:
            # Exact match shortcut
            if svt_norm and svt_norm == tmdb_norm:
                best_tmdb = tmdb_ep
                best_score = 1.0
                break

            score = SequenceMatcher(None, svt_norm, tmdb_norm).ratio()
            if score > best_score:
                best_score = score
                best_tmdb = tmdb_ep

        if best_tmdb and best_score >= threshold:
            result[svt_id] = (
                best_tmdb.get("season_number"),
                best_tmdb.get("episode_number"),
            )
        else:
            result[svt_id] = (None, None)

    return result


def safe_filename(name: str) -> str:
    """Strip characters illegal on Windows/macOS, preserve Swedish ÅÄÖ."""
    return re.sub(r'[\\/:*?"<>|]', "", name).strip()


def episode_filename(
    episode_name: str,
    show_name: str,
    season: Optional[int],
    episode: Optional[int],
    ext: str = ".mp4",
) -> str:
    """Build the canonical filename: 'S01E03 Episode Name - Show Name.mp4'

    Falls back to 'Episode Name - Show Name.mp4' if no S##E## match.
    """
    safe_ep = safe_filename(episode_name)
    safe_show = safe_filename(show_name)
    if season is not None and episode is not None:
        prefix = f"S{season:02d}E{episode:02d} "
    else:
        prefix = ""
    return f"{prefix}{safe_ep} - {safe_show}{ext}"
