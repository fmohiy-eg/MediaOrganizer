# PLAN — NAS Media Organizer & Audit Engine Specification

> **Status:** Implemented and running against the live NAS (as of 2026-06-23). Core
> ingest, identify, dedup-triage, deletion, and subtitle-fetch flows are built and
> tested (~130 tests). This document is the design spec; **Section 16 records what is
> as-built, what diverged from this spec (and why), and what is not yet built.**
> Where Sections 1–15 conflict with Section 16, Section 16 is authoritative.

---

## 1. Architectural Overview & Environment Scope

### 1.1 Target Environment

> **As-built note:** Docker was not used; the app runs split across the NAS (scan/`.nfo`) and the Windows PC (dashboard). See **§16.1** — it supersedes the deployment text below.

- **Host Platform:** QNAP NAS.
- **Primary Deployment:** Docker via QNAP Container Station. The image bundles Python and `ffmpeg`/`ffprobe`. Media shares, `/config`, `/logs`, and the central quarantine directory are mapped in as volumes.
- **Secondary Deployment:** Native execution over SSH using the host's Python. `ffmpeg`/`ffprobe` must be installed separately by the user. Supported but not the primary target.
- **Configuration:** A single local `config.yaml` (see Section 2).
- **Hardware Footprint:** Exclusively CPU-bound and I/O-optimized. No GPU acceleration or hardware transcoding. Design patterns minimize disk read overhead by caching results in the database and using lightweight partial hashes instead of reading full multi-gigabyte files on every scan.
- **Storage Calculation Standard:** All storage footprints, file sizes, and reclaimable-space metrics use the **Classic Decimal Standard** (1 KB = 1,000 bytes, 1 GB = 1,000,000,000 bytes) to align with disk-vendor reporting.
- **Jellyfin Interoperability:** The application detects and indexes Jellyfin sidecar metadata (`.nfo`, artwork) and indexing structures (`.trickplay/` folders) without treating them as library clutter, and executes cascading purges cleanly whenever a corresponding video file is removed.

### 1.2 File Layout Topology

The app is split into two operational boundaries that communicate entirely through a shared database layer:

- **`cli_engine.py` (The Data Engine):** A single script driving a keyboard-interactive loop (`while True`) that runs file-system discovery, fingerprinting, stream analysis, API metadata linking, and database pruning.
- **`web_dashboard.py` (The Interactive Executor):** A self-contained **FastAPI** application embedding all HTML, JavaScript, and Tailwind CSS. It reads processed audits from the database, displays analytical dashboards, handles OpenSubtitles fetch/upload ingestion, and manipulates files. Long-running operations (subtitle fetches, cascading deletes, relocations) run as FastAPI **background tasks** so the UI never blocks.
- **`media_audit.db` (The Relational Data Store):** An SQLite3 database caching all filesystem geometries, media stream configurations, external API results, and sidecar states.

### 1.3 Safety Posture (applies system-wide)

- **Dry-run by default:** Every destructive operation (delete, quarantine move, relocation, rename) first produces a preview of exactly what *would* happen. Nothing is moved or modified until the user explicitly confirms the previewed action.
- **Non-destructive deletion:** "Delete" never means `unlink`. It means move-to-quarantine (Section 6).
- **Two-tier duplicate confirmation:** No file is ever treated as an exact byte-duplicate of another based on a partial hash alone (Section 4.1).

---

## 2. Configuration (`config.yaml`)

All policy values have sensible built-in defaults so the app runs out-of-the-box; every value below is overridable in `config.yaml`. The app validates this file on startup (CLI task [5]).

```yaml
# --- Library paths (scanned recursively) ---
media_paths:
  - /media/Movies
  - /media/TV Shows

# --- Storage / runtime ---
database_path: /config/media_audit.db
log_directory: /logs
quarantine_path: /config/.quarantine     # single central quarantine (see Section 6)

# --- External API credentials ---
api_keys:
  tmdb: ""              # TMDB (movies)
  tvdb: ""              # TVDB v4 (TV + broadcast timeline)
  opensubtitles:
    api_key: ""
    username: ""
    password: ""

# --- Hashing thresholds ---
hashing:
  partial_hash_threshold_bytes: 20_000_000   # files larger than this use head/tail partial hashing
  partial_chunk_bytes: 10_000_000            # head & tail chunk size for fast_hash

# --- Audit thresholds ---
audit:
  duration_deviation_seconds: 120            # Release Protection tolerance vs. theatrical runtime
  variant_priority:                          # quality ranking order (first = strongest)
    - resolution
    - bitrate
    - codec        # HEVC/AV1 preferred over H.264
    - audio_channels

# --- External tooling ---
ffprobe:
  timeout_seconds: 30
  retries: 3

# --- API behavior ---
api:
  max_retries: 2
  retry_backoff_seconds: 5
  cache_ttl_days: 30

# --- Scan behavior ---
scan:
  worker_threads: 4
  # As-built default also includes legacy formats so old dupes surface:
  # .m4v .mov .ts .wmv .webm .rm .rmvb .mpg .mpeg .flv .vob .m2ts .divx
  valid_extensions: [".mkv", ".mp4", ".avi"]

# --- Safety ---
safety:
  dry_run_default: true                      # preview before any destructive action

# --- As-built additions (see §16) ---
# ffprobe.binary: C:/.../tools/ffprobe.exe   # absolute path; dashboard probes on demand
# path_map:                                  # translate catalog (NAS) paths -> SMB for off-NAS dashboard
#   "/share/TV Shows": "\\\\host\\TV Shows"
#   "/share/Movies": "\\\\host\\Movies"
```

---

## 3. Core SQLite3 Relational Database Schema

```sql
-- Core Media Inventory Table
CREATE TABLE IF NOT EXISTS media_files (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    filepath TEXT UNIQUE NOT NULL,
    filename TEXT NOT NULL,
    extension TEXT NOT NULL,
    parent_directory TEXT NOT NULL,
    file_size_bytes INTEGER NOT NULL,
    fast_hash TEXT NOT NULL,              -- Head/Tail 10MB composite signature (CANDIDATE match only)
    full_hash TEXT,                       -- Full-file SHA256, computed lazily to CONFIRM exact duplicates
    os_hash TEXT NOT NULL,                -- OpenSubtitles 64-bit hash (filesize + first/last 64KB)
    duration_ms INTEGER,                  -- ffprobe running length
    bitrate INTEGER,                      -- ffprobe overall file bitrate
    resolution_width INTEGER,             -- ffprobe video track pixel width
    resolution_height INTEGER,            -- ffprobe video track pixel height
    video_codec TEXT,                     -- ffprobe codec identifier (hevc, h264, av1)
    color_profile TEXT,                   -- ffprobe dynamic range profile (SDR, HDR10, DV)
    audio_languages TEXT,                 -- JSON array of audio language tags, e.g. '["eng","ara"]'
    has_english_audio TEXT,               -- 'yes' | 'no' | 'unknown'  (see Section 5.4)
    audio_profile TEXT,                   -- Primary audio codec + channels, e.g. 'DTS-HD 7.1'
    metadata_id TEXT,                     -- Namespaced ID: 'tmdb:<id>' (movie) or 'tvdb:<id>' (TV)
    match_status TEXT,                    -- 'matched' | 'unmatched' | 'ambiguous' (NULL until matched)
    item_type TEXT CHECK(item_type IN ('movie', 'episode')),
    season_number INTEGER,                -- Parsed from filename (NULL for movies)
    episode_number INTEGER,               -- Parsed from filename (NULL for movies)
    episode_number_end INTEGER,           -- For multi-episode files (S01E01-E02); NULL otherwise
    last_scanned TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- External Subtitle Relationships
CREATE TABLE IF NOT EXISTS external_subtitles (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    media_file_id INTEGER NOT NULL,
    filepath TEXT UNIQUE NOT NULL,
    language_tag TEXT,                    -- Parsed from filename suffix (e.g. 'eng', 'ara')
    is_sdh INTEGER DEFAULT 0,             -- Boolean (0/1) for Hearing Impaired tags
    is_forced INTEGER DEFAULT 0,          -- Boolean (0/1) for Forced tracks
    FOREIGN KEY(media_file_id) REFERENCES media_files(id) ON DELETE CASCADE
);

-- Jellyfin Sidecar Asset Tracker
CREATE TABLE IF NOT EXISTS sidecar_assets (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    media_file_id INTEGER NOT NULL,
    asset_path TEXT UNIQUE NOT NULL,
    asset_type TEXT CHECK(asset_type IN ('nfo', 'trickplay_dir', 'artwork', 'subtitle', 'scene_junk')),
    FOREIGN KEY(media_file_id) REFERENCES media_files(id) ON DELETE CASCADE
);
-- NOTE: 'subtitle' MUST be allowed — the scanner classifies .srt/.ass as 'subtitle';
-- omitting it makes INSERT OR IGNORE silently drop every subtitle sidecar.

-- API Meta-Cache (prevents redundant external API rate-limiting)
CREATE TABLE IF NOT EXISTS metadata_cache (
    metadata_id TEXT PRIMARY KEY,         -- Namespaced 'tmdb:<id>' or 'tvdb:<id>'
    title TEXT NOT NULL,
    release_date TEXT,
    theatrical_duration_minutes INTEGER,
    episode_map TEXT,                     -- JSON structure tracking air dates up to present
    last_updated TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    expires_at TIMESTAMP                  -- Set to last_updated + cache_ttl_days; refreshed on access
);

-- Indexes (REQUIRED): the subtitle-deficit / audit queries run correlated subqueries
-- against sidecar_assets; without these they degrade to O(media × sidecars) and hang at scale.
CREATE INDEX IF NOT EXISTS idx_sidecar_media ON sidecar_assets(media_file_id);
CREATE INDEX IF NOT EXISTS idx_subtitle_media ON external_subtitles(media_file_id);
CREATE INDEX IF NOT EXISTS idx_media_metadata ON media_files(metadata_id);
CREATE INDEX IF NOT EXISTS idx_media_parent ON media_files(parent_directory);
```

**Schema notes**
- `metadata_id` is **namespaced** so TMDB and TVDB IDs cannot collide in the same column.
- `fast_hash` is a *candidate* signature only; `full_hash` is the authoritative exact-duplicate key and is computed lazily (Section 4.1).
- `has_english_audio` is a tri-state field; the subtitle rule engine (Section 5.4) reads it directly.
- `expires_at` is part of the table from creation (no post-hoc `ALTER TABLE`).
- **Thread safety:** all database writes are serialized through a single threading lock; the connection uses WAL mode to allow concurrent reads during scans.

---

## 4. Fingerprinting & Hashing

### 4.1 Two-Tier Exact-Duplicate Detection

Exact (byte-identical) duplicate detection is a **two-tier** process to balance speed against correctness:

1. **Tier 1 — `fast_hash` (candidate):** For files larger than `partial_hash_threshold_bytes`, SHA256 over the concatenation of the first and last `partial_chunk_bytes` (default 10MB each). For smaller files, SHA256 of the whole file. Computed on every scan. This produces *candidate* duplicate groups cheaply but is **not** proof of identity — two different files can share head and tail.
2. **Tier 2 — `full_hash` (confirmation):** A full-file SHA256, computed **only** for files inside a candidate group and **only** before any destructive action that relies on byte-equality. Two files are treated as exact duplicates **only** when their `full_hash` values match.

> Exact-byte deduplication (this section) is **distinct** from quality-variant grouping (Section 5.1). Quality variants are deliberately *not* byte-identical — they are different encodes of the same title — and are never compared by hash.

Reference implementation for Tier 1:

```python
import hashlib, os

def compute_fast_hash(filepath, threshold, chunk_size):
    size = os.path.getsize(filepath)
    if size <= threshold:
        with open(filepath, 'rb') as f:
            return hashlib.sha256(f.read()).hexdigest()
    with open(filepath, 'rb') as f:
        first_chunk = f.read(chunk_size)
        f.seek(-chunk_size, os.SEEK_END)
        last_chunk = f.read(chunk_size)
    return hashlib.sha256(first_chunk + last_chunk).hexdigest()
```

### 4.2 OpenSubtitles Hash (`os_hash`)

The `os_hash` is the **official OpenSubtitles hash**: a 64-bit checksum equal to the file size plus the sum of all 64-bit little-endian integers across the first 64KB and the last 64KB of the file (modulo 2^64). The filesize term is mandatory — omitting it makes every subtitle lookup miss.

```python
import struct, os

def compute_os_hash(filepath):
    longlong_fmt = '<q'
    size = os.path.getsize(filepath)
    chunk = 64 * 1024
    h = size
    with open(filepath, 'rb') as f:
        for _ in range(chunk // 8):
            h = (h + struct.unpack(longlong_fmt, f.read(8))[0]) & 0xFFFFFFFFFFFFFFFF
        f.seek(max(0, size - chunk), os.SEEK_SET)
        for _ in range(chunk // 8):
            h = (h + struct.unpack(longlong_fmt, f.read(8))[0]) & 0xFFFFFFFFFFFFFFFF
    return f"{h:016x}"
```

### 4.3 Stream Interrogation (ffprobe)

All `ffprobe` calls run with a timeout and retry per `config.yaml`:

```python
import subprocess, json

def probe_file(filepath, timeout, retries):
    for attempt in range(retries):
        try:
            result = subprocess.run(
                ["ffprobe", "-v", "quiet", "-print_format", "json",
                 "-show_format", "-show_streams", filepath],
                capture_output=True, text=True, timeout=timeout)
            if result.returncode == 0:
                return json.loads(result.stdout)
        except subprocess.TimeoutExpired:
            continue
    raise RuntimeError(f"ffprobe failed for {filepath} after {retries} attempts")
```

ffprobe collects: video resolution, codec, color/dynamic-range profile; all audio tracks (codec, channels, language tags); and embedded subtitle tracks.

---

## 5. `cli_engine.py` Processing Architecture

On launch, the script initializes a persistent menu inside a loop:

```
==================================================
        NAS Media Organizer & Audit Engine
==================================================
 [1] Scan File System & Index Media (Update DB)
 [2] Match Metadata via Online APIs (TMDB/TVDB)
 [3] Run Library Integrity & Gap Audit (Generate Reports)
 [4] Prune Stale Database Entries (Fast Sync)
 [5] Validate Configuration & API Connectivity
 [6] Export Offline Reports (Markdown/JSON)
 [7] Exit
==================================================
 Select a task to run (1-7): _
```

**Input validation:** the menu rejects non-numeric and out-of-range input and re-prompts until a valid `1–7` choice is entered.

```python
def get_valid_choice():
    while True:
        try:
            choice = int(input("Select task (1-7): "))
            if 1 <= choice <= 7:
                return choice
            print("Invalid selection. Enter a number between 1 and 7.")
        except ValueError:
            print("Invalid input. Enter a numeric value.")
```

### 5.1 [1] Scan File System & Index Media

- **Traversal:** Multi-threaded directory walker (`worker_threads`) crawling every path in `media_paths`.
- **Jellyfin noise filter:** Excludes `.trickplay` directories and structural assets from core inventory rows; matches `valid_extensions` for media and tracks sidecars dynamically into `sidecar_assets`.
- **Fingerprinting:** Computes `fast_hash` (Section 4.1) and `os_hash` (Section 4.2) for each media file.
- **Stream interrogation:** Background `ffprobe` calls (Section 4.3) populate video/audio/subtitle fields, including `audio_languages` and the derived `has_english_audio` tri-state (Section 5.4).
- **Incremental:** Files whose path + size + mtime are unchanged since `last_scanned` skip re-hashing and re-probing.

### 5.2 [2] Match Metadata via Online APIs

- **TV token fallback matrix:** Iterative regex sequence capturing standard `S01E01`, flat `1x01`, and legacy forms (Section 7.2). Detects multi-episode spans (`S01E01-E02`) and records `episode_number_end`, caching the mapping across both episode identities to prevent false gaps.
- **API matching:** Queries TMDB (movies) and TVDB (TV). Results are stored in `metadata_cache` and `metadata_id` is linked back to the inventory row.
- **Retry/skip:** API calls retry per `api.max_retries` with backoff, then skip gracefully.

```python
import time

def api_call_with_retry(func, max_retries, backoff):
    for attempt in range(max_retries + 1):
        try:
            return func()
        except Exception as e:
            if attempt < max_retries:
                print(f"API call failed (attempt {attempt + 1}): {e}")
                time.sleep(backoff)
            else:
                print("Maximum retries reached. Skipping...")
                return None
```

### 5.3 [3] Run Library Integrity & Gap Audit

- **Variant / redundant-copy grouping (quality, not byte-identity):** Groups files by **same folder + same base name, different extension** (`Movie.mkv`/`Movie.mp4`/`Movie.avi`), ranked by `audit.variant_priority` to suggest a keeper. **Do NOT group by `metadata_id`** — every episode of a show shares the series-level `tvdb:` id, and multi-part files (`CD1…CDn`) share one `movie.nfo`, so id-grouping yields catastrophic false "delete all but one" sets (see §16). Before suggesting deletion, confirm the copies are the same content by comparing **runtimes** (different runtimes / edition markers ⇒ different versions, not duplicates).
- **Release Protection System:** Cross-checks `duration_ms` against `theatrical_duration_minutes`. Files deviating by ≥ `duration_deviation_seconds`, or whose filename contains explicit edition markers (Director's Cut, Extended, Remastered), are isolated and **protected** from auto-deduplication to preserve distinct releases.
- **Cross-folder contamination audit:** Zero-trust path analysis. If an episode's matched series identity does not align with its physical parent folder, a high-severity mismatch is logged.
- **English Subtitle Baseline Rule Engine:** See Section 5.4.
- **Broadcast timeline gap analysis:** Compares TVDB airing schedules against the NAS's **current system date**. Episodes already broadcast but missing from disk are compiled into a strict "missing gaps" list. Episodes with future air dates are filed into a separate "Upcoming" view and never counted as gaps.

### 5.4 English Subtitle Baseline Rule Engine (with tri-state audio)

`has_english_audio` is derived during scan from ffprobe audio language tags:

- Any audio track tagged English (`eng`/`en`) → `yes`
- All audio tracks tagged a non-English language → `no`
- No usable tag (`und`, missing, empty) → `unknown`

The rule engine then flags missing English subtitles:

| `has_english_audio` | Missing English subtitle → flag |
|---------------------|---------------------------------|
| `no`                | **Critical Deficit** |
| `yes`               | **Minor Optimization** |
| `unknown`           | **Needs Review** (audio language undetermined — not auto-classified) |

The dashboard surfaces `unknown` items with their audio track count/codec so the user can judge them manually; the engine never guesses an undetermined language.

### 5.5 [4] Prune Stale Database Entries

High-speed path-existence loop over the database. Any `filepath` missing from disk is unlinked, cascading through `external_subtitles`, `sidecar_assets`, and related rows via `ON DELETE CASCADE`.

### 5.6 [5] Validate Configuration & API Connectivity

Validates `config.yaml` syntax and required fields, checks that each `media_paths` entry is reachable, verifies the quarantine path is writable, and tests TMDB/TVDB/OpenSubtitles credentials with a lightweight live call.

### 5.7 [6] Export Offline Reports

Compiles current audit tables into flat **Markdown** reports and raw **JSON** documents saved under `log_directory`.

### 5.8 [7] Exit

Breaks the shell loop and terminates gracefully (closing the DB connection).

---

## 6. Cascading Deletion & Quarantine Engine (Non-Destructive)

When a file is flagged for deletion:

- **Quarantine, never destroy:** Selected items move into a **single central** `quarantine_path` (configurable). Because quarantine is centralized, a move that originates on a *different* volume becomes a full copy-then-delete — slower for large files and temporarily doubling space usage until complete. This is an accepted, documented tradeoff.
- **Retention:** **Manual only.** Quarantined files remain until the user explicitly purges them via the dashboard "Empty Quarantine" action. Nothing is auto-destroyed or time-expired.
- **Symmetrical cascade hook:** Moves the deleted video's per-file sidecars alongside it (e.g. its `.nfo`, `-thumb.jpg`, `.trickplay/`), while **preserving** folder-global assets (`movie.nfo`, `tvshow.nfo`, `poster.jpg`, `fanart.jpg`, …).
- **Shared-sidecar preservation (critical):** When one movie/episode is stored in several formats, the copies share base-named sidecars (`Movie.nfo`, `Movie.eng.srt`, `Movie.trickplay`). A sidecar cascades **only if it is owned *exclusively* by the deleted file** — if any *surviving* same-name copy still claims it, it is preserved (the surviving copies still use it). Never strip the subtitle/nfo/trickplay off a kept copy.
- **Dry-run by default:** The engine first lists every path it would move (video + cascaded sidecars). Nothing moves until the user confirms.

---

## 7. Folder Structure & Naming Intelligence

> The rules below reflect the user's **actual library conventions** (sampled from `tv.txt`/`movies.txt`). The library uses Windows UNC paths (`\\host\Movies\01-Ready\Title (Year)\...`) with a workflow bucket folder (`01-Ready`) between the share root and each title folder. The parser must be path-separator agnostic (handle `\` and `/`).

### 7.1 Folder-Context Derivation (authoritative over filename)

Identity is derived from the **folder hierarchy first**, because filenames are inconsistent:

- **Series title + year:** from the series folder `Series (Year)` (e.g. `Dilbert (1999)`). Handle titles with hyphens (`Rick and Morty - The Anime (2024)`) and double parens (`Calls (US) (2021)` → title `Calls (US)`, year `2021` = the **last** parenthesized 4-digit group).
- **Season number:** from the season folder — `Season 01`, `Season 1`, `Season 2` (zero-padding inconsistent), or `Specials` → **season 0**.
- **Movie title + year:** from the movie folder `Title (Year)`.

### 7.2 Episode Number Parsing

The episode token is parsed from the **filename**, then reconciled with folder context (§7.1). Iterative regex matrix, in priority order:

- `S01E05`, `s01e05`
- `2x04`, `1x20`, `0x01` (specials) — flat multiplier `<season>x<episode>`
- Multi-episode spans `S01E01-E02` / `2x01-02` → records `episode_number_end`
- Legacy: `Season_1_Episode_5`, `Season 1 Episode 5`

**CRITICAL — title extraction:** episode titles can themselves contain ` - ` (real example: `Disney's House of Mouse (2001) - 0x01 - Mickey's Magical Christmas - Snowed in at the House of Mouse`). The parser MUST anchor on the season/episode token and treat **everything after it** as the title. Never split naively on ` - `.

If the parsed season/episode disagrees with the folder context (e.g. an `S02E04` file sitting in `Season 3`), that is a **cross-folder/placement mismatch** (logged by §5.3), not a parse error.

### 7.3 Artwork & Sidecar Classification

- **Episode artwork:** `{name} -thumb.jpg` → bound to that episode (cascades on delete).
- **Folder-global artwork (PRESERVED on delete):** `poster.jpg`, `fanart.jpg`, `folder.jpg`, `banner.jpg`, `backdrop.jpg`, `landscape.jpg`, `logo.png`, `disc.png`, `clearart.png`, `seasonNN-poster.jpg`, `season-specials-poster.jpg`.
- **Global NFOs (PRESERVED):** `tvshow.nfo`, `season.nfo`, `movie.nfo`. **Per-item NFOs (cascade):** `{episodename}.nfo`.
- **Scene junk (`scene_junk`):** torrent-site droppings — `*.txt` and images matching YIFY/YTS/Demonoid/ExtraTorrent/AhaShare/`*proxies*` (e.g. `WWW.YIFY-TORRENTS.COM.jpg`, `YTSProxies.com.txt`), and `Other/` subfolders of torrent text files. Flagged for cleanup; never treated as real artwork.

### 7.4 Legacy-Format Duplicates

Legacy video files (e.g. `.rm`) appearing beside a modern encode of the same episode (`.avi`/`.mp4`) are real duplicates the tool should surface as quality-variant/cleanup candidates. Legacy extensions are indexed (configurable) so they can be flagged, even though `ffprobe` may return limited stream data for them.

---

## 8. Smart Sidecar Management

### 8.1 Trickplay Folder Validation

- Cross-reference `.trickplay` directories with their parent video files.
- Detect orphaned `.trickplay` folders (parent `.mp4`/`.avi` missing).
- Track thumbnail-count consistency across frame sizes.

### 8.2 NFO File Schema Verification

- Validate NFO content structure for both movies and TV episodes.
- Ensure required metadata fields exist.
- Flag malformed or incomplete NFO entries.

---

## 9. `web_dashboard.py` — Presentation Interface (FastAPI)

A self-contained FastAPI app across six visual triage tabs. All destructive actions are **dry-run-by-default** (preview → confirm), and long operations run as background tasks.

### 9.1 Tab 1 — Quality & Variant Conflicts
Visualizes quality variants (Section 5.1) side-by-side, suggests a "Keeper" by quality score, and allows manual checkbox overrides before a batch action. Exact-byte duplicates (confirmed via `full_hash`) are shown as a separate, clearly-labeled category.

### 9.2 Tab 2 — Cross-Folder Contamination Tracker
Groups misplaced files with their sidecar attachments. One-click relocation migrates the asset bundle (video + cascaded sidecars) into the correct directory tree (dry-run preview first).

### 9.3 Tab 3 — Subtitle Deficit & Ingestion Hub
- **Auto-fetch:** `[⚡ Auto-Fetch Best Match]` sends the precomputed `os_hash` to OpenSubtitles for a perfectly-synced English subtitle; on hash miss, falls back to a text search query. Honors the account's download quota and surfaces quota errors clearly.
- **Manual upload zone:** Drag-and-drop for locally-sourced subtitles. Validates subtitle format and sanitizes/re-encodes the payload to clean UTF-8 before writing to disk.
- **Collision-prevention rename policy:** If `Movie.eng.srt` already exists at the target, the existing file is renamed sequentially (`Movie.eng.1.srt`, `Movie.eng.2.srt`) before the incoming file is written as the primary.

### 9.4 Tab 4 — Missing Episode Timeline Matrix
Lists missing broadcast episodes (already-aired only) mapped by season; "Upcoming" episodes shown in a separate, non-gap view.

### 9.5 Tab 5 — Metadata Override Console
Lets the user correct failed/ambiguous matches by entering explicit TMDB/TVDB URLs or IDs to re-index problem items.

### 9.6 Tab 6 — Executive Analytics & Library Health
- **KPI grid:** Total inventory count, total storage utilized, active triage-issue count, reclaimable space (decimal standard).
- **Charts (Chart.js CDN):**
  - **Donut:** Space split across Movies vs. TV vs. Jellyfin infrastructure assets (`.nfo`, `.trickplay` volumes).
  - **Bar:** Resolution distribution alongside codec-efficiency split (H.264 vs. HEVC/H.265 vs. AV1).
  - **Stacked progress:** Clean/audited assets vs. conflict queues.
- **Work-in-progress matrix:** Outstanding API parse failures, subtitle deficits, and empty folders left after purges.

---

## 10. Advanced Analytics

- **Per-season health breakdown:** Coverage charts per season (metadata/artwork/subtitle completeness); highlight whole-season gaps.
- **Cross-season duplicate detection:** Extend exact-duplicate matching (Section 4.1, two-tier) across seasons to catch identical content filed under different season/episode numbers.

---

## 11. Automated Remediation Tools

- **Bulk directory relocation:** One-click fix to move a misfiled episode to its correct `Season X` folder (e.g. move `S02E04` from `Season 3` to `Season 2`). Dry-run preview first.
- **Artwork & metadata consolidation:**
  - Rename artwork files based on detected episode title.
  - Migrate metadata between old and new naming conventions.
  - Create placeholder files when critical sidecars are missing.
- **Smart batch operations:** Apply metadata refresh or artwork renames across an entire season or series in one action.

---

## 12. Edge Case Handling

- **Mixed content folders:** Handle directories containing both episodes and movies (e.g. a series folder that also holds a related movie file), classifying each item by parse result rather than folder.
- **Legacy naming adapters:** Support `S01E05`, `s01e05`, `Season_1_Episode_5`, and `1x01` forms (Section 7.2).

---

## 13. Testing & Validation Strategy

- **Unit tests over the risky logic** against a small **synthetic fixture library** (a generated tree of tiny dummy files), covering:
  - Filename → season/episode/edition parsing (all forms in Section 7.2).
  - Variant ranking and Release Protection isolation.
  - `fast_hash` / `full_hash` / `os_hash` on tiny crafted files.
  - The tri-state audio derivation and subtitle rule engine (Section 5.4).
  - Cascade-deletion target selection (correct sidecars moved, folder-globals preserved).
- **APIs mocked:** TMDB/TVDB/OpenSubtitles responses are stubbed; no live network in tests.
- **No real media in tests:** all fixtures are byte-sized dummies.
- **Dry-run-by-default everywhere:** destructive paths are verified by asserting on the *preview/plan* output, not by performing real moves.

---

## 14. Performance Benchmarking

Scan operations report throughput based on **actual bytes processed** (not a fixed constant):

```python
import time

def benchmark_scan(perform_full_scan, directory_path):
    start = time.time()
    result = perform_full_scan(directory_path)   # returns {'file_count', 'bytes_processed'}
    elapsed = time.time() - start
    mb = result['bytes_processed'] / 1_000_000   # decimal standard
    print(f"Scanned {result['file_count']} files "
          f"({mb:.1f} MB) in {elapsed:.2f}s — {mb / elapsed:.2f} MB/s")
```

---

## 15. Open Risks & Non-Goals

**Risks (documented, accepted, or to revisit):**
- Central quarantine causes cross-volume copy cost + temporary double space usage (Section 6).
- OpenSubtitles free-tier download quota may throttle bulk subtitle fetching (Tab 3).
- TVDB schedule data accuracy bounds the Broadcast Timeline feature; specials/Season 0 and daily shows may need special handling (to refine during implementation planning).
- Partial `fast_hash` collisions are mitigated but never *fully* eliminated until `full_hash` confirmation runs (Section 4.1).

**Non-goals:**
- No GPU/hardware transcoding or any media re-encoding.
- No automatic, unattended permanent deletion — quarantine is always manual-purge.
- No multi-user accounts/auth (single-user personal tool).

---

## 16. Implementation Status & As-Built Notes (authoritative)

Cross-check of this spec against the running implementation (2026-06-23). Where this
section conflicts with Sections 1–15, this section wins.

### 16.1 Deployment — as-built (diverged from §1.1)

Docker/Container Station was **not** used. The app runs in two places at once:

- **Scanning + `.nfo` reading run ON the NAS over SSH** (local disk ≈1000× faster than SMB — an SMB scan was on track for ~3 days vs ~3.5 min locally). NAS has Python 3.12 but **no pip** (`PyYAML` is vendored into the app dir) and **no ffprobe** (stream fields stay blank there). Code is staged to the NAS via the SMB `Public` share; the user runs the SSH commands.
- **The dashboard runs on the Windows PC** (web framework + internet + SMB write + a local `tools/ffprobe.exe`). The catalog stores NAS paths (`/share/TV Shows/...`); `config.path_map` translates them to SMB (`\\host\...`) for file ops. `config.ffprobe.binary` is an **absolute** path.

Operational runners (not in §5's single CLI): `scan_live.py` (inventory scan + live progress), `read_nfo_ids.py` (IDs from `.nfo`), `match_live.py` (API fallback).

### 16.2 Scan — inventory mode is the default fast pass (refines §5.1)

Even partial hashing (20 MB/file) is too heavy at library scale (57k files ≈ 1 TB of reads). `scan_and_index(..., compute_hashes=False)` records path/size/name/sidecars only — **no byte reads, no ffprobe** — the catalog completes in minutes. Full hashing + the two-tier `full_hash` confirmation (§4.1) are a **separate, not-yet-wired** pass. The scanner also prunes NAS system dirs `.@__thumb`/`@Recycle` (they hold decoy media), and is resilient to vanished/unreadable files. Incremental skip is size-based (not mtime). `season_number`/`episode_number` are derived via `parse_path` at read time, not stored during inventory.

### 16.3 Identity — Jellyfin `.nfo` first (refines §5.2)

The library is Jellyfin-managed, so `.nfo` files already hold resolved `tmdb`/`tvdb` IDs. `read_nfo_ids.py` reads those directly (free, accurate — 97% coverage on the real library). API matching (`metadata_client`: TMDB v4 bearer, TVDB login→token) is the **fallback** for the ~3% without a `.nfo`. Ambiguous/failed matches are flagged for manual review, never guessed.

### 16.4 Subtitles — as-built (refines §9.3)

Built: session-only OpenSubtitles login (token in server memory, never persisted), search (api-key) → download (login token, quota surfaced) → unzip → UTF-8 → collision-safe rename to `<video>.eng.srt` → move next to the video. Deficit detection = "no external English `.srt` sidecar." **Caveats:** `os_hash` auto-fetch is **not** used (inventory skips `os_hash`; search is by `tmdb_id`/`query`+season/episode); **embedded** subtitle tracks are invisible without ffprobe, so the deficit list is an upper bound; the drag-and-drop **upload zone is not built**.

### 16.5 ffprobe / runtime safety (enhances §5.3 Release Protection)

The dashboard probes a duplicate group's files **on demand** via the local ffprobe (over SMB) and shows runtime/resolution/codec. `web.inspect.assess_versions` flags a group as "possibly different versions, not duplicates" when runtimes differ ≥ `audit.duration_deviation_seconds` or a filename carries an edition marker — this caught a 75-min `.avi` mixed in with a 182-min cut. The keeper is labeled "KEEP?" (a suggestion, never automatic).

### 16.6 Feature status

| Area | Status |
|------|--------|
| Inventory scan + prune (NAS) | ✅ Done (`scan_live.py` / `prune_live.py`; prune also available PC-side via **Admin → Sync deletions**, no SSH) |
| `.nfo` ID read / API match fallback | ✅ Done (`matcher.decide_match`: single/unique-year hit, plus a unique exact-title match guarded to episodes-or-year; Admin **Re-match** runs it over unmatched titles) |
| Two-tier exact-dup **confirmation pass** (`full_hash` on candidates) | ❌ Not wired (functions exist) |
| Duplicate triage (folder+name) split into **Same-length / Diff-length** tabs; per-copy runtime/resolution/codec/embedded-subs/**container internal title** + filename-vs-embedded mismatch flag; ▶ Play in VLC; delete any copy; per-file **→ Arabic** move | ✅ Done (`probe_dupes.py` runtimes/audio: full pass complete 2026-06-24 — 13,289 probed / 11 failed) |
| Quarantine cascade delete + shared-sidecar preservation | ✅ Done |
| Subtitle fetch (Tab 3, minus upload zone & os_hash) | 🟡 Partial |
| Cleanup tab — legacy-format duplicates (per-file + bulk quarantine) | ✅ Done |
| Overview KPIs | ✅ Done (no Chart.js charts yet) |
| Needs-Review list (unmatched) | ✅ Done |
| **Missing-episode timeline (Tab 4)** | ✅ Done — `gaps_live.py` caches each show's TVDB episode list; the Missing tab diffs vs. on-disk (Season 0 specials excluded). |
| **Organize Folder tab** — point at a loose folder; embedded ffprobe tags (incl. composite `title`) → TVDB → per-file before/after Jellyfin rename/move with Select-all batch, subtitle move + leftover cleanup (quarantine stray art/.nfo/trickplay, remove emptied folder); repoints existing catalog rows | ✅ Done (`web/organize.py`; embedded-tags-only by design) |
| **Admin tab (PC-only)** — Sync deletions (PC-side prune, no SSH), catalog freshness, OpenSubtitles quota, DB backup + integrity, Quarantine browser (size/purge), Enrichment jobs (managed probe start/stop + re-match unmatched) | ✅ Done (`web/sync.py`, `services.admin_status`, `_bg_run` jobs) |
| **Cross-folder contamination (Tab 2)** — `audit.contamination` exists, not surfaced/relocation tool | ❌ Not built |
| **Metadata override / fix & relocate (Tab 5 + §11 relocation)** | ✅ Done — "Fix" dialog: TMDB/TVDB lookup → Jellyfin path → create folder + move (movies & episodes), preview before move, DB repointed. |
| **Arabic-audio tab + move to `02-ArabicReady`** (movies with a tagged Arabic track; move just the video file, preview→confirm) | ✅ Done (`services.arabic_audio_movies` + `relocate.arabic_target`; tagged `ara`/`ar` only; also reachable via per-file **→ Arabic** link on the Dupes tabs) |
| **Mismatch Videos tab** — movie folders with a video file whose name ≠ the folder name (CDn parts, scene-named files, stray episodes); grouped by folder; per-file ▶ Play / **Fix** (relocate) / **Delete** (quarantine) | ✅ Done (`services.mismatched_videos`; movies-library scope, case-insensitive) |
| **Analytics charts (Tab 6)**, per-season health (§10) | ❌ Not built |
| **Remediation tools (§11)** — relocation, artwork/NFO consolidation | ❌ Not built |
| **Smart sidecar mgmt (§8)** — trickplay/NFO validation | ❌ Not built |
| **`scene_junk` classification (§7.3)** — `classify_path` doesn't emit it yet | ❌ Not built |
| **Embedded-subtitle awareness** | ✅ Done — on-demand via dashboard ffprobe (Duplicates "Embedded subs" column + Subtitles "Check built-in"). A full catalog-wide pass still needs ffprobe on the NAS. |
| Full-hash confirm UI, batch operations, CLI tasks [5]/[6] polish | ❌ Not built |

### 16.7 New/changed risks (adds to §15)

- SMB throughput forced NAS-side scanning + inventory mode; revisit if moving to Docker.
- No ffprobe on the NAS ⇒ stream fields blank in the catalog; runtime is fetched on demand from the dashboard's local ffprobe. Embedded subs/audio-language rule (§5.4) are therefore inactive in the catalog until ffprobe runs on the NAS.
- Grouping by `metadata_id` is a proven footgun (multi-part `CDxx`, shared `.nfo`) — see §5.3.

---

*This specification targets robust operation within the stated constraints while keeping the design simple and performant for personal use.*
