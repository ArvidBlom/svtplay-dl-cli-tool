# svtplay CLI tools

A set of focused CLI commands for interacting with SVT Play — searching shows, listing episodes, downloading with metadata embedding, and backfilling existing files.

Each command works standalone and produces JSON output suitable for scripting or agent use.

## Prerequisites

- Python 3.9+
- [`ffmpeg`](https://ffmpeg.org/) on PATH (required for `svtplay-download` and `svtplay-backfill-apply`)
- [`uv`](https://docs.astral.sh/uv/) (recommended) or pip

Optional for S##E## naming and TMDB matching:
- `ANTHROPIC_API_KEY` — Claude Haiku for LLM-assisted TMDB matching
- `TMDB_API_KEY` — fetches season/episode numbers

## Install

```bash
git clone https://github.com/ArvidBlom/svtplay-dl-cli-tool
cd svtplay-dl-cli-tool
uv sync
```

Or with pip:

```bash
pip install -e .
```

Set API keys in a `.env` file at the repo root:

```
ANTHROPIC_API_KEY=sk-ant-...
TMDB_API_KEY=...
```

## Commands

### `svtplay-search`

Search SVT Play for shows and episodes via the GraphQL API.

```bash
svtplay-search QUERY [OPTIONS]
```

| Option | Default | Description |
|--------|---------|-------------|
| `--limit N` | 10 | Max results to return |
| `--shows-only` | off | Filter to series/shows only |
| `--json` | off | Output as JSON |

**Examples:**
```bash
uv run svtplay-search "bluey"
uv run svtplay-search --json --shows-only "bluey"
uv run svtplay-search --limit 5 "barn"
```

**JSON output shape:**
```json
{
  "query": "bluey",
  "count": 2,
  "results": [
    {
      "id": "ewAdZ2J",
      "name": "Bluey",
      "type": "KidsTvShow",
      "description": "Bluey älskar att leka!",
      "url": "https://www.svtplay.se/bluey",
      "is_show": true,
      "thumbnail_url": "https://..."
    }
  ]
}
```

---

### `svtplay-episodes`

Find a show by name and list all its available episodes with metadata. Internally calls search first, then scrapes the show page.

```bash
svtplay-episodes QUERY [OPTIONS]
```

| Option | Default | Description |
|--------|---------|-------------|
| `--json` | off | Output as JSON |
| `--threshold N` | 0.55 | Match confidence threshold (0–1) |

**Examples:**
```bash
uv run svtplay-episodes "bluey"
uv run svtplay-episodes --json "bluey"
```

**JSON output shape:**
```json
{
  "query": "bluey",
  "show": {
    "name": "Bluey",
    "url": "https://www.svtplay.se/bluey",
    "match_score": 1.0,
    "type": "KidsTvShow",
    "description": "...",
    "thumbnail_url": "https://..."
  },
  "episode_count": 47,
  "episodes": [
    {
      "svt_id": "eXY5Eqr",
      "name": "Burgarhund",
      "description": "Möt Bluey, Bingo och alla andra kära karaktärer igen!",
      "sub_heading": "Idag 04:55 • 1 min 42 sek",
      "duration_seconds": 102,
      "url": "https://www.svtplay.se/video/eXY5Eqr",
      "canonical_url": "https://www.svtplay.se/video/eXY5Eqr/bluey/burgarhund",
      "air_date": "Idag 04:55",
      "badge": null,
      "thumbnail_url": "https://...",
      "available": true
    }
  ]
}
```

> **Note:** `description` is a show-level tagline — SVT does not expose per-episode synopses in their page data.

---

### `svtplay-tmdb`

Find the TMDB entry for an SVT Play show using LLM-assisted matching (Claude Haiku).
Used to get the TMDB show ID needed for S##E## episode tagging.

Results are cached to `.svtplay-cache/tmdb-match/` (repo root) with a 7-day TTL — repeated calls for the same show are instant and free. Override the location with `SVTPLAY_CACHE_DIR`.

Requires `ANTHROPIC_API_KEY` and `TMDB_API_KEY` (set in `.env` or via flags).

```bash
svtplay-tmdb QUERY [OPTIONS]
```

| Option | Default | Description |
|--------|---------|-------------|
| `--json` | off | Output as JSON |
| `--api-key KEY` | `$ANTHROPIC_API_KEY` | Anthropic API key |
| `--tmdb-key KEY` | `$TMDB_API_KEY` | TMDB API key |
| `--no_cache` | off | Skip cache and force a fresh lookup |
| `--threshold N` | 0.55 | SVT show match threshold (0–1) |

**Examples:**
```bash
uv run svtplay-tmdb "bluey"
uv run svtplay-tmdb --json "bluey"
uv run svtplay-tmdb --json --no_cache "bluey"   # force fresh
```

**JSON output shape:**
```json
{
  "query": "bluey",
  "svt_show": {
    "name": "Bluey",
    "url": "https://www.svtplay.se/bluey",
    "description": "Bluey älskar att leka!",
    "match_score": 1.0
  },
  "tmdb_match": {
    "tmdb_id": 82728,
    "tmdb_name": "Bluey",
    "original_name": "Bluey",
    "first_air_date": "2018-10-01",
    "overview": "...",
    "confidence": 0.95,
    "reasoning": "Perfect name match, same premise and characters."
  },
  "tmdb_episodes": [
    {
      "season_number": 1,
      "episode_number": 1,
      "name": "Den magiska xylofonen",
      "air_date": "2018-10-01",
      "overview": "Bluey och Bingo har en magisk xylofon...",
      "id": 1583478,
      "still_url": "https://image.tmdb.org/t/p/original/abc123.jpg"
    }
  ],
  "cached": true
}
```

> `tmdb_id` is `null` if Claude finds no confident match among the TMDB candidates.
> `tmdb_episodes` is included when `confidence >= 0.90` (or single TMDB result). Contains all episodes across all seasons with S/E numbers — used for S##E## file tagging.

---

### `svtplay-download`

Download new episodes of a show from SVT Play. Tracks what has already been downloaded so re-running only fetches new episodes. Files are named `S##E## Episode Name - Show Name.mp4` (requires API keys for S##E## numbering). SVT and TMDB metadata plus cover art are embedded via ffmpeg.

Download history is stored in `.svtplay-cache/downloads/<show>.json` (repo root). If the cache is empty, the tool falls back to reading `svt_id` tags from existing files via ffprobe — so pre-existing downloads are detected automatically.

Requires `ffmpeg` on PATH. `ANTHROPIC_API_KEY` and `TMDB_API_KEY` are optional but enable S##E## naming and richer metadata.

```bash
svtplay-download QUERY [OPTIONS]
```

| Option | Default | Description |
|--------|---------|-------------|
| `--output-dir DIR` | `~/Downloads/svtplay-dl/` | Where to save files |
| `--api-key KEY` | `$ANTHROPIC_API_KEY` | Anthropic API key (for TMDB matching) |
| `--tmdb-key KEY` | `$TMDB_API_KEY` | TMDB API key |
| `--dry-run` | off | Show what would be downloaded, no action |
| `--all` | off | Ignore cache, re-download everything |
| `--quality N` | best | Quality passed to svtplay-dl (e.g. `1080`) |
| `--no-cache` | off | Skip TMDB cache, force fresh lookup |
| `--threshold N` | 0.55 | SVT show match threshold (0–1) |
| `--json` | off | Machine-readable JSON output |

**Examples:**
```bash
uv run svtplay-download "Bluey"                    # download new episodes
uv run svtplay-download --dry-run "Bluey"          # preview without downloading
uv run svtplay-download --all "Bluey"              # re-download everything
uv run svtplay-download --json "Bluey"             # JSON progress + summary
uv run svtplay-download --output-dir ~/Videos "Bluey"
```

**Output files:**
```
~/Downloads/svtplay-dl/
└── Bluey/
    ├── S01E01 Den magiska xylofonen - Bluey.mp4
    ├── S01E02 Babyräddning - Bluey.mp4
    └── S02E14 Kudd-fort - Bluey.mp4
```

Without API keys, files are named `Episode Name - Show Name.mp4` (no S##E## prefix).

**JSON output shape:**
```json
{
  "query": "bluey",
  "show": "Bluey",
  "downloaded": [
    {
      "svt_id": "eXY5Eqr",
      "name": "Burgarhund",
      "filename": "S01E03 Burgarhund - Bluey.mp4",
      "season": 1,
      "episode": 3,
      "path": "/home/user/Downloads/svtplay-dl/Bluey/S01E03 Burgarhund - Bluey.mp4"
    }
  ],
  "failed": [],
  "skipped": 46
}
```

**Embedded metadata tags:**

| Tag | Atom | Example |
|-----|------|---------|
| Title | `©nam` | `Tippen` |
| Show | `tvsh` | `Bluey` |
| Season | `tvsn` | `1` |
| Episode number | `tves` | `34` |
| Episode ID | `tven` | `S01E34` |
| Network | `tvnn` | `SVT Play` |
| Air date | `©day` | `Sön 8 mar 07:05` |
| Description | `desc` / `©cmt` | `Bluey och...` |
| Cover art | `covr` | attached thumbnail |
| SVT ID | `----:com.apple.iTunes:SVT_ID` | `eXY5Eqr` |
| SVT URL | `----:com.apple.iTunes:SVT_URL` | `https://www.svtplay.se/video/eXY5Eqr` |
| TMDB show ID | `----:com.apple.iTunes:TMDB_SHOW_ID` | `82728` |

Custom fields are stored as iTunes freeform atoms (`----:com.apple.iTunes:*`) which survive the MP4 container. Cover art is attached as an `attached_pic` stream — displayed automatically in VLC, Infuse, and most media players. Use `svtplay-meta` to inspect what is embedded in any file.

---

### `svtplay-meta`

Read and display metadata embedded in a video file. Useful for inspecting tags and for checking whether a file needs backfilling before running `svtplay-backfill-apply`.

```bash
svtplay-meta FILE [OPTIONS]
```

| Option | Default | Description |
|--------|---------|-------------|
| `--json` | off | Output as JSON |
| `--missing-only` | off | Only print fields that are absent (fast batch check) |

**Examples:**
```bash
uv run svtplay-meta "S01E34 Tippen - Bluey.mp4"
uv run svtplay-meta --json "S01E34 Tippen - Bluey.mp4"
uv run svtplay-meta --missing-only "S01E34 Tippen - Bluey.mp4"
```

**Human-readable output:**
```
File    : S01E34 Tippen - Bluey.mp4
Size    : 80.0 MB
Duration: 7m 0s  |  192 kbps

  Title       : Tippen
  Show        : Bluey
  Season      : 1
  Episode     : 34
  Episode ID  : S01E34
  Network     : SVT Play
  Air date    : Sön 8 mar 07:05
  Cover art   : [cover art, 366278 bytes]
  Description : Bluey och hennes syster Bingo...

  Custom fields:
  SVT ID      : eXY5Eqr
  SVT URL     : https://www.svtplay.se/video/eXY5Eqr
  TMDB show ID: 82728

  Needs backfill : no
```

**JSON output shape:**
```json
{
  "file": "/path/to/S01E34 Tippen - Bluey.mp4",
  "tags": {
    "©nam": "Tippen",
    "tvsh": "Bluey",
    "tvsn": 1,
    "tves": 34,
    "----:com.apple.iTunes:SVT_ID": ["eXY5Eqr"],
    "----:com.apple.iTunes:SVT_URL": ["https://www.svtplay.se/video/eXY5Eqr"],
    "----:com.apple.iTunes:TMDB_SHOW_ID": ["82728"],
    "_duration_seconds": 420,
    "_bitrate_kbps": 192
  },
  "missing": [],
  "needs_backfill": false
}
```

> **Batch use:** pipe `--missing-only` over a whole directory to quickly find which files need backfilling:
> ```bash
> for f in ~/Downloads/svtplay-dl/Bluey/*.mp4; do uv run svtplay-meta --missing-only "$f"; done
> ```

---

### `svtplay-backfill-info` + `svtplay-backfill-apply`

Two-step agent workflow for embedding metadata into pre-existing downloaded files that are missing S##E## prefixes and/or metadata tags.

**When to use:** you have video files downloaded outside of `svtplay-download` (or downloaded before metadata embedding was added) and want to retroactively add proper naming and tags.

#### Step 1 — gather data for the agent

```bash
svtplay-backfill-info SHOW [--files FILE ...] [--dir DIR] [OPTIONS]
```

| Option | Default | Description |
|--------|---------|-------------|
| `--files FILE` | — | Specific video files to backfill (repeatable) |
| `--dir DIR` | — | Scan directory for all video files |
| `--tmdb-key KEY` | `$TMDB_API_KEY` | TMDB API key (triggers fresh lookup if not cached) |
| `--api-key KEY` | `$ANTHROPIC_API_KEY` | Anthropic API key (needed for fresh TMDB lookup) |
| `--threshold N` | 0.55 | SVT show match threshold |

```bash
uv run svtplay-backfill-info "Bluey" --dir ~/Downloads/svtplay-dl/Bluey
uv run svtplay-backfill-info "Bluey" --files episode1.mp4 episode2.mp4
```

**JSON output** (feed to the agent):
```json
{
  "show": "Bluey",
  "svt_show_url": "https://www.svtplay.se/bluey",
  "tmdb_show_id": 82728,
  "files": [
    {"path": "/abs/path/Burgarhund - Bluey.mp4", "filename": "Burgarhund - Bluey.mp4"}
  ],
  "svt_episodes": [
    {"svt_id": "eXY5Eqr", "name": "Burgarhund", "url": "https://www.svtplay.se/video/eXY5Eqr",
     "thumbnail_url": "https://...", "air_date": "2022-03-01"}
  ],
  "tmdb_episodes": [
    {"season_number": 1, "episode_number": 3, "name": "Burgarhund",
     "air_date": "2018-10-15", "still_url": "https://image.tmdb.org/t/p/original/..."}
  ],
  "instructions": "Match each entry in 'files' to the best matching entries in 'svt_episodes' and 'tmdb_episodes'..."
}
```

> **Agent matching hint:** The agent receives filenames, SVT episode names/IDs, and TMDB season+episode data. Use name similarity between `filename` and `svt_episodes[].name` / `tmdb_episodes[].name` to determine the correct mapping. The `still_url` and `thumbnail_url` are full browser-pasteable URLs.

#### Step 2 — apply the agent's decisions

```bash
svtplay-backfill-apply JSON_STRING [OPTIONS]
echo '...' | svtplay-backfill-apply -
```

| Option | Default | Description |
|--------|---------|-------------|
| `--dry-run` | off | Preview renames/embeds without modifying files |
| `--no-rename` | off | Embed metadata only, skip renaming |
| `--json` | off | Machine-readable output |

**Input JSON shape** (agent provides this):
```json
{
  "show": "Bluey",
  "matches": [
    {
      "file": "/abs/path/Burgarhund - Bluey.mp4",
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
```

Each matched file is:
1. Renamed to `S01E03 Burgarhund - Bluey.mp4` (unless `--no-rename`)
2. Embedded with full SVT + TMDB metadata tags and cover art via ffmpeg
3. Recorded in `.svtplay-cache/downloads/<show>.json` so future `svtplay-download` runs skip it

---

## Agent usage

These tools are designed to be composed. For example, to answer "how many episodes of Bluey are there?":

```bash
uv run svtplay-episodes --json "bluey"
# → read episode_count from response
```

To get the TMDB ID for S##E## tagging:

```bash
uv run svtplay-tmdb --json "bluey"
# → read tmdb_match.tmdb_id
```

To find a show URL before downloading:

```bash
uv run svtplay-search --json --shows-only "bluey"
# → read results[0].url
```

To download all new episodes of a show:

```bash
uv run svtplay-download "bluey"
# → saves to ~/Downloads/svtplay-dl/Bluey/, skips already-downloaded episodes
```

To check what metadata is embedded in a file (or whether it needs backfilling):

```bash
uv run svtplay-meta --json "S01E34 Tippen - Bluey.mp4"
# → read needs_backfill, missing[]
```
