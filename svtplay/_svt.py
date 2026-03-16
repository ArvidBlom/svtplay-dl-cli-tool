"""SVT Play API — search, show metadata, episode listing.

All HTTP is done with stdlib urllib only.
"""

import json
import re
import unicodedata
import urllib.request
from typing import Any, Dict, List, Optional

# ─── Constants ────────────────────────────────────────────────────────────────

_GRAPHQL_URL = "https://api.svt.se/contento/graphql"
_SVTSTATIC = "https://www.svtstatic.se/image/original/default/{id}/{changed}?format=auto&quality=100"
_NEXT_DATA_RE = re.compile(
    r'<script id="__NEXT_DATA__" type="application/json">({.+?})</script>',
    re.DOTALL,
)
_DURATION_RE_MIN = re.compile(r"(\d+)\s*min")
_DURATION_RE_SEC = re.compile(r"(\d+)\s*sek")

_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
    ),
    "Accept-Language": "sv-SE,sv;q=0.9,en;q=0.8",
}

# SVT uses string-interpolated GQL (no variables), returns a flat list under data.search
_SEARCH_GQL = """
{
  search(query: %s) {
    id
    name
    description
    liveNow
    badge { text }
    item {
      __typename
      ... on KidsTvShow  { name shortDescription longDescription urls { svtplay } image { id changed } }
      ... on TvShow      { name shortDescription longDescription urls { svtplay } image { id changed } }
      ... on TvSeries    { name shortDescription longDescription urls { svtplay } image { id changed } }
      ... on Single      { name shortDescription urls { svtplay } image { id changed } }
      ... on Episode     { name svtId urls { svtplay } image { id changed } }
      ... on Clip        { name urls { svtplay } }
      ... on Trailer     { name urls { svtplay } }
    }
  }
}
"""


# ─── Helpers ──────────────────────────────────────────────────────────────────

def _http_get(url: str, timeout: int = 15) -> str:
    req = urllib.request.Request(url, headers=_HEADERS)
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return r.read().decode("utf-8", errors="replace")


def _graphql(gql: str) -> Dict[str, Any]:
    payload = json.dumps({"query": gql}).encode("utf-8")
    req = urllib.request.Request(
        _GRAPHQL_URL,
        data=payload,
        headers={**_HEADERS, "Content-Type": "application/json", "Accept": "application/json"},
    )
    with urllib.request.urlopen(req, timeout=15) as r:
        return json.loads(r.read().decode("utf-8"))


_HTML_TAG_RE = re.compile(r"<[^>]+>")


def _strip_html(text: str) -> str:
    return _HTML_TAG_RE.sub("", text).strip()


def _image_url(img: Dict[str, Any]) -> Optional[str]:
    if img and img.get("id") and img.get("changed"):
        return _SVTSTATIC.format(id=img["id"], changed=img["changed"])
    return None


def _parse_duration(sub_heading: str) -> Optional[int]:
    if not sub_heading:
        return None
    minutes = int(m.group(1)) if (m := _DURATION_RE_MIN.search(sub_heading)) else 0
    seconds = int(s.group(1)) if (s := _DURATION_RE_SEC.search(sub_heading)) else 0
    total = minutes * 60 + seconds
    return total if total > 0 else None


def _normalise(text: str) -> str:
    """Lowercase, strip accents, collapse whitespace/punctuation."""
    text = text.lower()
    # Swedish → ASCII fallbacks first (unicodedata strips the diacritic but keeps the base)
    text = unicodedata.normalize("NFD", text)
    text = "".join(c for c in text if unicodedata.category(c) != "Mn")
    text = re.sub(r"[^a-z0-9\s]", " ", text)
    return re.sub(r"\s+", " ", text).strip()


def _score(query: str, candidate: str) -> float:
    """Token-overlap similarity (Jaccard), tried on both raw and ASCII-folded forms."""
    def jaccard(a: str, b: str) -> float:
        ta, tb = set(a.split()), set(b.split())
        if not ta or not tb:
            return 0.0
        return len(ta & tb) / len(ta | tb)

    nq, nc = _normalise(query), _normalise(candidate)
    return max(jaccard(query.lower(), candidate.lower()), jaccard(nq, nc))


# ─── Public API ───────────────────────────────────────────────────────────────

def search(query: str) -> List[Dict[str, Any]]:
    """Search SVT Play via GraphQL. Returns normalised hit list."""
    gql = _SEARCH_GQL % json.dumps(query)
    data = _graphql(gql)
    hits = (data.get("data") or {}).get("search") or []
    results = []
    for hit in hits:
        item = hit.get("item") or {}
        typename = item.get("__typename", "")
        is_show = typename in ("TvShow", "KidsTvShow", "TvSeries")
        urls = item.get("urls") or {}
        svtplay_path = urls.get("svtplay") or ""
        url = f"https://www.svtplay.se{svtplay_path}" if svtplay_path else ""
        img = item.get("image") or {}
        results.append({
            "id": hit.get("id"),
            "name": _strip_html(hit.get("name") or item.get("name") or ""),
            "type": typename,
            "description": _strip_html(hit.get("description") or ""),
            "short_description": _strip_html(item.get("shortDescription") or ""),
            "long_description": _strip_html(item.get("longDescription") or ""),
            "url": url,
            "live_now": hit.get("liveNow", False),
            "badge": (hit.get("badge") or {}).get("text"),
            "is_show": is_show,
            "thumbnail_url": _image_url(img),
        })
    return results


def find_show(
    query: str,
    match_threshold: float = 0.55,
    suggests_threshold: float = 0.35,
    shows_only: bool = False,
) -> Dict[str, Any]:
    """Search + fuzzy-match. Returns best match and suggestions."""
    results = search(query)
    if shows_only:
        results = [r for r in results if r.get("is_show")]

    scored = [(r, _score(query, r["name"])) for r in results]
    scored.sort(key=lambda x: x[1], reverse=True)

    best, best_score = (scored[0] if scored else (None, 0.0))
    match = best if best_score >= match_threshold else None
    suggestions = [r for r, s in scored if r is not best and s >= suggests_threshold]

    return {
        "query": query,
        "match": match,
        "match_score": best_score,
        "suggestions": suggestions,
        "all_results": results,
    }


def fetch_show_episodes(show_url: str) -> List[Dict[str, Any]]:
    """Scrape a SVT Play show page and return all episodes (no recommendations)."""
    try:
        html = _http_get(show_url)
    except Exception:
        return []

    m = _NEXT_DATA_RE.search(html)
    if not m:
        return []
    try:
        next_data = json.loads(m.group(1))
    except json.JSONDecodeError:
        return []

    urql_state = (next_data.get("props") or {}).get("urqlState") or {}
    modules: List[Dict] = []
    for entry_raw in urql_state.values():
        if not isinstance(entry_raw, dict) or "data" not in entry_raw:
            continue
        try:
            entry = json.loads(entry_raw["data"])
        except (json.JSONDecodeError, TypeError):
            continue
        page = entry.get("detailsPageByPath")
        if page and isinstance(page.get("modules"), list):
            modules = page["modules"]
            break

    episodes: List[Dict[str, Any]] = []
    seen: set = set()

    for module in modules:
        if not isinstance(module, dict):
            continue
        selection = module.get("selection") or {}
        if selection.get("selectionType") == "related":
            continue
        for item in selection.get("items") or []:
            if not isinstance(item, dict):
                continue
            svt_id = (item.get("analytics") or {}).get("json", {}).get("svtId")
            if not svt_id or svt_id in seen:
                continue
            seen.add(svt_id)

            inner = item.get("item") or {}
            canonical = (inner.get("urls") or {}).get("svtplay")
            wide = (item.get("images") or {}).get("wide") or {}
            sub_heading = item.get("subHeading") or ""
            duration = _parse_duration(sub_heading)

            episodes.append({
                "svt_id": svt_id,
                "name": item.get("heading") or "",
                "description": item.get("description") or None,
                "sub_heading": sub_heading,
                "duration_seconds": duration,
                "url": f"https://www.svtplay.se/video/{svt_id}",
                "canonical_url": f"https://www.svtplay.se{canonical}" if canonical else None,
                "air_date": inner.get("validFromFormatted"),
                "badge": item.get("badge"),
                "thumbnail_url": _image_url(wide),
                "available": item.get("upcomingOverlay") is None,
            })

    return episodes
