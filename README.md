# Media Organizer & Audit Engine

A headless media-library auditor: catalogs your Movies/TV folders, identifies titles (from Jellyfin `.nfo` files, falling back to TMDB/TVDB), and surfaces duplicates, quality variants, missing episodes, and subtitle gaps — then lets you safely quarantine, relocate, and fix files from a web dashboard.

Runs **on a single machine** (media on a local, external, or mounted drive) or in a **NAS + PC split** (scan on the NAS, dashboard on a PC over SMB). Cross-platform (Windows/macOS/Linux).

- 👤 **Using it?** Read **[RUNBOOK.md](RUNBOOK.md)** — a plain-language user guide.
- 🏗️ **Design spec & as-built status:** [Plan3.md](Plan3.md).
- 🤖 **Working on the code (Claude/devs):** [CLAUDE.md](CLAUDE.md).

## What it does

- **Catalog** every media file (path, size, name, season/episode, sidecars) — fast inventory pass, no heavy reads.
- **Identify** titles from Jellyfin/Kodi `.nfo` IDs (free, accurate), with a TMDB/TVDB lookup fallback.
- **Duplicate triage** — groups same-name copies in a folder, **split into Same length / Diff length** by runtime. Each copy shows **runtime / resolution / codec / embedded subtitles / container internal title** (probed on demand), flags filename-vs-embedded-title mismatches, and warns when copies are *different versions* rather than true duplicates. You can delete **any** copy (the "KEEP?" is just a hint).
- **Cleanup** — one-click quarantine of legacy-format files that already have a modern copy.
- **Missing episodes** — diffs each show's full TVDB episode list against what's on disk (specials excluded).
- **Subtitles** — checks for embedded English tracks, and fetches/unzips/cleans/renames external subs from OpenSubtitles (session-only login, daily-quota aware).
- **Fix & relocate** — re-identify a mislabeled file and move it to the correct Jellyfin path/folder.
- **Mismatch Videos** — find movie folders whose video file name ≠ the folder name (CDn parts, scene-named files, stray episodes) and relocate/quarantine them.
- **Audio-language flag** (optional, configurable) — list movies whose audio track is in your configured language(s) and move just the video into a staging folder. Off until you set `audio_flag.languages` (e.g. `["ara"]` to flag Arabic audio).
- **Organize Folder** — point at a loose folder of TV files; reads embedded show/season/episode tags, identifies on TVDB, and previews a per-file rename into Jellyfin layout (with subtitle move + leftover cleanup) before moving.
- **Admin** — **Sync deletions** (reconcile files deleted outside the app), **Quarantine browser** (see parked size / purge to reclaim space), **Enrichment jobs** (run the probe + re-match unmatched), **DB backup/integrity**, catalog freshness, and OpenSubtitles quota.
- **Play** — open any file in your media player (auto-detected VLC, else the OS default) to preview before deciding.
- **Safe by default** — "delete" = move to a central quarantine; every destructive action previews first.

## Prerequisites

Install these **before** running setup:

**1. Python 3.12+** — check with `python --version`. Get it from [python.org](https://www.python.org/downloads/) (on Windows, tick "Add Python to PATH" in the installer).

**2. ffmpeg / ffprobe** — required for runtime/codec/audio info, the Duplicates length split, the audio-language flag, and the Probe panel. (The basic inventory scan works without it, but most features won't.) Install per your OS, then make sure `ffprobe` is on your PATH:

| OS | Command |
|----|---------|
| Windows | `winget install ffmpeg`  (or `choco install ffmpeg`, or download from [ffmpeg.org](https://ffmpeg.org/download.html) and add its `bin` folder to PATH) |
| macOS | `brew install ffmpeg` |
| Linux (Debian/Ubuntu) | `sudo apt install ffmpeg` |
| Linux (Fedora/RHEL) | `sudo dnf install ffmpeg` |

Verify with `ffprobe -version`. It's auto-detected; if it lives somewhere off PATH, set `ffprobe.binary` in `config.yaml` to its full path. If it's missing, the dashboard prints a clear warning at startup and `probe_dupes.py` stops with an install hint.

**3. VLC** *(optional)* — the "Play" button auto-detects VLC; without it, files open in your OS default player. Get it from [videolan.org](https://www.videolan.org/).

## Setup

```bash
pip install -r requirements.txt
python setup_wizard.py               # interactive wizard -> writes config.yaml
cp .env.example .env                 # (optional) put your API keys here
```

Prefer to edit by hand? `cp config.example.yaml config.yaml` and edit it. API keys go in `.env` (recommended) or `config.yaml`; precedence is **environment > .env > config.yaml**. Both `config.yaml` and `.env` are gitignored.

### Single-machine vs NAS+PC split

- **Single machine (default):** point `media_paths` at your local/mounted folders and leave `path_map: {}`. Everything runs in one place.
- **NAS + PC split:** scan on the NAS (`scan_live.py`), run the dashboard on a PC, and set `path_map` so the catalog's NAS paths translate to SMB for disk operations. See [RUNBOOK.md](RUNBOOK.md) §2.

The Movies/TV roots are matched by name — one path containing "movie", one containing "tv"/"show".

## Run

```bash
python -m pytest -q                   # test suite
python scan_live.py config.yaml       # build/refresh the catalog
python run_dashboard.py config.yaml   # dashboard at http://localhost:8080
python cli_engine.py config.yaml      # CLI engine (task menu)
```

## Architecture (two entry points over a shared SQLite catalog)

- `cli_engine.py` — interactive task menu over the module layer.
- `web_dashboard.py` — `create_app(...) -> FastAPI`; tabbed dashboard. `run_dashboard.py` serves it.
- Operational runners: `scan_live.py` (inventory scan), `read_nfo_ids.py` (IDs from `.nfo`), `prune_live.py` (remove rows for deleted files), `gaps_live.py` (cache TVDB episode lists), `probe_dupes.py` (ffprobe runtimes/audio), `match_live.py` (API match fallback).
- Logic lives in small, independently-tested modules under `src/`. External effects (ffprobe, HTTP, disk) are injected, so the suite runs fully offline.
