# Arabic-Audio Tab — Design

**Date:** 2026-06-24
**Status:** Approved (pending written-spec review)

## Goal

Surface every **movie** that has an Arabic audio track and let the user move its
video file into a curated `02-ArabicReady` folder, one movie at a time, with a
preview-then-confirm step. Powered by the `audio_languages` column that
`probe_dupes.py` fills in (probe currently running; the list grows as movies are
probed).

## Decisions (locked)

- **Scope:** movies only (TV excluded), matching `parse_path(...)['item_type'] == 'movie'`.
- **Detection:** tagged Arabic only — the file's `audio_languages` JSON list
  contains `"ara"` or `"ar"` (case-insensitive). Untagged (`und`) tracks are NOT
  flagged. No separate review bucket.
- **Destination:** a `02-ArabicReady` folder under the **Movies root**; move the
  **video file only** (sidecars stay behind).
- **Layout / target path — reparent by folder:**
  `…/Movies/02-ArabicReady/<existing parent-folder name>/<original filename>`.
  No metadata lookup, no rename. The existing `Title (Year)` folder name and the
  original filename are preserved.
- **Trigger:** per-movie **Move** button, **preview (src→dest) then confirm**,
  reusing the dashboard's dry-run-by-default convention. No bulk "move all".
- **Tab position:** `Overview · Dupes×2 · Cleanup · Missing Episodes · Subtitles
  · Arabic Audio · Needs Review` (Arabic Audio sits just before Needs Review).

## Architecture

Follows the existing pipeline (pure module → endpoint → inline JS), preserving
the project's dependency-injection and dry-run invariants.

### 1. Detection — `src/web/services.py`

`arabic_audio_movies(conn) -> dict`

- Reads `media_files` rows where `audio_languages IS NOT NULL` (i.e. probed).
- Keeps a row when **all** hold:
  - `parse_path(filepath)['item_type'] == 'movie'`,
  - the parsed `audio_languages` list contains `ara`/`ar` (case-insensitive),
  - the path does **not** already contain a `02-ArabicReady` segment.
- Returns:
  ```
  {
    "items": [ { filepath, title, size_bytes, audio_profile,
                 audio_languages: [...], duration_ms }, ... ],  # sorted by title
    "count": <int>,
    "total_bytes": <int>
  }
  ```
  (`size_bytes`/`total_bytes` source from the `file_size_bytes` catalog column.)
- `title` = the immediate parent-folder name of the file (the `Title (Year)` folder).

### 2. Target path — `src/web/relocate.py`

`arabic_target(movies_root, filepath, subdir="02-ArabicReady") -> str`

- Returns `<movies_root>/<subdir>/<parent-folder name>/<filename>`.
- Edge: if the file sits directly in the movies root (parent folder == the root
  itself), use the filename stem as the folder name instead, so we never produce
  `02-ArabicReady/Movies/...`.
- Pure string logic (mirrors `movie_target`); reuses `_join`.

The actual move reuses the existing `relocate_file(src_local, dest_local,
exists_fn, makedirs_fn, move_fn)` — it makes parent dirs and **refuses to
overwrite** an existing destination.

### 3. Endpoints — `web_dashboard.py`

- `GET  /api/arabic` → `services.arabic_audio_movies(conn())`.
- `POST /api/arabic/preview` `{filepath}` → `{src, dest}` (NAS-path display via
  the catalog paths; built with `pick_roots(media_paths)` movies root +
  `arabic_target`).
- `POST /api/arabic/move` `{filepath, confirm}`:
  - Builds dest with `arabic_target`; translates both ends through `path_map`
    (`to_local_path`).
  - `confirm=false` (default) → dry-run: returns `{src, dest, moved: false}`.
  - `confirm=true` → `relocate_file(...)`; returns `{moved: true, dest}`.
  - `FileExistsError`/`FileNotFoundError` → JSON error with a clear message
    (same shape as `relocate_execute`).

Constant `ARABIC_SUBDIR = "02-ArabicReady"`. Movies root resolved once via
`pick_roots(media_paths)`; if no movies root is configured the endpoints return a
clear error.

### 4. Frontend (inline, `web_dashboard.py`)

- Nav: `<button data-tab="arabic" data-panel="arabic" …>Arabic Audio</button>`
  inserted before the Needs Review button. (The `showTab` selector is already
  scoped to `section[data-panel]`, so the new button is unaffected.)
- `<section data-panel="arabic" class="hidden">` with a header (count + total GB)
  and a list. Each row: title, detected languages (`audio_profile` + langs),
  size, **▶ Play**, **Move** .
- `loadArabic()` fetches `/api/arabic` once (cached on `window`), renders rows.
- **Move** → `POST /api/arabic/move` with `confirm:false`, shows
  `src → dest` in a confirm dialog, then `confirm:true` on OK; on success removes
  the row and decrements the header counts.
- Overview gets one extra bullet: "**N** movies with an Arabic audio track. Open
  the **Arabic Audio** tab." (only shown when N > 0).

## Error handling

- Unprobed movies are simply absent (no `audio_languages`) and appear once probed.
- Overwrite at destination → refused, surfaced as an error toast; nothing moved.
- Missing source → error toast; row stays.
- Moving the video out of its folder intentionally leaves `.nfo`/subs/artwork
  behind (per decision); this is reversible by moving the file back.

## Testing (TDD)

- `tests/web/test_services.py::arabic_audio_movies` — fixtures with mixed
  `audio_languages` (`["ara","eng"]`, `["eng"]`, `["ar"]`, `null`), a TV path, and
  a file already under `02-ArabicReady`: asserts only tagged-Arabic movies that
  are probed and not-yet-moved are returned, plus correct count/total_bytes.
- `tests/web/test_relocate.py::arabic_target` — normal case, file-in-root edge,
  illegal chars left intact (we don't rename).
- `tests/web/test_app.py` — `/api/arabic` list; `/api/arabic/move` dry-run
  (no move_fn call) vs `confirm=true` (move_fn called with mapped paths);
  overwrite refused via a fake `exists_fn`.

All tests offline via injected fakes (`move_fn`, `exists_fn`, `makedirs_fn`),
consistent with existing `create_app` test wiring.

## Docs / memory follow-ups (in the implementation plan)

- CLAUDE.md: add Arabic Audio to the dashboard tab list + one invariant line.
- RUNBOOK.md: new "Arabic Audio" tab section.
- Update the `arabic-audio-feature` memory from "planned" to "built".

## Out of scope (YAGNI)

- Bulk "move all", undo/quarantine integration, TV episodes, untagged-track
  review, re-tagging audio, and any re-encode/extract of the Arabic track.
