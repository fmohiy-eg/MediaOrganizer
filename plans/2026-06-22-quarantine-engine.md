# Quarantine & Cascade-Deletion Engine Plan (Plan 5a of 5)

> **For agentic workers:** REQUIRED SUB-SKILL: superpowers:executing-plans. Steps use checkbox (`- [ ]`) syntax.

**Goal:** Implement the non-destructive deletion engine (spec §6): when a media file is "deleted," move it plus its per-file sidecars into a central quarantine, preserving folder-global assets, with dry-run preview by default.

**Architecture:** Pure `src/quarantine/` package. `assets.py` decides global-vs-per-file. `cascade.py` builds a deletion *plan* (no disk writes) from the DB. `mover.py` executes a plan into quarantine (real moves only when `dry_run=False`), collision-safe by reconstructing the source path under the quarantine root.

**Tech Stack:** stdlib `os`/`shutil`. Builds on Plans 1–2 (DB, `sidecar_assets`).

## Global Constraints

- Quarantine is a single central directory (configurable); manual purge only (spec §6, user decisions).
- **Dry-run by default:** plan is always previewable; nothing moves until `dry_run=False`.
- Preserve folder-global assets (`movie.nfo`, `poster.jpg`, `tvshow.nfo`, `season.nfo`, artwork) — only per-file sidecars cascade.
- Cross-volume moves accepted (full copy) — `shutil.move` handles it.
- Spec reference: `Plan3.md` §6, §7.3.

---

## File Structure

- `src/quarantine/__init__.py`
- `src/quarantine/assets.py` — `is_global_asset(path) -> bool`.
- `src/quarantine/cascade.py` — `build_deletion_plan(conn, filepath) -> dict`.
- `src/quarantine/mover.py` — `plan_moves(plan, quarantine_path) -> list[tuple]`, `execute_plan(plan, quarantine_path, dry_run=True) -> list[tuple]`.
- Tests: `tests/quarantine/test_assets.py`, `test_cascade.py`, `test_mover.py`.

---

### Task 1: Global-vs-per-file asset classifier

**Files:** Create `src/quarantine/assets.py`, `tests/quarantine/test_assets.py`

**Interfaces:**
- `is_global_asset(path: str) -> bool` — True for folder-global files that must be PRESERVED: `movie.nfo`, `tvshow.nfo`, `season.nfo`, and artwork `poster/fanart/folder/banner/backdrop/landscape/logo/disc/clearart` (any extension), and `seasonNN-poster`, `season-specials-poster`. Case-insensitive, separator-agnostic.

- [ ] **Step 1: Write failing tests `tests/quarantine/test_assets.py`**

```python
from src.quarantine.assets import is_global_asset


def test_global_nfos_preserved():
    assert is_global_asset(r"\\h\Movies\X (2012)\movie.nfo")
    assert is_global_asset(r"\\h\TV\X (1999)\tvshow.nfo")
    assert is_global_asset(r"\\h\TV\X (1999)\Season 01\season.nfo")


def test_global_artwork_preserved():
    for name in ["poster.jpg", "fanart.jpg", "folder.jpg", "banner.jpg",
                 "backdrop.jpg", "logo.png", "disc.png", "clearart.png",
                 "season01-poster.jpg", "season-specials-poster.jpg"]:
        assert is_global_asset(r"\\h\X\\" + name), name


def test_per_file_sidecars_not_global():
    assert not is_global_asset(r"\\h\X\Dilbert - S01E01 - The Name.nfo")
    assert not is_global_asset(r"\\h\X\Dilbert - S01E01 - The Name-thumb.jpg")
    assert not is_global_asset(r"\\h\X\Movie (2012).mp4")
```

- [ ] **Step 2:** Run → FAIL.

- [ ] **Step 3: Write `src/quarantine/assets.py`**

```python
import os
import re

_GLOBAL_NFO = {"movie.nfo", "tvshow.nfo", "season.nfo"}
_GLOBAL_ART_STEMS = {"poster", "fanart", "folder", "banner", "backdrop",
                     "landscape", "logo", "disc", "clearart", "thumb"}
_SEASON_POSTER = re.compile(r"^season(\d+|-specials)-poster$")


def is_global_asset(path):
    name = os.path.basename(path.replace("\\", "/")).lower()
    if name in _GLOBAL_NFO:
        return True
    stem, _ext = os.path.splitext(name)
    if stem in _GLOBAL_ART_STEMS:
        return True
    if _SEASON_POSTER.match(stem):
        return True
    return False
```

Note: a bare `thumb.jpg` is global, but episode art is `{name}-thumb.jpg` (stem `... -thumb`, not `thumb`) so it is correctly per-file.

- [ ] **Step 4:** Run → PASS. **Step 5:** Commit.

---

### Task 2: Build deletion plan from the DB

**Files:** Create `src/quarantine/cascade.py`, `tests/quarantine/test_cascade.py`

**Interfaces:**
- `build_deletion_plan(conn, filepath: str) -> dict` → `{"video": filepath, "cascade": [paths], "preserved": [paths]}`. Looks up the media row, pulls its `sidecar_assets`, routes each asset to `cascade` (per-file) or `preserved` (global, via `is_global_asset`). `cascade` also includes the video itself's directly-bound sidecars. Raises `ValueError` if the file is not in the DB.

- [ ] **Step 1: Write failing tests `tests/quarantine/test_cascade.py`**

```python
import pytest
from src.database import init_db, get_connection
from src.repository import upsert_media_file, add_sidecar
from src.quarantine.cascade import build_deletion_plan


def _conn(tmp_path):
    db = str(tmp_path / "m.db"); init_db(db); return get_connection(db)


def _rec(path):
    return dict(filepath=path, filename="v.mkv", extension=".mkv",
                parent_directory="/d", file_size_bytes=10, fast_hash="fh", os_hash="oh")


def test_plan_splits_cascade_and_preserved(tmp_path):
    conn = _conn(tmp_path)
    rid = upsert_media_file(conn, _rec("/d/Show - S01E01 - Pilot.mkv"))
    add_sidecar(conn, rid, "/d/Show - S01E01 - Pilot.nfo", "nfo")
    add_sidecar(conn, rid, "/d/Show - S01E01 - Pilot-thumb.jpg", "artwork")
    add_sidecar(conn, rid, "/d/Show - S01E01 - Pilot.trickplay", "trickplay_dir")
    add_sidecar(conn, rid, "/d/poster.jpg", "artwork")     # global, preserve
    add_sidecar(conn, rid, "/d/tvshow.nfo", "nfo")         # global, preserve
    plan = build_deletion_plan(conn, "/d/Show - S01E01 - Pilot.mkv")
    assert plan["video"] == "/d/Show - S01E01 - Pilot.mkv"
    assert set(plan["cascade"]) == {
        "/d/Show - S01E01 - Pilot.nfo",
        "/d/Show - S01E01 - Pilot-thumb.jpg",
        "/d/Show - S01E01 - Pilot.trickplay"}
    assert set(plan["preserved"]) == {"/d/poster.jpg", "/d/tvshow.nfo"}


def test_missing_file_raises(tmp_path):
    conn = _conn(tmp_path)
    with pytest.raises(ValueError):
        build_deletion_plan(conn, "/nope.mkv")
```

- [ ] **Step 2:** Run → FAIL.

- [ ] **Step 3: Write `src/quarantine/cascade.py`**

```python
from src.repository import get_media_row
from src.quarantine.assets import is_global_asset


def build_deletion_plan(conn, filepath):
    row = get_media_row(conn, filepath)
    if row is None:
        raise ValueError(f"Not in database: {filepath}")
    assets = conn.execute(
        "SELECT asset_path FROM sidecar_assets WHERE media_file_id = ?",
        (row["id"],)).fetchall()
    cascade, preserved = [], []
    for a in assets:
        path = a["asset_path"]
        (preserved if is_global_asset(path) else cascade).append(path)
    return {"video": filepath, "cascade": cascade, "preserved": preserved}
```

- [ ] **Step 4:** Run → PASS. **Step 5:** Commit.

---

### Task 3: Execute plan into quarantine (dry-run by default)

**Files:** Create `src/quarantine/mover.py`, `tests/quarantine/test_mover.py`

**Interfaces:**
- `plan_moves(plan: dict, quarantine_path: str) -> list[tuple[str,str]]` — pure: returns `(source, destination)` pairs for the video + every cascade path. Destination = `quarantine_path` + source path with drive/leading separators stripped (preserves structure, avoids collisions). Preserved paths are never included.
- `execute_plan(plan, quarantine_path, dry_run=True) -> list[tuple]` — returns the same pairs; when `dry_run=False`, creates destination dirs and `shutil.move`s each existing source. Dry-run touches nothing.

- [ ] **Step 1: Write failing tests `tests/quarantine/test_mover.py`**

```python
import os
from src.quarantine.mover import plan_moves, execute_plan


def test_plan_moves_includes_video_and_cascade_not_preserved():
    plan = {"video": "/d/v.mkv", "cascade": ["/d/v.nfo"], "preserved": ["/d/poster.jpg"]}
    pairs = plan_moves(plan, "/q")
    sources = [s for s, _ in pairs]
    assert "/d/v.mkv" in sources and "/d/v.nfo" in sources
    assert "/d/poster.jpg" not in sources


def test_dry_run_moves_nothing(tmp_path):
    src = tmp_path / "v.mkv"; src.write_bytes(b"x")
    q = tmp_path / "q"
    plan = {"video": str(src), "cascade": [], "preserved": []}
    execute_plan(plan, str(q), dry_run=True)
    assert src.exists() and not q.exists()


def test_real_move_relocates_into_quarantine(tmp_path):
    src = tmp_path / "v.mkv"; src.write_bytes(b"x")
    q = tmp_path / "q"
    plan = {"video": str(src), "cascade": [], "preserved": []}
    pairs = execute_plan(plan, str(q), dry_run=False)
    assert not src.exists()
    assert os.path.exists(pairs[0][1])  # destination exists
```

- [ ] **Step 2:** Run → FAIL.

- [ ] **Step 3: Write `src/quarantine/mover.py`**

```python
import os
import shutil


def _dest_for(source, quarantine_path):
    _drive, rest = os.path.splitdrive(source.replace("\\", "/"))
    rest = rest.lstrip("/")
    return os.path.join(quarantine_path, rest)


def plan_moves(plan, quarantine_path):
    sources = [plan["video"]] + list(plan.get("cascade", []))
    return [(s, _dest_for(s, quarantine_path)) for s in sources]


def execute_plan(plan, quarantine_path, dry_run=True):
    pairs = plan_moves(plan, quarantine_path)
    if dry_run:
        return pairs
    for source, dest in pairs:
        if os.path.exists(source):
            os.makedirs(os.path.dirname(dest), exist_ok=True)
            shutil.move(source, dest)
    return pairs
```

- [ ] **Step 4:** Run full suite `python -m pytest -q` → all PASS. **Step 5:** Commit.

---

## Self-Review

- §6 quarantine move, per-file cascade, global preservation, dry-run default → Tasks 1–3 ✓.
- §7.3 global asset list (nfo + artwork + seasonNN-poster) → Task 1 ✓.
- Cross-volume handled by `shutil.move` → Task 3 ✓.
- Trickplay directory included in cascade (it is a `sidecar_assets` row) → Task 2 ✓.
- No placeholders; pure plan/build separated from disk-touching execute.
- Deferred: DB row removal after a confirmed real move, and "empty quarantine" purge, are wired in the dashboard/CLI layer (Plan 5b).

This is Plan 5a of 5. Next: Plan 5b (FastAPI dashboard — clean & functional).
