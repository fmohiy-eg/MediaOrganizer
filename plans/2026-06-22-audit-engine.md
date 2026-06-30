# Audit Engine Implementation Plan (Plan 4 of 5)

> **For agentic workers:** REQUIRED SUB-SKILL: superpowers:executing-plans. Steps use checkbox (`- [ ]`) syntax.

**Goal:** Implement CLI task [3] — the library integrity & gap audit: quality-variant grouping + keeper selection, two-tier exact-duplicate confirmation, release protection, cross-folder contamination, subtitle-deficit rules, and broadcast-gap analysis.

**Architecture:** A pure-logic `src/audit/` package — one focused module per audit dimension, each a small set of testable functions operating on plain dicts (DB `Row`s are dict-like). No DB or network inside the logic; the future CLI/dashboard feeds rows in and renders results out.

**Tech Stack:** Python stdlib (`re`, `datetime`). Builds on Plans 1–3 (`compute_full_hash`, parsed identity fields).

## Global Constraints

- Decimal units; durations in ms in the DB, minutes from APIs.
- Two-tier dup rule: a partial-hash group is only a confirmed duplicate set after `full_hash` agreement (spec §4.1).
- Release protection: edition marker OR duration deviation ≥ `audit.duration_deviation_seconds` → protected (spec §5.3).
- Subtitle tri-state mirrors `has_english_audio` (spec §5.4).
- Gap audit: already-aired-and-missing → missing; future air date → upcoming, never a gap (spec §5.3).
- `today` is passed in to gap functions (testability; the caller supplies `date.today().isoformat()`).
- Spec reference: `Plan3.md` §4.1, §5.3, §5.4.

---

## File Structure

- `src/audit/__init__.py`
- `src/audit/quality.py` — `quality_score`, `group_variants`, `select_keeper`.
- `src/audit/duplicates.py` — `confirm_exact_duplicates`.
- `src/audit/release_protection.py` — `is_protected`.
- `src/audit/contamination.py` — `normalize_title`, `is_contaminated`.
- `src/audit/subtitles.py` — `subtitle_flag`.
- `src/audit/gaps.py` — `analyze_gaps`.
- Tests: `tests/audit/test_quality.py`, `test_duplicates.py`, `test_release_protection.py`, `test_contamination.py`, `test_subtitles.py`, `test_gaps.py`.

---

### Task 1: Quality scoring, variant grouping, keeper selection

**Files:** Create `src/audit/__init__.py` (empty), `src/audit/quality.py`, `tests/audit/__init__.py` (empty), `tests/audit/test_quality.py`

**Interfaces:**
- `quality_score(row: dict, priority: list[str]) -> tuple` — sortable; higher = better. Honors `priority` order over keys `resolution` (width*height), `bitrate`, `codec` (av1>hevc>h264>other), `audio_channels` (parsed from `audio_profile` like `"dts 6ch"`).
- `group_variants(rows: list[dict]) -> dict[str, list[dict]]` — groups by `metadata_id`, only groups with ≥2 members.
- `select_keeper(rows: list[dict], priority: list[str]) -> dict` — the highest-scoring row.

- [ ] **Step 1: Write failing tests `tests/audit/test_quality.py`**

```python
from src.audit.quality import quality_score, group_variants, select_keeper

PRI = ["resolution", "bitrate", "codec", "audio_channels"]


def _row(mid, w, h, br, codec, prof="aac 2ch"):
    return {"metadata_id": mid, "resolution_width": w, "resolution_height": h,
            "bitrate": br, "video_codec": codec, "audio_profile": prof}


def test_higher_resolution_scores_higher():
    hd = _row("tmdb:1", 1920, 1080, 5_000_000, "h264")
    sd = _row("tmdb:1", 720, 480, 5_000_000, "h264")
    assert quality_score(hd, PRI) > quality_score(sd, PRI)


def test_codec_breaks_tie_when_resolution_and_bitrate_equal():
    av1 = _row("tmdb:1", 1920, 1080, 5_000_000, "av1")
    h264 = _row("tmdb:1", 1920, 1080, 5_000_000, "h264")
    assert quality_score(av1, PRI) > quality_score(h264, PRI)


def test_group_variants_only_multi():
    rows = [_row("tmdb:1", 1920, 1080, 5, "h264"),
            _row("tmdb:1", 720, 480, 4, "h264"),
            _row("tmdb:2", 1920, 1080, 5, "h264")]
    groups = group_variants(rows)
    assert set(groups) == {"tmdb:1"} and len(groups["tmdb:1"]) == 2


def test_select_keeper_picks_best():
    rows = [_row("tmdb:1", 720, 480, 4_000_000, "h264"),
            _row("tmdb:1", 3840, 2160, 20_000_000, "hevc")]
    assert select_keeper(rows, PRI)["resolution_height"] == 2160
```

- [ ] **Step 2:** Run `python -m pytest tests/audit/test_quality.py -q` → FAIL.

- [ ] **Step 3: Write `src/audit/quality.py`**

```python
import re

_CODEC_RANK = {"av1": 3, "hevc": 2, "h265": 2, "h264": 1}


def _channels(audio_profile):
    if not audio_profile:
        return 0
    m = re.search(r"(\d+)\s*ch", audio_profile)
    return int(m.group(1)) if m else 0


def _metric(row, key):
    if key == "resolution":
        return (row.get("resolution_width") or 0) * (row.get("resolution_height") or 0)
    if key == "bitrate":
        return row.get("bitrate") or 0
    if key == "codec":
        return _CODEC_RANK.get((row.get("video_codec") or "").lower(), 0)
    if key == "audio_channels":
        return _channels(row.get("audio_profile"))
    return 0


def quality_score(row, priority):
    return tuple(_metric(row, key) for key in priority)


def group_variants(rows):
    groups = {}
    for r in rows:
        mid = r.get("metadata_id")
        if mid:
            groups.setdefault(mid, []).append(r)
    return {mid: members for mid, members in groups.items() if len(members) > 1}


def select_keeper(rows, priority):
    return max(rows, key=lambda r: quality_score(r, priority))
```

- [ ] **Step 4:** Run → PASS. **Step 5:** Commit.

---

### Task 2: Two-tier exact-duplicate confirmation

**Files:** Create `src/audit/duplicates.py`, `tests/audit/test_duplicates.py`

**Interfaces:**
- `confirm_exact_duplicates(rows: list[dict], full_hash_fn) -> list[list[str]]` — groups candidate rows by `fast_hash`; for each candidate group of ≥2, computes `full_hash_fn(filepath)` and returns the lists of filepaths whose full hashes agree (only groups of ≥2 true duplicates). `full_hash_fn` is injected (Plan 1's `compute_full_hash`) so tests pass a fake.

- [ ] **Step 1: Write failing tests `tests/audit/test_duplicates.py`**

```python
from src.audit.duplicates import confirm_exact_duplicates


def _row(path, fast):
    return {"filepath": path, "fast_hash": fast}


def test_fast_hash_collision_not_confirmed():
    rows = [_row("/a", "FH"), _row("/b", "FH")]   # same fast hash...
    full = {"/a": "AAA", "/b": "BBB"}             # ...different full hashes
    assert confirm_exact_duplicates(rows, lambda p: full[p]) == []


def test_true_duplicates_confirmed():
    rows = [_row("/a", "FH"), _row("/b", "FH"), _row("/c", "OTHER")]
    full = {"/a": "SAME", "/b": "SAME", "/c": "X"}
    groups = confirm_exact_duplicates(rows, lambda p: full[p])
    assert groups == [["/a", "/b"]]


def test_singletons_never_hashed():
    calls = []
    rows = [_row("/only", "UNIQUE")]
    confirm_exact_duplicates(rows, lambda p: calls.append(p))
    assert calls == []  # no full hash computed for a lone candidate
```

- [ ] **Step 2:** Run → FAIL.

- [ ] **Step 3: Write `src/audit/duplicates.py`**

```python
def confirm_exact_duplicates(rows, full_hash_fn):
    by_fast = {}
    for r in rows:
        by_fast.setdefault(r["fast_hash"], []).append(r)

    confirmed = []
    for candidates in by_fast.values():
        if len(candidates) < 2:
            continue  # singleton: never read the full file
        by_full = {}
        for r in candidates:
            fh = full_hash_fn(r["filepath"])
            by_full.setdefault(fh, []).append(r["filepath"])
        for paths in by_full.values():
            if len(paths) >= 2:
                confirmed.append(sorted(paths))
    return confirmed
```

- [ ] **Step 4:** Run → PASS. **Step 5:** Commit.

---

### Task 3: Release protection

**Files:** Create `src/audit/release_protection.py`, `tests/audit/test_release_protection.py`

**Interfaces:**
- `is_protected(row: dict, theatrical_minutes: int|None, deviation_seconds: int) -> bool` — True if `row["edition"]` is set, OR `theatrical_minutes` is known and `abs(row_duration_seconds - theatrical_seconds) >= deviation_seconds`. Unknown duration/theatrical with no edition → False.

- [ ] **Step 1: Write failing tests `tests/audit/test_release_protection.py`**

```python
from src.audit.release_protection import is_protected


def _row(duration_ms=None, edition=None):
    return {"duration_ms": duration_ms, "edition": edition}


def test_edition_marker_protects():
    assert is_protected(_row(edition="Director's Cut"), 120, 120) is True


def test_duration_deviation_protects():
    # 130 min file vs 120 min theatrical = 600s deviation > 120s threshold
    assert is_protected(_row(duration_ms=130 * 60 * 1000), 120, 120) is True


def test_close_runtime_not_protected():
    # 121 min vs 120 min = 60s deviation < 120s threshold
    assert is_protected(_row(duration_ms=121 * 60 * 1000), 120, 120) is False


def test_unknown_data_not_protected():
    assert is_protected(_row(), None, 120) is False
```

- [ ] **Step 2:** Run → FAIL.

- [ ] **Step 3: Write `src/audit/release_protection.py`**

```python
def is_protected(row, theatrical_minutes, deviation_seconds):
    if row.get("edition"):
        return True
    duration_ms = row.get("duration_ms")
    if duration_ms is None or theatrical_minutes is None:
        return False
    file_seconds = duration_ms / 1000.0
    theatrical_seconds = theatrical_minutes * 60
    return abs(file_seconds - theatrical_seconds) >= deviation_seconds
```

- [ ] **Step 4:** Run → PASS. **Step 5:** Commit.

---

### Task 4: Cross-folder contamination

**Files:** Create `src/audit/contamination.py`, `tests/audit/test_contamination.py`

**Interfaces:**
- `normalize_title(s: str) -> str` — lowercase, strip non-alphanumerics, collapse spaces.
- `is_contaminated(matched_series_title: str, folder_series_title: str) -> bool` — True when both are present and normalize to different values (an episode whose matched identity disagrees with its physical folder).

- [ ] **Step 1: Write failing tests `tests/audit/test_contamination.py`**

```python
from src.audit.contamination import normalize_title, is_contaminated


def test_normalize_ignores_case_and_punctuation():
    assert normalize_title("The Tom & Jerry Show!") == normalize_title("the tom  jerry show")


def test_same_series_not_contaminated():
    assert is_contaminated("Dilbert", "Dilbert") is False


def test_different_series_contaminated():
    assert is_contaminated("The Office", "Parks and Recreation") is True


def test_missing_data_not_flagged():
    assert is_contaminated("", "Dilbert") is False
    assert is_contaminated("Dilbert", None) is False
```

- [ ] **Step 2:** Run → FAIL.

- [ ] **Step 3: Write `src/audit/contamination.py`**

```python
import re


def normalize_title(s):
    if not s:
        return ""
    s = re.sub(r"[^0-9a-zA-Z]+", " ", s.lower())
    return " ".join(s.split())


def is_contaminated(matched_series_title, folder_series_title):
    a = normalize_title(matched_series_title)
    b = normalize_title(folder_series_title)
    if not a or not b:
        return False
    return a != b
```

- [ ] **Step 4:** Run → PASS. **Step 5:** Commit.

---

### Task 5: Subtitle-deficit rule

**Files:** Create `src/audit/subtitles.py`, `tests/audit/test_subtitles.py`

**Interfaces:**
- `subtitle_flag(has_english_audio: str, has_english_subtitle: bool) -> str|None` — if an English subtitle exists → `None` (no deficit). Else: `has_english_audio == "no"` → `"critical"`; `"yes"` → `"minor"`; `"unknown"`/anything else → `"needs_review"`.

- [ ] **Step 1: Write failing tests `tests/audit/test_subtitles.py`**

```python
from src.audit.subtitles import subtitle_flag


def test_has_subtitle_no_flag():
    assert subtitle_flag("no", True) is None


def test_no_english_audio_missing_sub_is_critical():
    assert subtitle_flag("no", False) == "critical"


def test_english_audio_missing_sub_is_minor():
    assert subtitle_flag("yes", False) == "minor"


def test_unknown_audio_missing_sub_needs_review():
    assert subtitle_flag("unknown", False) == "needs_review"
```

- [ ] **Step 2:** Run → FAIL.

- [ ] **Step 3: Write `src/audit/subtitles.py`**

```python
def subtitle_flag(has_english_audio, has_english_subtitle):
    if has_english_subtitle:
        return None
    if has_english_audio == "no":
        return "critical"
    if has_english_audio == "yes":
        return "minor"
    return "needs_review"
```

- [ ] **Step 4:** Run → PASS. **Step 5:** Commit.

---

### Task 6: Broadcast-gap analysis

**Files:** Create `src/audit/gaps.py`, `tests/audit/test_gaps.py`

**Interfaces:**
- `analyze_gaps(episode_map: list[dict], present: set[tuple[int,int]], today: str) -> dict` — `episode_map` entries are `{"season": int, "episode": int, "air_date": "YYYY-MM-DD"|None}`. Returns `{"missing": [...], "upcoming": [...]}`: an episode is **missing** if its `(season, episode)` is not in `present` AND its `air_date` is non-null and `<= today`; **upcoming** if `air_date > today`. Episodes with null air dates are ignored (neither). Lists are sorted by (season, episode).

- [ ] **Step 1: Write failing tests `tests/audit/test_gaps.py`**

```python
from src.audit.gaps import analyze_gaps

EMAP = [
    {"season": 1, "episode": 1, "air_date": "2020-01-01"},
    {"season": 1, "episode": 2, "air_date": "2020-01-08"},
    {"season": 1, "episode": 3, "air_date": "2999-01-01"},  # future
    {"season": 1, "episode": 4, "air_date": None},          # unknown
]


def test_aired_and_absent_is_missing():
    out = analyze_gaps(EMAP, present={(1, 1)}, today="2026-06-22")
    assert (1, 2) in [(m["season"], m["episode"]) for m in out["missing"]]
    assert (1, 1) not in [(m["season"], m["episode"]) for m in out["missing"]]


def test_future_is_upcoming_not_missing():
    out = analyze_gaps(EMAP, present=set(), today="2026-06-22")
    ups = [(m["season"], m["episode"]) for m in out["upcoming"]]
    miss = [(m["season"], m["episode"]) for m in out["missing"]]
    assert (1, 3) in ups and (1, 3) not in miss


def test_unknown_airdate_ignored():
    out = analyze_gaps(EMAP, present=set(), today="2026-06-22")
    all_eps = [(m["season"], m["episode"]) for m in out["missing"] + out["upcoming"]]
    assert (1, 4) not in all_eps


def test_present_future_episode_not_listed():
    out = analyze_gaps(EMAP, present={(1, 3)}, today="2026-06-22")
    assert (1, 3) not in [(m["season"], m["episode"]) for m in out["upcoming"]]
```

- [ ] **Step 2:** Run → FAIL.

- [ ] **Step 3: Write `src/audit/gaps.py`**

```python
def analyze_gaps(episode_map, present, today):
    missing, upcoming = [], []
    for ep in episode_map:
        key = (ep["season"], ep["episode"])
        air = ep.get("air_date")
        if not air:
            continue
        if key in present:
            continue
        if air <= today:
            missing.append(ep)
        else:
            upcoming.append(ep)
    keyf = lambda e: (e["season"], e["episode"])
    return {"missing": sorted(missing, key=keyf), "upcoming": sorted(upcoming, key=keyf)}
```

- [ ] **Step 4:** Run full suite `python -m pytest -q` → all PASS. **Step 5:** Commit.

---

## Self-Review

- §5.3 variant grouping + keeper → Task 1 ✓; exact-dup two-tier → Task 2 ✓; release protection → Task 3 ✓; cross-folder contamination → Task 4 ✓; subtitle rules → Task 5 ✓; broadcast-gap → Task 6 ✓.
- §4.1 two-tier confirmation honored (singletons never full-hashed) → Task 2 ✓.
- §5.4 tri-state subtitle mapping → Task 5 ✓.
- ISO date strings compare lexicographically — valid for `YYYY-MM-DD`; documented in Task 6 interface.
- No placeholders; functions are pure and independently testable.
- Deferred: wiring these into a single CLI "run audit" report and persisting flags is part of the CLI assembly (with Plan 5/dashboard consumption).

This is Plan 4 of 5. Next: Plan 5 (FastAPI dashboard + quarantine/deletion engine).
