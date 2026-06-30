# Scan & Index Implementation Plan (Plan 2 of 5)

> **For agentic workers:** REQUIRED SUB-SKILL: superpowers:executing-plans. Steps use checkbox (`- [ ]`) syntax.

**Goal:** Implement CLI task [1] (scan filesystem → fingerprint → probe streams → index into DB) and CLI task [4] (prune stale DB rows), all behind testable, ffprobe-optional logic.

**Architecture:** `scanner.py` classifies and discovers paths (pure). `probe.py` wraps ffprobe and — critically — exposes a pure `parse_probe_json` so stream-derived fields (including the tri-state English-audio rule) are unit-tested without ffprobe installed. `repository.py` owns all DB read/write helpers (write-locked). `indexer.py` orchestrates a scan with incremental skip (size+mtime). `prune.py` removes rows whose files vanished.

**Tech Stack:** Python 3.11+, stdlib `os`/`subprocess`/`json`, builds on Plan 1's `config`, `database`, `hashing`.

## Global Constraints

- Decimal storage units; `metadata_id` namespaced; DB writes via `db_write_lock`; WAL.
- `os_hash` requires ≥64KB files — scanner must skip os_hash for tiny files without crashing.
- Tri-state `has_english_audio`: `yes` if any audio track tagged eng/en; `no` if all tracks tagged non-English; `unknown` if no usable tag (`und`/missing/empty).
- `.trickplay` directories and their contents are never indexed as media; tracked as sidecars.
- Spec reference: `Plan3.md` §4.3, §5.1, §5.4, §5.5.

---

## File Structure

- `src/scanner.py` — `classify_path`, `discover`.
- `src/probe.py` — `parse_probe_json`, `probe_streams`.
- `src/repository.py` — `upsert_media_file`, `get_media_row`, `add_sidecar`, `all_media_paths`, `delete_media_by_path`.
- `src/indexer.py` — `scan_and_index`.
- `src/prune.py` — `prune_stale`.
- Tests: `tests/test_scanner.py`, `tests/test_probe.py`, `tests/test_repository.py`, `tests/test_indexer.py`, `tests/test_prune.py`.
- Modify: `src/config.py` DEFAULTS + `config.example.yaml` (common extension set).

---

### Task 1: Broaden default media extensions

**Files:** Modify `src/config.py`, `config.example.yaml`

- [ ] **Step 1:** In `src/config.py`, change the `scan.valid_extensions` default to:
`[".mkv", ".mp4", ".avi", ".m4v", ".mov", ".ts", ".wmv", ".webm"]`
- [ ] **Step 2:** Mirror the same list in `config.example.yaml`.
- [ ] **Step 3:** Run `python -m pytest tests/test_config.py -q` → PASS (existing tests don't assert the list).
- [ ] **Step 4:** Commit: `git commit -am "feat: broaden default media extension set"`

---

### Task 2: Path classifier + discovery walker

**Files:** Create `src/scanner.py`, `tests/test_scanner.py`

**Interfaces:**
- Produces:
  - `classify_path(path: str, valid_extensions: list[str]) -> str` → one of `"media"`, `"nfo"`, `"trickplay_dir"`, `"artwork"`, `"subtitle"`, `"ignore"`. Extension match is case-insensitive. Any path with a `.trickplay` component → `"trickplay_dir"`. `.nfo` → `"nfo"`; `.srt/.ass/.sub/.ssa` → `"subtitle"`; `.jpg/.jpeg/.png` → `"artwork"`.
  - `discover(media_paths: list[str], valid_extensions: list[str]) -> Iterator[tuple[str, str]]` yielding `(kind, abspath)` for every file under the roots, skipping descent into `.trickplay` directories (yields the trickplay dir once as `("trickplay_dir", dirpath)`).

- [ ] **Step 1: Write failing test `tests/test_scanner.py`**

```python
import os
from src.scanner import classify_path, discover

EXTS = [".mkv", ".mp4", ".avi"]


def test_classify_media_case_insensitive():
    assert classify_path("/m/A.MKV", EXTS) == "media"
    assert classify_path("/m/b.mp4", EXTS) == "media"


def test_classify_sidecars():
    assert classify_path("/m/a.nfo", EXTS) == "nfo"
    assert classify_path("/m/a.eng.srt", EXTS) == "subtitle"
    assert classify_path("/m/poster.jpg", EXTS) == "artwork"


def test_classify_trickplay_anywhere_in_path():
    assert classify_path("/m/Movie.trickplay/1.jpg", EXTS) == "trickplay_dir"


def test_classify_unknown_is_ignore():
    assert classify_path("/m/notes.txt", EXTS) == "ignore"


def test_discover_walks_and_skips_trickplay_descent(tmp_path):
    (tmp_path / "Movie.mkv").write_bytes(b"x")
    (tmp_path / "Movie.nfo").write_bytes(b"x")
    tp = tmp_path / "Movie.trickplay"
    tp.mkdir()
    (tp / "1.jpg").write_bytes(b"x")
    (tp / "2.jpg").write_bytes(b"x")
    found = list(discover([str(tmp_path)], EXTS))
    kinds = sorted(k for k, _ in found)
    # one media, one nfo, one trickplay_dir (not its inner jpgs)
    assert kinds == ["media", "nfo", "trickplay_dir"]
```

- [ ] **Step 2:** Run `python -m pytest tests/test_scanner.py -q` → FAIL (no module).

- [ ] **Step 3: Write `src/scanner.py`**

```python
import os

_SUBTITLE_EXTS = {".srt", ".ass", ".sub", ".ssa"}
_ARTWORK_EXTS = {".jpg", ".jpeg", ".png"}


def classify_path(path, valid_extensions):
    lower = path.lower()
    if ".trickplay" in lower.replace("\\", "/").split("/")[-2:][0] or ".trickplay" in lower:
        # any component containing .trickplay
        for part in lower.replace("\\", "/").split("/"):
            if part.endswith(".trickplay") or ".trickplay" in part:
                return "trickplay_dir"
    ext = os.path.splitext(lower)[1]
    if ext in {e.lower() for e in valid_extensions}:
        return "media"
    if ext == ".nfo":
        return "nfo"
    if ext in _SUBTITLE_EXTS:
        return "subtitle"
    if ext in _ARTWORK_EXTS:
        return "artwork"
    return "ignore"


def discover(media_paths, valid_extensions):
    for root in media_paths:
        for dirpath, dirnames, filenames in os.walk(root):
            # Yield trickplay dirs once, and prune them from descent
            trick = [d for d in dirnames if d.lower().endswith(".trickplay")]
            for d in trick:
                yield ("trickplay_dir", os.path.join(dirpath, d))
            dirnames[:] = [d for d in dirnames if not d.lower().endswith(".trickplay")]
            for name in filenames:
                full = os.path.join(dirpath, name)
                kind = classify_path(full, valid_extensions)
                if kind != "ignore":
                    yield (kind, full)
```

- [ ] **Step 4:** Run `python -m pytest tests/test_scanner.py -q` → PASS.
- [ ] **Step 5:** Commit: `git add src/scanner.py tests/test_scanner.py && git commit -m "feat: path classifier and discovery walker"`

---

### Task 3: ffprobe JSON parser + tri-state English audio

**Files:** Create `src/probe.py`, `tests/test_probe.py`

**Interfaces:**
- Produces:
  - `parse_probe_json(data: dict) -> dict` → keys: `duration_ms`, `bitrate`, `resolution_width`, `resolution_height`, `video_codec`, `color_profile`, `audio_languages` (JSON string list), `has_english_audio` (`"yes"|"no"|"unknown"`), `audio_profile`. Missing fields → `None` (or `"unknown"` for english).
  - `probe_streams(filepath, timeout, retries) -> dict | None` → runs ffprobe and returns `parse_probe_json` output; returns `None` if ffprobe missing or all retries fail (scan continues without stream data).

- [ ] **Step 1: Write failing test `tests/test_probe.py`**

```python
import json
from src.probe import parse_probe_json

SAMPLE = {
    "format": {"duration": "5400.5", "bit_rate": "8000000"},
    "streams": [
        {"codec_type": "video", "codec_name": "hevc", "width": 1920, "height": 1080,
         "color_transfer": "smpte2084"},
        {"codec_type": "audio", "codec_name": "dts", "channels": 6,
         "tags": {"language": "eng"}},
        {"codec_type": "audio", "codec_name": "aac", "channels": 2,
         "tags": {"language": "ara"}},
    ],
}


def test_parse_core_video_fields():
    out = parse_probe_json(SAMPLE)
    assert out["duration_ms"] == 5400500
    assert out["bitrate"] == 8000000
    assert out["resolution_width"] == 1920
    assert out["resolution_height"] == 1080
    assert out["video_codec"] == "hevc"
    assert out["color_profile"] == "HDR10"


def test_parse_audio_languages_and_english_yes():
    out = parse_probe_json(SAMPLE)
    assert json.loads(out["audio_languages"]) == ["eng", "ara"]
    assert out["has_english_audio"] == "yes"


def test_english_no_when_all_non_english():
    data = {"format": {}, "streams": [
        {"codec_type": "audio", "codec_name": "aac", "channels": 2, "tags": {"language": "ara"}}]}
    assert parse_probe_json(data)["has_english_audio"] == "no"


def test_english_unknown_when_untagged():
    data = {"format": {}, "streams": [
        {"codec_type": "audio", "codec_name": "aac", "channels": 2, "tags": {"language": "und"}},
        {"codec_type": "audio", "codec_name": "aac", "channels": 2}]}
    assert parse_probe_json(data)["has_english_audio"] == "unknown"


def test_audio_profile_primary_track():
    out = parse_probe_json(SAMPLE)
    assert out["audio_profile"] == "dts 6ch"
```

- [ ] **Step 2:** Run → FAIL.

- [ ] **Step 3: Write `src/probe.py`**

```python
import json
import subprocess

_ENGLISH = {"eng", "en"}
_UNKNOWN_TAGS = {"", "und", "unknown", None}

# color_transfer / color_space hints → dynamic range profile
_HDR_TRANSFERS = {"smpte2084": "HDR10", "arib-std-b67": "HLG"}


def _derive_english(langs):
    if any(l in _ENGLISH for l in langs):
        return "yes"
    usable = [l for l in langs if l not in _UNKNOWN_TAGS]
    if not usable:
        return "unknown"
    return "no"


def parse_probe_json(data):
    fmt = data.get("format", {}) or {}
    streams = data.get("streams", []) or []
    video = next((s for s in streams if s.get("codec_type") == "video"), {})
    audios = [s for s in streams if s.get("codec_type") == "audio"]

    duration = fmt.get("duration")
    duration_ms = int(float(duration) * 1000) if duration else None
    bitrate = int(fmt["bit_rate"]) if fmt.get("bit_rate") else None

    transfer = video.get("color_transfer")
    color_profile = _HDR_TRANSFERS.get(transfer, "SDR") if video else None

    langs = []
    for a in audios:
        tag = (a.get("tags") or {}).get("language")
        langs.append(tag if tag is not None else "und")

    primary = audios[0] if audios else {}
    audio_profile = None
    if primary:
        ch = primary.get("channels")
        audio_profile = f"{primary.get('codec_name', '?')} {ch}ch" if ch else primary.get("codec_name")

    return {
        "duration_ms": duration_ms,
        "bitrate": bitrate,
        "resolution_width": video.get("width") if video else None,
        "resolution_height": video.get("height") if video else None,
        "video_codec": video.get("codec_name") if video else None,
        "color_profile": color_profile,
        "audio_languages": json.dumps(langs),
        "has_english_audio": _derive_english([l.lower() for l in langs]),
        "audio_profile": audio_profile,
    }


def probe_streams(filepath, timeout, retries):
    cmd = ["ffprobe", "-v", "quiet", "-print_format", "json",
           "-show_format", "-show_streams", filepath]
    for _ in range(max(1, retries)):
        try:
            result = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
        except (subprocess.TimeoutExpired, FileNotFoundError):
            continue
        if result.returncode == 0:
            try:
                return parse_probe_json(json.loads(result.stdout))
            except json.JSONDecodeError:
                return None
    return None
```

- [ ] **Step 4:** Run `python -m pytest tests/test_probe.py -q` → PASS.
- [ ] **Step 5:** Commit.

---

### Task 4: Repository (DB read/write helpers)

**Files:** Create `src/repository.py`, `tests/test_repository.py`

**Interfaces:**
- Produces (all writes acquire `db_write_lock`):
  - `upsert_media_file(conn, record: dict) -> int` — insert or update by `filepath`; returns row id. `record` must include `filepath, filename, extension, parent_directory, file_size_bytes, fast_hash, os_hash`; optional probe/metadata fields allowed.
  - `get_media_row(conn, filepath: str) -> sqlite3.Row | None`.
  - `add_sidecar(conn, media_id: int, asset_path: str, asset_type: str) -> None` — idempotent on `asset_path`.
  - `all_media_paths(conn) -> list[str]`.
  - `delete_media_by_path(conn, filepath: str) -> None` — cascades children.

- [ ] **Step 1: Write failing test `tests/test_repository.py`**

```python
from src.database import init_db, get_connection
from src.repository import (upsert_media_file, get_media_row, add_sidecar,
                            all_media_paths, delete_media_by_path)


def _conn(tmp_path):
    db = str(tmp_path / "m.db")
    init_db(db)
    return get_connection(db)


def _rec(path, **over):
    base = dict(filepath=path, filename="a.mkv", extension=".mkv",
                parent_directory="/m", file_size_bytes=10, fast_hash="fh", os_hash="oh")
    base.update(over)
    return base


def test_insert_then_get(tmp_path):
    conn = _conn(tmp_path)
    rid = upsert_media_file(conn, _rec("/m/a.mkv", os_hash="oh1"))
    row = get_media_row(conn, "/m/a.mkv")
    assert row["id"] == rid and row["os_hash"] == "oh1"


def test_upsert_updates_existing(tmp_path):
    conn = _conn(tmp_path)
    rid1 = upsert_media_file(conn, _rec("/m/a.mkv", file_size_bytes=10))
    rid2 = upsert_media_file(conn, _rec("/m/a.mkv", file_size_bytes=999))
    assert rid1 == rid2
    assert get_media_row(conn, "/m/a.mkv")["file_size_bytes"] == 999


def test_sidecar_and_cascade(tmp_path):
    conn = _conn(tmp_path)
    rid = upsert_media_file(conn, _rec("/m/a.mkv"))
    add_sidecar(conn, rid, "/m/a.nfo", "nfo")
    add_sidecar(conn, rid, "/m/a.nfo", "nfo")  # idempotent
    assert conn.execute("SELECT COUNT(*) c FROM sidecar_assets").fetchone()["c"] == 1
    delete_media_by_path(conn, "/m/a.mkv")
    assert conn.execute("SELECT COUNT(*) c FROM sidecar_assets").fetchone()["c"] == 0


def test_all_media_paths(tmp_path):
    conn = _conn(tmp_path)
    upsert_media_file(conn, _rec("/m/a.mkv"))
    upsert_media_file(conn, _rec("/m/b.mkv"))
    assert sorted(all_media_paths(conn)) == ["/m/a.mkv", "/m/b.mkv"]
```

- [ ] **Step 2:** Run → FAIL.

- [ ] **Step 3: Write `src/repository.py`**

```python
from src.database import db_write_lock

_REQUIRED = ("filepath", "filename", "extension", "parent_directory",
             "file_size_bytes", "fast_hash", "os_hash")


def upsert_media_file(conn, record):
    for key in _REQUIRED:
        if key not in record:
            raise ValueError(f"record missing required field: {key}")
    cols = list(record.keys())
    placeholders = ",".join("?" for _ in cols)
    updates = ",".join(f"{c}=excluded.{c}" for c in cols if c != "filepath")
    sql = (f"INSERT INTO media_files ({','.join(cols)}) VALUES ({placeholders}) "
           f"ON CONFLICT(filepath) DO UPDATE SET {updates}")
    with db_write_lock:
        conn.execute(sql, [record[c] for c in cols])
        conn.commit()
    return get_media_row(conn, record["filepath"])["id"]


def get_media_row(conn, filepath):
    return conn.execute("SELECT * FROM media_files WHERE filepath = ?", (filepath,)).fetchone()


def add_sidecar(conn, media_id, asset_path, asset_type):
    with db_write_lock:
        conn.execute(
            "INSERT OR IGNORE INTO sidecar_assets (media_file_id, asset_path, asset_type) "
            "VALUES (?,?,?)", (media_id, asset_path, asset_type))
        conn.commit()


def all_media_paths(conn):
    return [r["filepath"] for r in conn.execute("SELECT filepath FROM media_files")]


def delete_media_by_path(conn, filepath):
    with db_write_lock:
        conn.execute("DELETE FROM media_files WHERE filepath = ?", (filepath,))
        conn.commit()
```

- [ ] **Step 4:** Run → PASS. **Step 5:** Commit.

---

### Task 5: Indexer orchestration (scan_and_index)

**Files:** Create `src/indexer.py`, `tests/test_indexer.py`

**Interfaces:**
- Consumes: `discover` (Task 2), `compute_fast_hash`/`compute_os_hash` (Plan 1), `probe_streams` (Task 3), repository (Task 4).
- Produces: `scan_and_index(conn, config, probe_fn=probe_streams) -> dict` with stats `{"media_indexed", "sidecars_tracked", "skipped"}`. `probe_fn` is injectable so tests pass a fake (no ffprobe needed). Incremental: a media file whose stored `file_size_bytes` equals current size is skipped (counts in `skipped`). os_hash is `""` for files < 64KB (no crash).

- [ ] **Step 1: Write failing test `tests/test_indexer.py`**

```python
import os
from src.database import init_db, get_connection
from src.indexer import scan_and_index
from src.repository import get_media_row


def _cfg(root):
    return {
        "media_paths": [root],
        "scan": {"valid_extensions": [".mkv"]},
        "hashing": {"partial_hash_threshold_bytes": 20_000_000, "partial_chunk_bytes": 10_000_000},
        "ffprobe": {"timeout_seconds": 5, "retries": 1},
    }


def _fake_probe(path, timeout, retries):
    return {"duration_ms": 1000, "bitrate": 100, "resolution_width": 1920,
            "resolution_height": 1080, "video_codec": "hevc", "color_profile": "SDR",
            "audio_languages": '["eng"]', "has_english_audio": "yes", "audio_profile": "aac 2ch"}


def test_scan_indexes_media_and_sidecars(tmp_path):
    (tmp_path / "Movie.mkv").write_bytes(b"x" * 1000)
    (tmp_path / "Movie.nfo").write_bytes(b"x")
    db = str(tmp_path / "m.db"); init_db(db); conn = get_connection(db)
    stats = scan_and_index(conn, _cfg(str(tmp_path)), probe_fn=_fake_probe)
    assert stats["media_indexed"] == 1
    assert stats["sidecars_tracked"] == 1
    row = get_media_row(conn, str(tmp_path / "Movie.mkv"))
    assert row["video_codec"] == "hevc" and row["has_english_audio"] == "yes"
    assert row["os_hash"] == ""  # under 64KB


def test_rescan_skips_unchanged(tmp_path):
    (tmp_path / "Movie.mkv").write_bytes(b"x" * 1000)
    db = str(tmp_path / "m.db"); init_db(db); conn = get_connection(db)
    scan_and_index(conn, _cfg(str(tmp_path)), probe_fn=_fake_probe)
    stats2 = scan_and_index(conn, _cfg(str(tmp_path)), probe_fn=_fake_probe)
    assert stats2["skipped"] == 1 and stats2["media_indexed"] == 0
```

- [ ] **Step 2:** Run → FAIL.

- [ ] **Step 3: Write `src/indexer.py`**

```python
import os
from src.scanner import discover
from src.hashing import compute_fast_hash, compute_os_hash
from src.probe import probe_streams
from src.repository import upsert_media_file, get_media_row, add_sidecar

_OS_MIN = 64 * 1024


def scan_and_index(conn, config, probe_fn=probe_streams):
    exts = config["scan"]["valid_extensions"]
    threshold = config["hashing"]["partial_hash_threshold_bytes"]
    chunk = config["hashing"]["partial_chunk_bytes"]
    timeout = config["ffprobe"]["timeout_seconds"]
    retries = config["ffprobe"]["retries"]

    stats = {"media_indexed": 0, "sidecars_tracked": 0, "skipped": 0}
    pending_sidecars = []  # (parent_dir, path, asset_type)

    for kind, path in discover(config["media_paths"], exts):
        if kind == "media":
            size = os.path.getsize(path)
            existing = get_media_row(conn, path)
            if existing and existing["file_size_bytes"] == size:
                stats["skipped"] += 1
                continue
            record = {
                "filepath": path,
                "filename": os.path.basename(path),
                "extension": os.path.splitext(path)[1].lower(),
                "parent_directory": os.path.dirname(path),
                "file_size_bytes": size,
                "fast_hash": compute_fast_hash(path, threshold, chunk),
                "os_hash": compute_os_hash(path) if size >= _OS_MIN else "",
            }
            probed = probe_fn(path, timeout, retries)
            if probed:
                record.update(probed)
            upsert_media_file(conn, record)
            stats["media_indexed"] += 1
        else:
            pending_sidecars.append((os.path.dirname(path), path, kind))

    # Link sidecars to media in the same directory (best-effort by directory).
    for parent_dir, path, asset_type in pending_sidecars:
        row = conn.execute(
            "SELECT id FROM media_files WHERE parent_directory = ? LIMIT 1",
            (parent_dir,)).fetchone()
        if row:
            add_sidecar(conn, row["id"], path, asset_type)
            stats["sidecars_tracked"] += 1
    return stats
```

- [ ] **Step 4:** Run → PASS. **Step 5:** Commit.

---

### Task 6: Prune stale entries (CLI task [4])

**Files:** Create `src/prune.py`, `tests/test_prune.py`

**Interfaces:**
- Produces: `prune_stale(conn) -> int` — deletes every `media_files` row whose `filepath` is absent on disk; returns count removed. Cascades children.

- [ ] **Step 1: Write failing test `tests/test_prune.py`**

```python
from src.database import init_db, get_connection
from src.repository import upsert_media_file
from src.prune import prune_stale


def _rec(path):
    return dict(filepath=path, filename="a.mkv", extension=".mkv",
                parent_directory="/m", file_size_bytes=10, fast_hash="fh", os_hash="oh")


def test_prune_removes_only_missing(tmp_path):
    real = tmp_path / "real.mkv"; real.write_bytes(b"x")
    db = str(tmp_path / "m.db"); init_db(db); conn = get_connection(db)
    upsert_media_file(conn, _rec(str(real)))
    upsert_media_file(conn, _rec(str(tmp_path / "gone.mkv")))
    removed = prune_stale(conn)
    assert removed == 1
    paths = [r["filepath"] for r in conn.execute("SELECT filepath FROM media_files")]
    assert paths == [str(real)]
```

- [ ] **Step 2:** Run → FAIL.

- [ ] **Step 3: Write `src/prune.py`**

```python
import os
from src.repository import all_media_paths, delete_media_by_path


def prune_stale(conn):
    removed = 0
    for path in all_media_paths(conn):
        if not os.path.exists(path):
            delete_media_by_path(conn, path)
            removed += 1
    return removed
```

- [ ] **Step 4:** Run full suite `python -m pytest -q` → all PASS. **Step 5:** Commit.

---

## Self-Review

- §5.1 scan/index/fingerprint/probe → Tasks 2,3,5 ✓; Jellyfin noise filter (trickplay) → Task 2 ✓.
- §5.4 tri-state English audio → Task 3 ✓.
- §5.5 prune → Task 6 ✓.
- §4.3 ffprobe timeout/retry + graceful absence → Task 3 ✓.
- No placeholders; function names consistent across tasks (`scan_and_index`, `parse_probe_json`, `upsert_media_file`, `prune_stale`).
- Deferred: incremental skip uses size only (mtime refinement) — acceptable for this plan; metadata matching is Plan 3.

This is Plan 2 of 5. Next: Plan 3 (metadata APIs + filename parsing).
