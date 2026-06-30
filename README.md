# NAS Media Organizer & Audit Engine

A headless media-library auditor for a QNAP NAS: catalogs your Movies/TV shares, identifies titles (from Jellyfin `.nfo` files, falling back to TMDB/TVDB), and surfaces duplicates, quality variants, missing episodes, and subtitle gaps — then lets you safely quarantine, relocate, and fix files from a web dashboard.

- 👤 **Using it?** Read **[RUNBOOK.md](RUNBOOK.md)** — a plain-language user guide.
- 🏗️ **Design spec & as-built status:** [Plan3.md](Plan3.md) (see **Section 16** for what's built vs. not).
- 🤖 **Working on the code (Claude/devs):** [CLAUDE.md](CLAUDE.md).

## What it does

- **Catalog** every media file (path, size, name, season/episode, sidecars) — fast inventory pass, no heavy reads.
- **Identify** titles from Jellyfin/Kodi `.nfo` IDs (free, accurate), with a TMDB/TVDB lookup fallback.
- **Duplicate triage** — groups same-name copies in a folder, **split into two tabs (Same length / Diff length)** by runtime. Each copy shows **runtime / resolution / codec / embedded subtitles / container internal title** (probed on demand), flags filename-vs-embedded-title mismatches, and warns when copies are *different versions* (different runtime or "Director's Cut") rather than true duplicates. You can delete **any** copy (the "KEEP?" is just a hint).
- **Cleanup** — one-click quarantine of legacy-format files that already have a modern copy.
- **Missing episodes** — diffs each show's full TVDB episode list against what's on disk (specials excluded).
- **Subtitles** — checks for embedded English tracks, and fetches/unzips/cleans/renames external subs from OpenSubtitles (session-only login, daily-quota aware).
- **Fix & relocate** — re-identify a mislabeled file and move it to the correct Jellyfin path/folder.
- **Mismatch Videos** — find movie folders whose video file name ≠ the folder name (CDn parts, scene-named files, stray episodes) and relocate/quarantine them.
- **Arabic Audio** — list movies with a tagged Arabic track and move just the video to `02-ArabicReady`.
- **Organize Folder** — point at a loose folder of TV files; reads embedded show/season/episode tags, identifies on TVDB, and previews a per-file rename into Jellyfin layout (with subtitle move + leftover cleanup) before moving.
- **Admin** (PC-only) — **Sync deletions** (reconcile files deleted outside the app, no SSH), **Quarantine browser** (see parked size / purge to reclaim space), **Enrichment jobs** (run the probe + re-match unmatched), **DB backup/integrity**, catalog freshness, and OpenSubtitles quota.
- **Play** — open any file in VLC to preview before deciding.
- **Safe by default** — "delete" = move to a central quarantine on the NAS; every destructive action previews first.

## Architecture (two entry points over a shared SQLite catalog)

- `cli_engine.py` — interactive 7-task menu over the module layer.
- `web_dashboard.py` — `create_app(...) -> FastAPI`; tabbed dashboard (Overview · Dupes·Same-length · Dupes·Diff-length · Mismatch Videos · Cleanup · Missing Episodes · Subtitles · Arabic Audio · Needs Review · Organize Folder · Admin). `run_dashboard.py` serves it.
- Operational runners: `scan_live.py` (inventory scan, NAS), `read_nfo_ids.py` (IDs from `.nfo`, NAS), `prune_live.py` (remove rows for deleted files, NAS), `gaps_live.py` (cache TVDB episode lists), `probe_dupes.py` (ffprobe runtimes/audio for dup-group files + all movies), `match_live.py` (API match fallback). Routine deletion-sync can also be done PC-side from the Admin tab (no SSH).
- Logic lives in small, independently-tested modules under `src/` (ingest, identify, audit, quarantine, web). External effects (ffprobe, HTTP, disk) are injected, so the suite runs fully offline.

**Deployment is split:** scanning/`.nfo`-reading run **on the NAS** (over SSH); the dashboard runs **on a Windows PC** with a `path_map` translating NAS paths to SMB and a local `ffprobe`. See RUNBOOK §2 and Plan3 §16.1.

## Setup

```bash
pip install -r requirements.txt
cp config.example.yaml config.yaml   # then edit paths, API keys, path_map, ffprobe.binary
```

## Run

```bash
python -m pytest -q                   # test suite (~234 tests)
python run_dashboard.py config.yaml   # dashboard at http://localhost:8080
python cli_engine.py config.yaml      # CLI engine (7-task menu)
```

`config.yaml` is gitignored (copy from `config.example.yaml`). `ffprobe` is optional for the scan but used on demand by the dashboard for runtime/embedded-subtitle info.
