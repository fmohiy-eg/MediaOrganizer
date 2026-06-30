# Metadata Matching & Filename Parsing Plan (Plan 3 of 5)

> **For agentic workers:** REQUIRED SUB-SKILL: superpowers:executing-plans. Steps use checkbox (`- [ ]`) syntax.

**Goal:** Parse movie/TV identity from real-world paths (folder-context first), then match against TMDB/TVDB — flagging ambiguous/failed matches for manual review instead of guessing.

**Architecture:** `parsing.py` is pure (path string → structured identity), tested against the real sample names. `metadata_client.py` wraps TMDB/TVDB HTTP behind a small injectable interface so the matcher is tested without network. `matcher.py` holds the pure decision logic (matched / ambiguous / unmatched). Repository gains a `match_status` column and persistence helpers.

**Tech Stack:** Python 3.11+, `requests` (HTTP), stdlib `re`. Builds on Plans 1–2.

## Global Constraints

- Parser is path-separator agnostic (`\` and `/`); identity from folder context overrides filename (spec §7.1).
- Episode title may contain ` - `; anchor on the season/episode token (spec §7.2).
- `metadata_id` namespaced `tmdb:`/`tvdb:`. `Specials` folder → season 0.
- Match failures/ambiguity → `match_status='unmatched'`/`'ambiguous'`, never an auto-guess (user decision).
- API retries via `api.max_retries`/`retry_backoff_seconds`; on exhaustion, skip and flag.
- Spec reference: `Plan3.md` §5.2, §7; `library-naming-conventions` memory.

---

## File Structure

- `src/parsing.py` — `parse_path(filepath) -> dict`.
- `src/metadata_client.py` — `TmdbClient`, `TvdbClient` (HTTP), plus `MetadataProvider` protocol shape (duck-typed).
- `src/matcher.py` — `decide_match(candidates, parsed) -> dict`, `match_one(parsed, provider) -> dict`.
- `src/metadata_repository.py` — `cache_metadata`, `get_cached_metadata`, `set_match`, `unmatched_items`.
- Modify: `src/database.py` (add `match_status` column), `requirements.txt` (+requests).
- Tests: `tests/test_parsing.py`, `tests/test_matcher.py`, `tests/test_metadata_repository.py`, `tests/test_metadata_client.py`.

---

### Task 1: Path/identity parser

**Files:** Create `src/parsing.py`, `tests/test_parsing.py`

**Interfaces:**
- Produces `parse_path(filepath: str) -> dict` with keys:
  `item_type` (`"movie"|"episode"|"unknown"`), `series_title`, `year` (int|None), `season_number` (int|None), `episode_number` (int|None), `episode_number_end` (int|None), `episode_title` (str|None), `movie_title` (str|None), `edition` (str|None — Director's Cut/Extended/Remastered if present).

- [ ] **Step 1: Write failing tests `tests/test_parsing.py`** (uses the real sample shapes)

```python
from src.parsing import parse_path

M = r"\\host\Movies\01-Ready\Resident Evil - Damnation (2012)\Resident Evil - Damnation (2012).mp4"
TV1 = r"\\host\TV Shows\01-Ready\Dilbert (1999)\Season 01\Dilbert - S01E01 - The Name.avi"
TV2 = r"\\host\TV Shows\01-Ready\The Avengers (1961)\Season 2\The Avengers (1961) - 2x09 - The Sell-Out.mkv"
SPECIAL = (r"\\host\TV Shows\01-Ready\Disney's House of Mouse (2001)\Specials"
           r"\Disney's House of Mouse (2001) - 0x01 - Mickey's Magical Christmas - Snowed in at the House of Mouse.mp4")
DOUBLE = r"\\host\TV Shows\01-Ready\Calls (US) (2021)\Season 1\Calls (US) - S01E03 - Whatever.mp4"


def test_movie_title_and_year():
    out = parse_path(M)
    assert out["item_type"] == "movie"
    assert out["movie_title"] == "Resident Evil - Damnation"
    assert out["year"] == 2012


def test_episode_sxxexx():
    out = parse_path(TV1)
    assert out["item_type"] == "episode"
    assert out["series_title"] == "Dilbert"
    assert out["year"] == 1999
    assert (out["season_number"], out["episode_number"]) == (1, 1)
    assert out["episode_title"] == "The Name"


def test_episode_flat_multiplier_with_hyphen_title():
    out = parse_path(TV2)
    assert (out["season_number"], out["episode_number"]) == (2, 9)
    assert out["episode_title"] == "The Sell-Out"
    assert out["series_title"] == "The Avengers"


def test_specials_season_zero_and_title_with_dashes():
    out = parse_path(SPECIAL)
    assert out["season_number"] == 0
    assert out["episode_number"] == 1
    # Everything after the token is the title, dashes preserved
    assert out["episode_title"] == "Mickey's Magical Christmas - Snowed in at the House of Mouse"


def test_double_parens_title():
    out = parse_path(DOUBLE)
    assert out["series_title"] == "Calls (US)"
    assert out["year"] == 2021
    assert (out["season_number"], out["episode_number"]) == (1, 3)


def test_multi_episode_span():
    p = r"\\host\TV Shows\01-Ready\Show (2020)\Season 1\Show - S01E01-E02 - Pilot.mkv"
    out = parse_path(p)
    assert out["episode_number"] == 1 and out["episode_number_end"] == 2


def test_edition_marker_detected():
    p = r"\\host\Movies\01-Ready\Blade Runner (1982)\Blade Runner (1982) Director's Cut.mkv"
    out = parse_path(p)
    assert out["edition"] == "Director's Cut"
```

- [ ] **Step 2:** Run → FAIL.

- [ ] **Step 3: Write `src/parsing.py`**

```python
import os
import re

_SXXEXX = re.compile(r"[Ss](\d{1,2})[Ee](\d{1,3})(?:-?[Ee](\d{1,3}))?")
_FLAT = re.compile(r"(?<![\dxX])(\d{1,2})[xX](\d{1,3})(?:-(\d{1,3}))?")
_YEAR_PAREN = re.compile(r"\((\d{4})\)")
_EDITIONS = ["Director's Cut", "Extended", "Remastered", "Unrated", "Theatrical"]


def _norm(path):
    return path.replace("\\", "/")


def _strip_year_folder(folder):
    """'Calls (US) (2021)' -> ('Calls (US)', 2021); 'Dilbert (1999)' -> ('Dilbert', 1999)."""
    years = _YEAR_PAREN.findall(folder)
    year = int(years[-1]) if years else None
    title = folder
    if years:
        idx = folder.rfind(f"({years[-1]})")
        title = folder[:idx].strip()
    return title, year


def _find_edition(name):
    for ed in _EDITIONS:
        if ed.lower() in name.lower():
            return ed
    return None


def parse_path(filepath):
    parts = [p for p in _norm(filepath).split("/") if p]
    filename = parts[-1] if parts else ""
    stem = os.path.splitext(filename)[0]
    parent = parts[-2] if len(parts) >= 2 else ""
    grandparent = parts[-3] if len(parts) >= 3 else ""

    result = {
        "item_type": "unknown", "series_title": None, "year": None,
        "season_number": None, "episode_number": None, "episode_number_end": None,
        "episode_title": None, "movie_title": None, "edition": _find_edition(stem),
    }

    # Determine season folder context.
    season_from_folder = None
    if parent.lower().startswith("season"):
        m = re.search(r"(\d{1,2})", parent)
        season_from_folder = int(m.group(1)) if m else None
        series_folder = grandparent
    elif parent.lower() == "specials":
        season_from_folder = 0
        series_folder = grandparent
    else:
        series_folder = None

    # Try episode tokens in the filename.
    m = _SXXEXX.search(stem)
    flat = _FLAT.search(stem) if not m else None
    token_match = m or flat
    if token_match:
        result["item_type"] = "episode"
        if m:
            season = int(m.group(1)); ep = int(m.group(2)); ep_end = m.group(3)
        else:
            season = int(flat.group(1)); ep = int(flat.group(2)); ep_end = flat.group(3)
        result["season_number"] = season_from_folder if season_from_folder is not None else season
        result["episode_number"] = ep
        result["episode_number_end"] = int(ep_end) if ep_end else None
        # Title = everything after the matched token, trimmed of a leading separator.
        after = stem[token_match.end():]
        after = re.sub(r"^\s*-\s*", "", after).strip()
        result["episode_title"] = after or None
        src_folder = series_folder if series_folder else parent
        title, year = _strip_year_folder(src_folder)
        result["series_title"] = title or None
        result["year"] = year
        return result

    # Otherwise treat as a movie; identity from the containing folder.
    result["item_type"] = "movie"
    title, year = _strip_year_folder(parent)
    result["movie_title"] = title or None
    result["year"] = year
    return result
```

- [ ] **Step 4:** Run `python -m pytest tests/test_parsing.py -q` → PASS.
- [ ] **Step 5:** Commit.

---

### Task 2: `match_status` column + metadata repository

**Files:** Modify `src/database.py`; Create `src/metadata_repository.py`, `tests/test_metadata_repository.py`

**Interfaces:**
- Schema: add `match_status TEXT` to `media_files` (values `matched`/`unmatched`/`ambiguous`/NULL).
- Produces:
  - `cache_metadata(conn, metadata_id, title, release_date=None, theatrical_duration_minutes=None, episode_map=None) -> None`
  - `get_cached_metadata(conn, metadata_id) -> Row | None`
  - `set_match(conn, filepath, metadata_id, status) -> None` — updates `media_files.metadata_id` + `match_status`.
  - `unmatched_items(conn) -> list[Row]` — rows where `match_status` IN ('unmatched','ambiguous').

- [ ] **Step 1:** Add `match_status TEXT,` to the `media_files` CREATE in `src/database.py` (after `metadata_id`).

- [ ] **Step 2: Write failing tests `tests/test_metadata_repository.py`**

```python
from src.database import init_db, get_connection
from src.repository import upsert_media_file
from src.metadata_repository import (cache_metadata, get_cached_metadata,
                                     set_match, unmatched_items)


def _conn(tmp_path):
    db = str(tmp_path / "m.db"); init_db(db); return get_connection(db)


def _rec(path):
    return dict(filepath=path, filename="a.mkv", extension=".mkv",
                parent_directory="/m", file_size_bytes=10, fast_hash="fh", os_hash="oh")


def test_cache_and_get(tmp_path):
    conn = _conn(tmp_path)
    cache_metadata(conn, "tmdb:603", "The Matrix", release_date="1999-03-31",
                   theatrical_duration_minutes=136)
    row = get_cached_metadata(conn, "tmdb:603")
    assert row["title"] == "The Matrix" and row["theatrical_duration_minutes"] == 136


def test_set_match_and_unmatched(tmp_path):
    conn = _conn(tmp_path)
    upsert_media_file(conn, _rec("/m/a.mkv"))
    upsert_media_file(conn, _rec("/m/b.mkv"))
    set_match(conn, "/m/a.mkv", "tmdb:603", "matched")
    set_match(conn, "/m/b.mkv", None, "ambiguous")
    paths = sorted(r["filepath"] for r in unmatched_items(conn))
    assert paths == ["/m/b.mkv"]
```

- [ ] **Step 3:** Run → FAIL.

- [ ] **Step 4: Write `src/metadata_repository.py`**

```python
from src.database import db_write_lock


def cache_metadata(conn, metadata_id, title, release_date=None,
                   theatrical_duration_minutes=None, episode_map=None):
    with db_write_lock:
        conn.execute(
            "INSERT INTO metadata_cache "
            "(metadata_id, title, release_date, theatrical_duration_minutes, episode_map, expires_at) "
            "VALUES (?,?,?,?,?, datetime('now','+30 days')) "
            "ON CONFLICT(metadata_id) DO UPDATE SET title=excluded.title, "
            "release_date=excluded.release_date, "
            "theatrical_duration_minutes=excluded.theatrical_duration_minutes, "
            "episode_map=excluded.episode_map, last_updated=CURRENT_TIMESTAMP, "
            "expires_at=datetime('now','+30 days')",
            (metadata_id, title, release_date, theatrical_duration_minutes, episode_map))
        conn.commit()


def get_cached_metadata(conn, metadata_id):
    return conn.execute("SELECT * FROM metadata_cache WHERE metadata_id = ?",
                        (metadata_id,)).fetchone()


def set_match(conn, filepath, metadata_id, status):
    with db_write_lock:
        conn.execute("UPDATE media_files SET metadata_id = ?, match_status = ? WHERE filepath = ?",
                     (metadata_id, status, filepath))
        conn.commit()


def unmatched_items(conn):
    return conn.execute(
        "SELECT * FROM media_files WHERE match_status IN ('unmatched','ambiguous')").fetchall()
```

- [ ] **Step 5:** Run → PASS. **Step 6:** Commit (include database.py change).

---

### Task 3: Matcher decision logic (flag-for-review)

**Files:** Create `src/matcher.py`, `tests/test_matcher.py`

**Interfaces:**
- Produces:
  - `decide_match(candidates: list[dict], parsed: dict) -> dict` → `{"status": "matched"|"ambiguous"|"unmatched", "metadata_id": str|None}`. Rules: 0 candidates → unmatched; exactly 1 → matched; >1 but exactly one shares the parsed `year` → matched (that one); >1 with 0 or ≥2 year matches → ambiguous. Each candidate is `{"metadata_id": str, "title": str, "year": int|None}`.
  - `match_one(parsed: dict, provider) -> dict` → calls `provider.search(parsed)` (returns candidate list) and passes to `decide_match`. Returns the same decision dict. Any exception from provider → `{"status": "unmatched", "metadata_id": None}`.

- [ ] **Step 1: Write failing tests `tests/test_matcher.py`**

```python
from src.matcher import decide_match, match_one


def test_single_candidate_matched():
    out = decide_match([{"metadata_id": "tmdb:1", "title": "X", "year": 2012}], {"year": 2012})
    assert out == {"status": "matched", "metadata_id": "tmdb:1"}


def test_no_candidates_unmatched():
    assert decide_match([], {"year": 2012})["status"] == "unmatched"


def test_year_disambiguates():
    cands = [{"metadata_id": "tmdb:1", "title": "X", "year": 1999},
             {"metadata_id": "tmdb:2", "title": "X", "year": 2012}]
    out = decide_match(cands, {"year": 2012})
    assert out == {"status": "matched", "metadata_id": "tmdb:2"}


def test_ambiguous_when_year_cannot_disambiguate():
    cands = [{"metadata_id": "tmdb:1", "title": "X", "year": 2012},
             {"metadata_id": "tmdb:2", "title": "X", "year": 2012}]
    assert decide_match(cands, {"year": 2012})["status"] == "ambiguous"


class _Provider:
    def __init__(self, result): self._r = result
    def search(self, parsed): return self._r


def test_match_one_uses_provider():
    p = _Provider([{"metadata_id": "tvdb:9", "title": "Y", "year": 1999}])
    assert match_one({"year": 1999}, p)["metadata_id"] == "tvdb:9"


def test_match_one_provider_error_is_unmatched():
    class Boom:
        def search(self, parsed): raise RuntimeError("network")
    assert match_one({"year": 1999}, Boom())["status"] == "unmatched"
```

- [ ] **Step 2:** Run → FAIL.

- [ ] **Step 3: Write `src/matcher.py`**

```python
def decide_match(candidates, parsed):
    if not candidates:
        return {"status": "unmatched", "metadata_id": None}
    if len(candidates) == 1:
        return {"status": "matched", "metadata_id": candidates[0]["metadata_id"]}
    year = parsed.get("year")
    year_hits = [c for c in candidates if year is not None and c.get("year") == year]
    if len(year_hits) == 1:
        return {"status": "matched", "metadata_id": year_hits[0]["metadata_id"]}
    return {"status": "ambiguous", "metadata_id": None}


def match_one(parsed, provider):
    try:
        candidates = provider.search(parsed)
    except Exception:
        return {"status": "unmatched", "metadata_id": None}
    return decide_match(candidates or [], parsed)
```

- [ ] **Step 4:** Run → PASS. **Step 5:** Commit.

---

### Task 4: TMDB/TVDB HTTP clients

**Files:** Modify `requirements.txt` (+`requests==2.32.3`); Create `src/metadata_client.py`, `tests/test_metadata_client.py`

**Interfaces:**
- Produces:
  - `TmdbClient(api_key, http_get=requests.get)` with `.search(parsed) -> list[candidate]` for movies (uses `parsed["movie_title"]`, normalizes results to `{"metadata_id": "tmdb:<id>", "title", "year"}`).
  - `TvdbClient(api_key, http_get=requests.get)` with `.search(parsed) -> list[candidate]` for series (uses `parsed["series_title"]`, ids `tvdb:<id>`).
  - Both accept an injectable `http_get` so tests pass a fake (no network). Retries handled by the caller (Task 3 wraps errors); client raises on HTTP error.

- [ ] **Step 1:** Add `requests==2.32.3` to `requirements.txt` and `pip install requests==2.32.3`.

- [ ] **Step 2: Write failing tests `tests/test_metadata_client.py`**

```python
from src.metadata_client import TmdbClient


class _Resp:
    def __init__(self, payload): self._p = payload
    def raise_for_status(self): pass
    def json(self): return self._p


def test_tmdb_search_normalizes(monkeypatch):
    payload = {"results": [
        {"id": 603, "title": "The Matrix", "release_date": "1999-03-31"},
        {"id": 604, "title": "The Matrix Reloaded", "release_date": "2003-05-15"}]}

    def fake_get(url, params=None, headers=None, timeout=None):
        return _Resp(payload)

    client = TmdbClient("KEY", http_get=fake_get)
    cands = client.search({"movie_title": "The Matrix", "year": 1999})
    assert cands[0] == {"metadata_id": "tmdb:603", "title": "The Matrix", "year": 1999}
    assert cands[1]["year"] == 2003
```

- [ ] **Step 3:** Run → FAIL.

- [ ] **Step 4: Write `src/metadata_client.py`**

```python
import requests

_TMDB_SEARCH = "https://api.themoviedb.org/3/search/movie"
_TVDB_SEARCH = "https://api4.thetvdb.com/v4/search"


def _year_from_date(date_str):
    if date_str and len(date_str) >= 4 and date_str[:4].isdigit():
        return int(date_str[:4])
    return None


class TmdbClient:
    def __init__(self, api_key, http_get=requests.get, timeout=15):
        self.api_key = api_key
        self.http_get = http_get
        self.timeout = timeout

    def search(self, parsed):
        title = parsed.get("movie_title") or parsed.get("series_title") or ""
        resp = self.http_get(_TMDB_SEARCH,
                             params={"api_key": self.api_key, "query": title},
                             timeout=self.timeout)
        resp.raise_for_status()
        out = []
        for r in resp.json().get("results", []):
            out.append({"metadata_id": f"tmdb:{r['id']}", "title": r.get("title"),
                        "year": _year_from_date(r.get("release_date"))})
        return out


class TvdbClient:
    def __init__(self, api_key, http_get=requests.get, timeout=15):
        self.api_key = api_key
        self.http_get = http_get
        self.timeout = timeout

    def search(self, parsed):
        title = parsed.get("series_title") or ""
        resp = self.http_get(_TVDB_SEARCH,
                             params={"query": title, "type": "series"},
                             headers={"Authorization": f"Bearer {self.api_key}"},
                             timeout=self.timeout)
        resp.raise_for_status()
        out = []
        for r in resp.json().get("data", []):
            yr = r.get("year")
            out.append({"metadata_id": f"tvdb:{r.get('tvdb_id') or r.get('id')}",
                        "title": r.get("name"),
                        "year": int(yr) if yr else None})
        return out
```

- [ ] **Step 5:** Run `python -m pytest tests/test_metadata_client.py -q` → PASS.
- [ ] **Step 6:** Run full suite `python -m pytest -q` → all PASS. **Step 7:** Commit.

---

## Self-Review

- §7.1 folder-context identity, double parens → Task 1 ✓.
- §7.2 SxxExx/NxNN/0x/spans + title-with-dashes → Task 1 ✓.
- §5.2 API match + cache + namespaced ids → Tasks 2,4 ✓.
- Flag-for-manual-review (user decision) → Task 3 + `match_status` + `unmatched_items` ✓.
- Edition markers (feeds Release Protection, §5.3) → Task 1 `edition` ✓.
- No placeholders; function/column names consistent across tasks.
- Deferred: live retry/backoff loop wiring into the CLI menu and TVDB episode-map/airdate fetch (broadcast-gap audit) belong to Plan 4.

This is Plan 3 of 5. Next: Plan 4 (audit engine + subtitle rules + broadcast-gap).
