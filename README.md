# svtplay CLI tools

Download and manage SVT Play content with proper S##E## naming and embedded metadata.

The primary workflow is `svtplay-download-missing` — point it at a local folder and a show name, and it downloads everything on SVT Play that you don't already have. Uses embedded `SVT_URL` metadata as the ground-truth fingerprint, so no fragile filename matching.

## Prerequisites

- Python 3.9+
- [`ffmpeg`](https://ffmpeg.org/) on PATH (required for metadata embedding)
- `ANTHROPIC_API_KEY` — Claude for LLM-assisted TMDB show matching
- `TMDB_API_KEY` — fetches season/episode numbers for S##E## naming

Set API keys in a `.env` file:

```
ANTHROPIC_API_KEY=sk-ant-...
TMDB_API_KEY=...
```

## Install

```bash
pip install -e .
```

## Primary workflow

### `svtplay-download-missing`

Download episodes that are on SVT Play but not in your local folder.

```bash
svtplay-download-missing FOLDER SHOW [OPTIONS]
```

```bash
# See what would be downloaded (dry run)
svtplay-download-missing "~/Videos/Bluey" Bluey --dry-run

# Download everything missing
svtplay-download-missing "~/Videos/Bluey" Bluey

# Custom output dir (defaults to FOLDER's parent)
svtplay-download-missing "~/Videos/Bluey" Bluey --output-dir "~/Videos"
```

| Option | Default | Description |
|--------|---------|-------------|
| `--output-dir DIR` | parent of FOLDER | Where to save new files |
| `--dry-run` | off | Preview without downloading |
| `--quality N` | best | Quality passed to svtplay-dl (e.g. `1080`) |
| `--no-cache` | off | Force fresh TMDB lookup |
| `--json` | off | Machine-readable JSON output |

**How it works:**
1. Scans FOLDER for `.mp4`/`.webm`/`.mkv` files and reads the `SVT_URL` tag embedded in each
2. Fetches the current SVT Play episode list for SHOW
3. Downloads only episodes whose SVT ID is not already in your local files
4. Embeds full metadata (show, season, episode, SVT ID/URL, TMDB ID, cover art) into each new file

**Output files** land in `FOLDER` (or `--output-dir/Show Name/`):
```
~/Videos/Bluey/
├── S01E01 Den magiska xylofonen - Bluey.mp4
├── S01E02 Sjukhus - Bluey.mp4
└── S03E44 Vilda tjejer - Bluey.mp4
```

---

## Supporting commands

### `svtplay-scan`

Crawl a folder and dump embedded metadata from all video files as JSON. Useful for auditing your library.

```bash
svtplay-scan FOLDER [--show NAME] [--no-recursive]
```

```bash
svtplay-scan "~/Videos"
svtplay-scan "~/Videos" --show Bluey
```

Output is grouped by show, with each episode's season, episode number, title, SVT ID, and TMDB show ID.

---

### `svtplay-diff`

Three-way comparison: local files vs SVT Play (currently available) vs TMDB (all episodes ever aired).

```bash
svtplay-diff FOLDER SHOW [OPTIONS]
```

```bash
# Full picture
svtplay-diff "~/Videos/Bluey" Bluey

# Only missing episodes available for download now
svtplay-diff "~/Videos/Bluey" Bluey --downloadable-only

# Only episodes you're missing (including expired ones)
svtplay-diff "~/Videos/Bluey" Bluey --missing-only
```

| Option | Default | Description |
|--------|---------|-------------|
| `--downloadable-only` | off | Only missing + currently on SVT |
| `--missing-only` | off | All missing (including expired) |
| `--svt-url URL` | auto | Skip SVT search, use this show URL |

Each episode in the output has `local`, `svt_available`, and `svt_id` fields. The `summary` block gives counts.

---

### `svtplay-meta`

Inspect metadata embedded in a single video file.

```bash
svtplay-meta FILE [--json] [--missing-only]
```

```bash
svtplay-meta "S01E34 Tippen - Bluey.mp4"
svtplay-meta --json "S01E34 Tippen - Bluey.mp4"
svtplay-meta --missing-only "S01E34 Tippen - Bluey.mp4"
```

---

### `svtplay-backfill-info` + `svtplay-backfill-apply`

Two-step workflow for adding proper metadata to files that were downloaded outside of this tool (or before metadata embedding was added).

**Step 1** — generate a JSON payload the agent uses to match files to episodes:

```bash
svtplay-backfill-info SHOW --dir ~/Videos/Bluey
```

**Step 2** — apply the agent's matched decisions:

```bash
echo '...' | svtplay-backfill-apply -
svtplay-backfill-apply JSON_STRING [--dry-run] [--no-rename]
```

Each matched file is renamed to `S##E## Title - Show.mp4` and gets full metadata embedded.

---

## Cache

SVT episode lists and TMDB match results are cached in `.svtplay-cache/` (repo root, gitignored). TTLs:

| Data | TTL |
|------|-----|
| SVT episode list | 1 day |
| TMDB show match | 7 days |

Override location with `SVTPLAY_CACHE_DIR` env var.

## Embedded metadata tags

| Tag | Example |
|-----|---------|
| Title | `Tippen` |
| Show | `Bluey` |
| Season / Episode | `1` / `34` |
| Episode ID | `S01E34` |
| Air date | `2018-10-01` |
| Cover art | attached thumbnail |
| SVT ID | `eXY5Eqr` |
| SVT URL | `https://www.svtplay.se/video/eXY5Eqr` |
| TMDB show ID | `82728` |
