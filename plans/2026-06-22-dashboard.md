# FastAPI Dashboard Plan (Plan 5b of 5)

> **For agentic workers:** REQUIRED SUB-SKILL: superpowers:executing-plans. Steps use checkbox (`- [ ]`) syntax.

**Goal:** A clean, functional FastAPI dashboard that reads audit data from the DB and lets the user preview/execute quarantine deletions safely.

**Architecture:** `src/web/services.py` holds pure-ish DB query functions (testable with a seeded DB). `src/web/subtitle_ingest.py` holds the collision-safe rename rule (pure). `web_dashboard.py` is the FastAPI app: JSON data endpoints, deletion preview/execute endpoints (dry-run default, using the Plan 5a engine), and a single self-contained HTML page (Tailwind CDN + small vanilla JS). Tests drive the API via `TestClient`.

**Tech Stack:** FastAPI, Tailwind (CDN), Chart.js (CDN), `httpx`/`TestClient`. Builds on all prior plans.

## Global Constraints

- Clean & functional UI (user decision): tables, badges, clear buttons; no heavy framework.
- Deletion is **dry-run by default**: a preview endpoint returns the plan; execute requires an explicit confirm flag.
- Reclaimable space and sizes use the decimal standard.
- DB path comes from config; the app opens its own connection per request (SQLite + WAL).
- Spec reference: `Plan3.md` §9 (tabs), §6 (deletion).

---

## File Structure

- `src/web/__init__.py`
- `src/web/services.py` — `library_kpis`, `variant_conflicts`, `subtitle_deficits`, `unmatched_list`.
- `src/web/subtitle_ingest.py` — `collision_safe_path`.
- `web_dashboard.py` — `create_app(db_path) -> FastAPI`; endpoints + HTML.
- Tests: `tests/web/test_services.py`, `tests/web/test_subtitle_ingest.py`, `tests/web/test_app.py`.

---

### Task 1: Subtitle collision-safe rename (pure)

**Files:** Create `src/web/subtitle_ingest.py`, `tests/web/test_subtitle_ingest.py`

**Interfaces:**
- `collision_safe_path(target: str, exists_fn) -> str` — if `exists_fn(target)` is False, return `target`. Else insert a sequential index before the final extension: `Movie.eng.srt` → `Movie.eng.1.srt`, `.2.srt`, … until `exists_fn` is False. `exists_fn(path) -> bool` is injected (real = `os.path.exists`).

- [ ] **Step 1: Write failing tests `tests/web/test_subtitle_ingest.py`**

```python
from src.web.subtitle_ingest import collision_safe_path


def test_no_collision_returns_target():
    assert collision_safe_path("/d/Movie.eng.srt", lambda p: False) == "/d/Movie.eng.srt"


def test_first_collision_gets_1():
    taken = {"/d/Movie.eng.srt"}
    assert collision_safe_path("/d/Movie.eng.srt", lambda p: p in taken) == "/d/Movie.eng.1.srt"


def test_sequential_until_free():
    taken = {"/d/Movie.eng.srt", "/d/Movie.eng.1.srt", "/d/Movie.eng.2.srt"}
    assert collision_safe_path("/d/Movie.eng.srt", lambda p: p in taken) == "/d/Movie.eng.3.srt"
```

- [ ] **Step 2:** Run → FAIL.

- [ ] **Step 3: Write `src/web/subtitle_ingest.py`**

```python
import os


def collision_safe_path(target, exists_fn):
    if not exists_fn(target):
        return target
    base, ext = os.path.splitext(target)
    i = 1
    while True:
        candidate = f"{base}.{i}{ext}"
        if not exists_fn(candidate):
            return candidate
        i += 1
```

- [ ] **Step 4:** Run → PASS. **Step 5:** Commit.

---

### Task 2: Dashboard data services

**Files:** Create `src/web/services.py`, `tests/web/test_services.py`

**Interfaces:** (each takes a live `conn`)
- `library_kpis(conn) -> dict` → `{"total_items", "total_bytes", "issue_count", "reclaimable_bytes"}`. `issue_count` = rows with `match_status` in ('unmatched','ambiguous'). `reclaimable_bytes` = 0 placeholder sum (no selection yet) — sums `file_size_bytes` where `match_status='marked_delete'`.
- `variant_conflicts(conn) -> list[dict]` → groups (metadata_id with ≥2 items) each `{"metadata_id", "items": [{"filepath","resolution_height","bitrate","video_codec","file_size_bytes"}]}`.
- `subtitle_deficits(conn) -> list[dict]` → items whose `match_status` is not the concern; returns `{"filepath","has_english_audio"}` for every media row (the flag is computed client-side via the audit rule) — for the service, return rows with `has_english_audio` present.
- `unmatched_list(conn) -> list[dict]` → `{"filepath","item_type","season_number","episode_number"}` for `match_status` in ('unmatched','ambiguous').

- [ ] **Step 1: Write failing tests `tests/web/test_services.py`**

```python
from src.database import init_db, get_connection
from src.repository import upsert_media_file
from src.metadata_repository import set_match
from src.web.services import (library_kpis, variant_conflicts,
                              subtitle_deficits, unmatched_list)


def _conn(tmp_path):
    db = str(tmp_path / "m.db"); init_db(db); return get_connection(db)


def _rec(path, mid=None, size=100, **over):
    base = dict(filepath=path, filename="v.mkv", extension=".mkv",
                parent_directory="/d", file_size_bytes=size, fast_hash="fh", os_hash="oh")
    if mid:
        base["metadata_id"] = mid
    base.update(over)
    return base


def test_kpis_counts(tmp_path):
    conn = _conn(tmp_path)
    upsert_media_file(conn, _rec("/d/a.mkv", size=1000))
    upsert_media_file(conn, _rec("/d/b.mkv", size=2000))
    set_match(conn, "/d/b.mkv", None, "unmatched")
    k = library_kpis(conn)
    assert k["total_items"] == 2
    assert k["total_bytes"] == 3000
    assert k["issue_count"] == 1


def test_variant_conflicts_groups(tmp_path):
    conn = _conn(tmp_path)
    upsert_media_file(conn, _rec("/d/a.mkv", mid="tmdb:1", resolution_height=1080))
    upsert_media_file(conn, _rec("/d/b.mkv", mid="tmdb:1", resolution_height=480))
    upsert_media_file(conn, _rec("/d/c.mkv", mid="tmdb:2", resolution_height=1080))
    groups = variant_conflicts(conn)
    assert len(groups) == 1 and groups[0]["metadata_id"] == "tmdb:1"
    assert len(groups[0]["items"]) == 2


def test_unmatched_list(tmp_path):
    conn = _conn(tmp_path)
    upsert_media_file(conn, _rec("/d/a.mkv"))
    set_match(conn, "/d/a.mkv", None, "ambiguous")
    rows = unmatched_list(conn)
    assert rows[0]["filepath"] == "/d/a.mkv"
```

- [ ] **Step 2:** Run → FAIL.

- [ ] **Step 3: Write `src/web/services.py`**

```python
def library_kpis(conn):
    row = conn.execute(
        "SELECT COUNT(*) c, COALESCE(SUM(file_size_bytes),0) b FROM media_files").fetchone()
    issues = conn.execute(
        "SELECT COUNT(*) c FROM media_files WHERE match_status IN ('unmatched','ambiguous')"
    ).fetchone()["c"]
    reclaim = conn.execute(
        "SELECT COALESCE(SUM(file_size_bytes),0) b FROM media_files "
        "WHERE match_status = 'marked_delete'").fetchone()["b"]
    return {"total_items": row["c"], "total_bytes": row["b"],
            "issue_count": issues, "reclaimable_bytes": reclaim}


def variant_conflicts(conn):
    rows = conn.execute(
        "SELECT metadata_id, filepath, resolution_height, bitrate, video_codec, file_size_bytes "
        "FROM media_files WHERE metadata_id IS NOT NULL ORDER BY metadata_id").fetchall()
    groups = {}
    for r in rows:
        groups.setdefault(r["metadata_id"], []).append(dict(r))
    return [{"metadata_id": mid, "items": items}
            for mid, items in groups.items() if len(items) > 1]


def subtitle_deficits(conn):
    rows = conn.execute(
        "SELECT filepath, has_english_audio FROM media_files "
        "WHERE has_english_audio IS NOT NULL").fetchall()
    return [dict(r) for r in rows]


def unmatched_list(conn):
    rows = conn.execute(
        "SELECT filepath, item_type, season_number, episode_number FROM media_files "
        "WHERE match_status IN ('unmatched','ambiguous')").fetchall()
    return [dict(r) for r in rows]
```

- [ ] **Step 4:** Run → PASS. **Step 5:** Commit.

---

### Task 3: FastAPI app — endpoints + HTML, deletion preview/execute

**Files:** Create `web_dashboard.py`, `tests/web/test_app.py`

**Interfaces:**
- `create_app(db_path: str, quarantine_path: str) -> FastAPI` with routes:
  - `GET /` → HTML page (200, `text/html`).
  - `GET /api/kpis` → `library_kpis`.
  - `GET /api/variants` → `variant_conflicts`.
  - `GET /api/unmatched` → `unmatched_list`.
  - `POST /api/delete/preview` body `{"filepath": str}` → the deletion plan (`build_deletion_plan` + `plan_moves`), nothing moved.
  - `POST /api/delete/execute` body `{"filepath": str, "confirm": bool}` → if `confirm` is true, `execute_plan(dry_run=False)` and remove the DB row; else 400. Returns moved pairs.

- [ ] **Step 1: Write failing tests `tests/web/test_app.py`**

```python
from fastapi.testclient import TestClient
from src.database import init_db, get_connection
from src.repository import upsert_media_file
from web_dashboard import create_app


def _setup(tmp_path):
    db = str(tmp_path / "m.db"); init_db(db)
    conn = get_connection(db)
    vid = tmp_path / "v.mkv"; vid.write_bytes(b"x")
    upsert_media_file(conn, dict(
        filepath=str(vid), filename="v.mkv", extension=".mkv",
        parent_directory=str(tmp_path), file_size_bytes=1, fast_hash="fh", os_hash="oh"))
    app = create_app(db, str(tmp_path / "q"))
    return TestClient(app), str(vid)


def test_index_serves_html(tmp_path):
    client, _ = _setup(tmp_path)
    r = client.get("/")
    assert r.status_code == 200 and "text/html" in r.headers["content-type"]


def test_kpis_endpoint(tmp_path):
    client, _ = _setup(tmp_path)
    r = client.get("/api/kpis")
    assert r.status_code == 200 and r.json()["total_items"] == 1


def test_delete_preview_moves_nothing(tmp_path):
    client, vid = _setup(tmp_path)
    r = client.post("/api/delete/preview", json={"filepath": vid})
    assert r.status_code == 200
    import os
    assert os.path.exists(vid)  # still there


def test_delete_execute_requires_confirm(tmp_path):
    client, vid = _setup(tmp_path)
    r = client.post("/api/delete/execute", json={"filepath": vid, "confirm": False})
    assert r.status_code == 400


def test_delete_execute_quarantines(tmp_path):
    client, vid = _setup(tmp_path)
    r = client.post("/api/delete/execute", json={"filepath": vid, "confirm": True})
    assert r.status_code == 200
    import os
    assert not os.path.exists(vid)  # moved to quarantine
```

- [ ] **Step 2:** Run → FAIL.

- [ ] **Step 3: Write `web_dashboard.py`** (services + engine wired; self-contained HTML with Tailwind/Chart.js CDN; small fetch-based JS rendering KPIs, variant table, unmatched list, and a per-row delete with confirm)

```python
from fastapi import FastAPI, HTTPException
from fastapi.responses import HTMLResponse, JSONResponse
from pydantic import BaseModel

from src.database import get_connection
from src.repository import delete_media_by_path
from src.web.services import library_kpis, variant_conflicts, unmatched_list, subtitle_deficits
from src.quarantine.cascade import build_deletion_plan
from src.quarantine.mover import plan_moves, execute_plan


class DeleteBody(BaseModel):
    filepath: str
    confirm: bool = False


def create_app(db_path, quarantine_path):
    app = FastAPI(title="NAS Media Organizer")

    def conn():
        return get_connection(db_path)

    @app.get("/", response_class=HTMLResponse)
    def index():
        return _INDEX_HTML

    @app.get("/api/kpis")
    def kpis():
        return library_kpis(conn())

    @app.get("/api/variants")
    def variants():
        return variant_conflicts(conn())

    @app.get("/api/unmatched")
    def unmatched():
        return unmatched_list(conn())

    @app.get("/api/subtitles")
    def subtitles():
        return subtitle_deficits(conn())

    @app.post("/api/delete/preview")
    def delete_preview(body: DeleteBody):
        c = conn()
        try:
            plan = build_deletion_plan(c, body.filepath)
        except ValueError as e:
            raise HTTPException(status_code=404, detail=str(e))
        return {"plan": plan, "moves": plan_moves(plan, quarantine_path)}

    @app.post("/api/delete/execute")
    def delete_execute(body: DeleteBody):
        if not body.confirm:
            raise HTTPException(status_code=400, detail="confirm=true required")
        c = conn()
        try:
            plan = build_deletion_plan(c, body.filepath)
        except ValueError as e:
            raise HTTPException(status_code=404, detail=str(e))
        moved = execute_plan(plan, quarantine_path, dry_run=False)
        delete_media_by_path(c, body.filepath)
        return {"moved": moved}

    return app


_INDEX_HTML = """<!doctype html>
<html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>NAS Media Organizer</title>
<script src="https://cdn.tailwindcss.com"></script>
<script src="https://cdn.jsdelivr.net/npm/chart.js"></script>
</head>
<body class="bg-slate-50 text-slate-800">
<div class="max-w-6xl mx-auto p-6">
  <h1 class="text-2xl font-semibold mb-4">NAS Media Organizer &amp; Audit Engine</h1>
  <div id="kpis" class="grid grid-cols-2 md:grid-cols-4 gap-4 mb-6"></div>
  <section class="mb-8">
    <h2 class="text-lg font-medium mb-2">Quality &amp; Variant Conflicts</h2>
    <div id="variants" class="space-y-3"></div>
  </section>
  <section>
    <h2 class="text-lg font-medium mb-2">Needs Review (unmatched)</h2>
    <ul id="unmatched" class="list-disc pl-6 text-sm"></ul>
  </section>
</div>
<script>
const fmtGB = b => (b/1e9).toFixed(2) + ' GB';
async function load() {
  const k = await (await fetch('/api/kpis')).json();
  document.getElementById('kpis').innerHTML = [
    ['Total Items', k.total_items], ['Storage Used', fmtGB(k.total_bytes)],
    ['Issues', k.issue_count], ['Reclaimable', fmtGB(k.reclaimable_bytes)]
  ].map(([l,v]) => `<div class="bg-white rounded-lg shadow p-4">
      <div class="text-xs uppercase text-slate-400">${l}</div>
      <div class="text-xl font-semibold">${v}</div></div>`).join('');

  const groups = await (await fetch('/api/variants')).json();
  document.getElementById('variants').innerHTML = groups.length ? groups.map(g => `
    <div class="bg-white rounded-lg shadow p-4">
      <div class="text-sm font-medium mb-2">${g.metadata_id}</div>
      <table class="w-full text-sm"><tbody>${g.items.map(it => `
        <tr class="border-t">
          <td class="py-1 pr-2">${it.filepath}</td>
          <td class="py-1 pr-2">${it.resolution_height||'?'}p</td>
          <td class="py-1 pr-2">${it.video_codec||''}</td>
          <td class="py-1 pr-2">${fmtGB(it.file_size_bytes||0)}</td>
          <td class="py-1"><button onclick="del('${it.filepath.replace(/'/g,"\\\\'")}')"
            class="text-red-600 hover:underline">Delete</button></td>
        </tr>`).join('')}</tbody></table>
    </div>`).join('') : '<p class="text-sm text-slate-500">No conflicts.</p>';

  const un = await (await fetch('/api/unmatched')).json();
  document.getElementById('unmatched').innerHTML = un.length
    ? un.map(u => `<li>${u.filepath}</li>`).join('')
    : '<li class="list-none text-slate-500">Everything matched.</li>';
}
async function del(fp) {
  const prev = await (await fetch('/api/delete/preview',
    {method:'POST', headers:{'Content-Type':'application/json'},
     body: JSON.stringify({filepath: fp})})).json();
  const n = prev.moves.length;
  if (!confirm(`Move ${n} file(s) to quarantine?\\n` +
      prev.moves.map(m => m[0]).join('\\n'))) return;
  await fetch('/api/delete/execute',
    {method:'POST', headers:{'Content-Type':'application/json'},
     body: JSON.stringify({filepath: fp, confirm: true})});
  load();
}
load();
</script>
</body></html>"""
```

- [ ] **Step 4:** Run `python -m pytest tests/web/test_app.py -q` → PASS.
- [ ] **Step 5:** Run full suite `python -m pytest -q` → all PASS. **Step 6:** Commit.

---

## Self-Review

- §9 tabs: KPIs + variant conflicts + needs-review rendered; subtitle endpoint provided → Task 2/3 ✓ (charts/remaining tabs are incremental front-end additions on the same endpoints).
- §6 deletion: preview (dry-run) + execute (confirm-gated) via the Plan 5a engine; DB row removed after move → Task 3 ✓.
- §9.3 collision-safe subtitle rename → Task 1 ✓.
- Dry-run-by-default honored: preview never moves; execute requires `confirm=true` → tests assert both.
- No placeholders; endpoints tested via TestClient against a real seeded DB + temp files.
- Deferred (future increments, same architecture): OpenSubtitles live auto-fetch, upload ingestion wiring, Chart.js visualizations, relocation tool, broadcast-gap tab. Each hangs off an added service function + endpoint.

This is Plan 5b of 5 — final plan. After merge, the build is feature-complete for the core workflow.
