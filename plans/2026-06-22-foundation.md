# Foundation Implementation Plan (Plan 1 of 5)

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build the shared foundation — config loading/validation, the SQLite schema + thread-safe database layer, and the fingerprinting/hashing module — that every later subsystem depends on.

**Architecture:** Three focused, independently-testable modules under a `src/` package. `config.py` loads `config.yaml` over a defaults dict. `database.py` owns schema creation and a write-serialized SQLite connection (WAL mode). `hashing.py` implements the two-tier exact-duplicate hashes and the OpenSubtitles hash. No CLI, no web, no external APIs in this plan.

**Tech Stack:** Python 3.11+, `PyYAML`, `pytest`, stdlib `sqlite3`/`hashlib`/`struct`.

## Global Constraints

- Storage math uses the **Classic Decimal Standard** (1 KB = 1,000 bytes) everywhere.
- `metadata_id` values are **namespaced**: `tmdb:<id>` or `tvdb:<id>`.
- All DB **writes** are serialized through a single shared lock; connection uses WAL mode.
- `os_hash` MUST include the filesize term (filesize + 64-bit sum of first/last 64KB, mod 2^64).
- `fast_hash` is a **candidate** signature only; exact-duplicate truth requires `full_hash`.
- All policy thresholds come from config with built-in defaults; nothing hardcoded in logic.
- Spec reference: `Plan3.md` (sections 2, 3, 4).

---

## File Structure

- `requirements.txt` — pinned deps (`PyYAML`, `pytest`).
- `config.example.yaml` — documented example config (mirrors `Plan3.md` §2).
- `src/__init__.py` — package marker.
- `src/config.py` — `load_config(path) -> dict`, defaults merge + validation.
- `src/database.py` — `init_db(db_path)`, `get_connection(db_path)`, `db_write_lock`.
- `src/hashing.py` — `compute_fast_hash`, `compute_full_hash`, `compute_os_hash`.
- `tests/__init__.py`
- `tests/test_config.py`, `tests/test_database.py`, `tests/test_hashing.py`
- `tests/conftest.py` — shared fixtures (tmp dirs, dummy binary files).

---

### Task 1: Project scaffold + config loader

**Files:**
- Create: `requirements.txt`, `config.example.yaml`, `src/__init__.py`, `src/config.py`, `tests/__init__.py`, `tests/conftest.py`, `tests/test_config.py`

**Interfaces:**
- Produces: `load_config(path: str) -> dict` returning the fully-merged config (user values over `DEFAULTS`). Raises `ConfigError(str)` on missing file, invalid YAML, or a missing required field (`media_paths` non-empty). Also exports `DEFAULTS: dict` and `ConfigError(Exception)`.

- [ ] **Step 1: Create `requirements.txt`**

```text
PyYAML==6.0.2
pytest==8.3.3
```

- [ ] **Step 2: Create `src/__init__.py` and `tests/__init__.py`** (both empty files)

- [ ] **Step 3: Create `tests/conftest.py`**

```python
import struct
import pytest


@pytest.fixture
def write_binary(tmp_path):
    """Return a factory that writes `size` bytes (repeating pattern) to a file and returns its path."""
    def _make(name, size, fill=b"\x01"):
        p = tmp_path / name
        p.write_bytes((fill * size)[:size])
        return str(p)
    return _make


@pytest.fixture
def write_os_hash_file(tmp_path):
    """Write a file whose 8-byte little-endian longs are all `value`, for deterministic os_hash tests."""
    def _make(name, total_bytes, value=1):
        p = tmp_path / name
        longs = total_bytes // 8
        p.write_bytes(struct.pack("<%dq" % longs, *([value] * longs)))
        return str(p)
    return _make
```

- [ ] **Step 4: Write the failing test — `tests/test_config.py`**

```python
import pytest
from src.config import load_config, ConfigError, DEFAULTS


def _write(tmp_path, text):
    p = tmp_path / "config.yaml"
    p.write_text(text)
    return str(p)


def test_user_values_override_defaults(tmp_path):
    cfg_path = _write(tmp_path, "media_paths:\n  - /media/Movies\nscan:\n  worker_threads: 8\n")
    cfg = load_config(cfg_path)
    assert cfg["scan"]["worker_threads"] == 8           # overridden
    assert cfg["hashing"]["partial_chunk_bytes"] == DEFAULTS["hashing"]["partial_chunk_bytes"]  # default kept
    assert cfg["media_paths"] == ["/media/Movies"]


def test_missing_file_raises(tmp_path):
    with pytest.raises(ConfigError):
        load_config(str(tmp_path / "nope.yaml"))


def test_empty_media_paths_raises(tmp_path):
    cfg_path = _write(tmp_path, "media_paths: []\n")
    with pytest.raises(ConfigError):
        load_config(cfg_path)
```

- [ ] **Step 5: Run test to verify it fails**

Run: `python -m pytest tests/test_config.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'src.config'`

- [ ] **Step 6: Write `src/config.py`**

```python
import copy
import os
import yaml

DEFAULTS = {
    "media_paths": [],
    "database_path": "/config/media_audit.db",
    "log_directory": "/logs",
    "quarantine_path": "/config/.quarantine",
    "api_keys": {
        "tmdb": "",
        "tvdb": "",
        "opensubtitles": {"api_key": "", "username": "", "password": ""},
    },
    "hashing": {
        "partial_hash_threshold_bytes": 20_000_000,
        "partial_chunk_bytes": 10_000_000,
    },
    "audit": {
        "duration_deviation_seconds": 120,
        "variant_priority": ["resolution", "bitrate", "codec", "audio_channels"],
    },
    "ffprobe": {"timeout_seconds": 30, "retries": 3},
    "api": {"max_retries": 2, "retry_backoff_seconds": 5, "cache_ttl_days": 30},
    "scan": {"worker_threads": 4, "valid_extensions": [".mkv", ".mp4", ".avi"]},
    "safety": {"dry_run_default": True},
}


class ConfigError(Exception):
    pass


def _deep_merge(base, override):
    result = copy.deepcopy(base)
    for key, value in (override or {}).items():
        if isinstance(value, dict) and isinstance(result.get(key), dict):
            result[key] = _deep_merge(result[key], value)
        else:
            result[key] = value
    return result


def load_config(path):
    if not os.path.isfile(path):
        raise ConfigError(f"Config file not found: {path}")
    try:
        with open(path, "r", encoding="utf-8") as f:
            user = yaml.safe_load(f) or {}
    except yaml.YAMLError as e:
        raise ConfigError(f"Invalid YAML in {path}: {e}")
    if not isinstance(user, dict):
        raise ConfigError("Config root must be a mapping")
    merged = _deep_merge(DEFAULTS, user)
    if not merged["media_paths"]:
        raise ConfigError("config.media_paths must contain at least one path")
    return merged
```

- [ ] **Step 7: Create `config.example.yaml`** (copy the full block from `Plan3.md` §2 verbatim so users have a documented starting point)

- [ ] **Step 8: Run test to verify it passes**

Run: `python -m pytest tests/test_config.py -v`
Expected: PASS (3 passed)

- [ ] **Step 9: Commit**

```bash
git add requirements.txt config.example.yaml src/ tests/
git commit -m "feat: project scaffold and config loader with defaults + validation"
```

---

### Task 2: SQLite schema + thread-safe database layer

**Files:**
- Create: `src/database.py`, `tests/test_database.py`

**Interfaces:**
- Consumes: nothing from Task 1.
- Produces:
  - `init_db(db_path: str) -> None` — creates all four tables (idempotent, `IF NOT EXISTS`) and enables WAL + foreign keys.
  - `get_connection(db_path: str) -> sqlite3.Connection` — returns a connection with `row_factory = sqlite3.Row`, `PRAGMA foreign_keys = ON`, `PRAGMA journal_mode = WAL`.
  - `db_write_lock` — a module-level `threading.Lock` callers hold around writes.

- [ ] **Step 1: Write the failing test — `tests/test_database.py`**

```python
import sqlite3
import threading
from src.database import init_db, get_connection, db_write_lock


def test_init_creates_all_tables(tmp_path):
    db = str(tmp_path / "media_audit.db")
    init_db(db)
    conn = get_connection(db)
    names = {r["name"] for r in conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table'")}
    assert {"media_files", "external_subtitles", "sidecar_assets", "metadata_cache"} <= names


def test_init_is_idempotent(tmp_path):
    db = str(tmp_path / "media_audit.db")
    init_db(db)
    init_db(db)  # second call must not raise


def test_foreign_key_cascade_deletes_children(tmp_path):
    db = str(tmp_path / "media_audit.db")
    init_db(db)
    conn = get_connection(db)
    with db_write_lock:
        conn.execute(
            "INSERT INTO media_files (filepath, filename, extension, parent_directory, "
            "file_size_bytes, fast_hash, os_hash) VALUES (?,?,?,?,?,?,?)",
            ("/m/a.mkv", "a.mkv", ".mkv", "/m", 100, "fh", "oh"))
        mid = conn.execute("SELECT id FROM media_files").fetchone()["id"]
        conn.execute(
            "INSERT INTO sidecar_assets (media_file_id, asset_path, asset_type) VALUES (?,?,?)",
            (mid, "/m/a.nfo", "nfo"))
        conn.commit()
    with db_write_lock:
        conn.execute("DELETE FROM media_files WHERE id = ?", (mid,))
        conn.commit()
    assert conn.execute("SELECT COUNT(*) c FROM sidecar_assets").fetchone()["c"] == 0


def test_write_lock_is_a_lock():
    assert isinstance(db_write_lock, type(threading.Lock()))
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_database.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'src.database'`

- [ ] **Step 3: Write `src/database.py`**

```python
import os
import sqlite3
import threading

db_write_lock = threading.Lock()

SCHEMA = """
CREATE TABLE IF NOT EXISTS media_files (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    filepath TEXT UNIQUE NOT NULL,
    filename TEXT NOT NULL,
    extension TEXT NOT NULL,
    parent_directory TEXT NOT NULL,
    file_size_bytes INTEGER NOT NULL,
    fast_hash TEXT NOT NULL,
    full_hash TEXT,
    os_hash TEXT NOT NULL,
    duration_ms INTEGER,
    bitrate INTEGER,
    resolution_width INTEGER,
    resolution_height INTEGER,
    video_codec TEXT,
    color_profile TEXT,
    audio_languages TEXT,
    has_english_audio TEXT,
    audio_profile TEXT,
    metadata_id TEXT,
    item_type TEXT CHECK(item_type IN ('movie', 'episode')),
    season_number INTEGER,
    episode_number INTEGER,
    episode_number_end INTEGER,
    last_scanned TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
CREATE TABLE IF NOT EXISTS external_subtitles (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    media_file_id INTEGER NOT NULL,
    filepath TEXT UNIQUE NOT NULL,
    language_tag TEXT,
    is_sdh INTEGER DEFAULT 0,
    is_forced INTEGER DEFAULT 0,
    FOREIGN KEY(media_file_id) REFERENCES media_files(id) ON DELETE CASCADE
);
CREATE TABLE IF NOT EXISTS sidecar_assets (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    media_file_id INTEGER NOT NULL,
    asset_path TEXT UNIQUE NOT NULL,
    asset_type TEXT CHECK(asset_type IN ('nfo', 'trickplay_dir', 'artwork', 'scene_junk')),
    FOREIGN KEY(media_file_id) REFERENCES media_files(id) ON DELETE CASCADE
);
CREATE TABLE IF NOT EXISTS metadata_cache (
    metadata_id TEXT PRIMARY KEY,
    title TEXT NOT NULL,
    release_date TEXT,
    theatrical_duration_minutes INTEGER,
    episode_map TEXT,
    last_updated TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    expires_at TIMESTAMP
);
"""


def get_connection(db_path):
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    conn.execute("PRAGMA journal_mode = WAL")
    return conn


def init_db(db_path):
    parent = os.path.dirname(db_path)
    if parent:
        os.makedirs(parent, exist_ok=True)
    conn = get_connection(db_path)
    try:
        with db_write_lock:
            conn.executescript(SCHEMA)
            conn.commit()
    finally:
        conn.close()
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/test_database.py -v`
Expected: PASS (4 passed)

- [ ] **Step 5: Commit**

```bash
git add src/database.py tests/test_database.py
git commit -m "feat: SQLite schema and thread-safe database layer"
```

---

### Task 3: Hashing module (fast_hash, full_hash, os_hash)

**Files:**
- Create: `src/hashing.py`, `tests/test_hashing.py`

**Interfaces:**
- Consumes: config values `hashing.partial_hash_threshold_bytes`, `hashing.partial_chunk_bytes` (passed in by caller; functions take explicit args, not the config dict).
- Produces:
  - `compute_fast_hash(filepath: str, threshold: int, chunk_size: int) -> str` — SHA256 hex. Whole-file for files ≤ threshold; head+tail concat for larger.
  - `compute_full_hash(filepath: str) -> str` — streaming full-file SHA256 hex.
  - `compute_os_hash(filepath: str) -> str` — 16-char hex OpenSubtitles hash (filesize + first/last 64KB longs, mod 2^64). Raises `ValueError` if file < 64KB.

- [ ] **Step 1: Write the failing test — `tests/test_hashing.py`**

```python
import hashlib
import os
import struct
import pytest
from src.hashing import compute_fast_hash, compute_full_hash, compute_os_hash


def test_small_file_fast_hash_equals_full_sha256(write_binary):
    path = write_binary("small.bin", 1000)
    expected = hashlib.sha256(b"\x01" * 1000).hexdigest()
    assert compute_fast_hash(path, threshold=20_000_000, chunk_size=10) == expected


def test_large_file_fast_hash_uses_head_and_tail(write_binary):
    # threshold tiny so the file counts as "large"; chunk_size=4
    path = write_binary("big.bin", 100, fill=b"\x01")
    with open(path, "rb") as f:
        head = f.read(4)
        f.seek(-4, os.SEEK_END)
        tail = f.read(4)
    expected = hashlib.sha256(head + tail).hexdigest()
    assert compute_fast_hash(path, threshold=10, chunk_size=4) == expected


def test_full_hash_matches_hashlib(write_binary):
    path = write_binary("f.bin", 5000)
    assert compute_full_hash(path) == hashlib.sha256(b"\x01" * 5000).hexdigest()


def test_os_hash_known_value(write_os_hash_file):
    # 128KB of 8-byte longs all = 1. Each 64KB region has 8192 longs.
    # h = filesize + sum(head longs) + sum(tail longs)
    size = 128 * 1024
    path = write_os_hash_file("os.bin", size, value=1)
    longs_per_chunk = (64 * 1024) // 8
    expected_int = (size + longs_per_chunk + longs_per_chunk) & 0xFFFFFFFFFFFFFFFF
    assert compute_os_hash(path) == f"{expected_int:016x}"


def test_os_hash_rejects_tiny_file(write_binary):
    path = write_binary("tiny.bin", 100)
    with pytest.raises(ValueError):
        compute_os_hash(path)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_hashing.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'src.hashing'`

- [ ] **Step 3: Write `src/hashing.py`**

```python
import hashlib
import os
import struct

_OS_CHUNK = 64 * 1024
_MASK = 0xFFFFFFFFFFFFFFFF


def compute_fast_hash(filepath, threshold, chunk_size):
    size = os.path.getsize(filepath)
    if size <= threshold:
        with open(filepath, "rb") as f:
            return hashlib.sha256(f.read()).hexdigest()
    with open(filepath, "rb") as f:
        head = f.read(chunk_size)
        f.seek(-chunk_size, os.SEEK_END)
        tail = f.read(chunk_size)
    return hashlib.sha256(head + tail).hexdigest()


def compute_full_hash(filepath):
    h = hashlib.sha256()
    with open(filepath, "rb") as f:
        for block in iter(lambda: f.read(1024 * 1024), b""):
            h.update(block)
    return h.hexdigest()


def compute_os_hash(filepath):
    size = os.path.getsize(filepath)
    if size < _OS_CHUNK:
        raise ValueError(f"File too small for os_hash (<64KB): {filepath}")
    h = size
    fmt = "<%dq" % (_OS_CHUNK // 8)
    with open(filepath, "rb") as f:
        for val in struct.unpack(fmt, f.read(_OS_CHUNK)):
            h = (h + val) & _MASK
        f.seek(size - _OS_CHUNK, os.SEEK_SET)
        for val in struct.unpack(fmt, f.read(_OS_CHUNK)):
            h = (h + val) & _MASK
    return f"{h:016x}"
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/test_hashing.py -v`
Expected: PASS (5 passed)

- [ ] **Step 5: Run the full suite**

Run: `python -m pytest -v`
Expected: PASS (all tests from Tasks 1–3)

- [ ] **Step 6: Commit**

```bash
git add src/hashing.py tests/test_hashing.py
git commit -m "feat: hashing module (fast_hash, full_hash, os_hash)"
```

---

## Self-Review

**Spec coverage (Plan3.md §2–4):**
- §2 config + defaults + validation → Task 1 ✓
- §3 four-table schema, namespaced ids, `full_hash`/`has_english_audio`/`episode_number_end`/`expires_at`, cascade, thread lock, WAL → Task 2 ✓
- §4.1 two-tier hashing → Task 3 (`compute_fast_hash` + `compute_full_hash`) ✓
- §4.2 corrected `os_hash` with filesize term → Task 3 ✓
- §4.3 ffprobe → deferred to Plan 2 (scan), not foundation. Noted, not a gap.

**Placeholder scan:** none — every step has complete code/commands.

**Type consistency:** `db_write_lock`, `init_db`, `get_connection` names match between Task 2 interface and `database.py`; hashing function names/signatures match between Task 3 interface, tests, and implementation.

---

## Execution Handoff

This is Plan 1 of 5. After it passes, proceed to Plan 2 (scan & index).
