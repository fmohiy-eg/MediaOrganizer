# Arabic-Audio Tab Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add an "Arabic Audio" dashboard tab that lists movies with a tagged Arabic audio track and moves each movie's video file (reparented under `Movies/02-ArabicReady/`) with a preview-then-confirm step.

**Architecture:** Two new pure functions (`relocate.arabic_target` for the destination path, `services.arabic_audio_movies` for detection), three FastAPI endpoints reusing the existing `relocate_file` mover, and an inline tab (nav button + section + JS) in `web_dashboard.py`. Mirrors the existing relocate/delete flows exactly.

**Tech Stack:** Python 3.12+, FastAPI, SQLite (WAL), pytest. ffprobe data already lands in the `audio_languages` column via `probe_dupes.py`.

## Global Constraints

- **Movies only:** detect via `parse_path(filepath)['item_type'] == 'movie'` (same rule `probe_dupes.py` used to choose what to probe).
- **Tagged Arabic only:** a movie qualifies iff its `audio_languages` JSON list contains `"ara"` or `"ar"` (case-insensitive). Untagged (`und`) is never flagged.
- **Move the video file only**, reparented to `<movies_root>/02-ArabicReady/<existing parent-folder name>/<original filename>`. Sidecars stay behind.
- **Dry-run by default:** the move endpoint moves only when `confirm=true`; reuse `relocate_file` (makes dirs, **refuses to overwrite**).
- **DI for testability:** never call the filesystem directly in endpoints — use the injected `move_fn`/`exists_fn`/`makedirs_fn` already on `create_app`.
- **Constant:** `ARABIC_SUBDIR = "02-ArabicReady"`.
- **Catalog paths use forward slashes** (`/share/Movies/...`); `path_map` + `to_local_path` translate to SMB for any filesystem op.
- Run the full suite with `python -m pytest -q` (must stay green; ~153 tests today).

---

### Task 1: `arabic_target` destination-path builder

**Files:**
- Modify: `src/web/relocate.py` (add function near `movie_target`)
- Test: `tests/web/test_relocate.py`

**Interfaces:**
- Produces: `arabic_target(movies_root: str, filepath: str, subdir: str = "02-ArabicReady") -> str` — returns `<movies_root>/<subdir>/<folder>/<filename>` where `<folder>` is the file's immediate parent-folder name, or the filename stem if the file sits directly in `movies_root`.

- [ ] **Step 1: Write the failing tests**

Add to `tests/web/test_relocate.py`:

```python
from src.web.relocate import arabic_target


def test_arabic_target_reparents_under_subdir():
    src = "/share/Movies/01-Ready/Heat (1995)/Heat (1995).mkv"
    assert arabic_target("/share/Movies/01-Ready", src) == \
        "/share/Movies/01-Ready/02-ArabicReady/Heat (1995)/Heat (1995).mkv"


def test_arabic_target_file_directly_in_root_uses_filename_stem():
    src = "/share/Movies/01-Ready/loose.mkv"
    assert arabic_target("/share/Movies/01-Ready", src) == \
        "/share/Movies/01-Ready/02-ArabicReady/loose/loose.mkv"
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/web/test_relocate.py -q`
Expected: FAIL with `ImportError: cannot import name 'arabic_target'`.

- [ ] **Step 3: Implement**

Add to `src/web/relocate.py` (uses the existing `_join`; `posixpath` handles the forward-slash catalog paths consistently on Windows):

```python
import posixpath


def arabic_target(movies_root, filepath, subdir="02-ArabicReady"):
    """Reparent a movie's video file under <movies_root>/<subdir>/, keeping its
    parent-folder name and original filename. If the file sits directly in the
    movies root, use the filename stem as the folder so we never nest under the
    root's own name."""
    norm = filepath.replace("\\", "/")
    fname = posixpath.basename(norm)
    parent = posixpath.basename(posixpath.dirname(norm))
    root_name = posixpath.basename(movies_root.replace("\\", "/").rstrip("/"))
    folder = parent if parent and parent != root_name else posixpath.splitext(fname)[0]
    return _join(movies_root, subdir, folder, fname)
```

Put the `import posixpath` at the top of the file with the other imports.

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest tests/web/test_relocate.py -q`
Expected: PASS (all relocate tests).

- [ ] **Step 5: Commit**

```bash
git add src/web/relocate.py tests/web/test_relocate.py
git commit -m "feat: add arabic_target reparent path builder"
```

---

### Task 2: `arabic_audio_movies` detection service

**Files:**
- Modify: `src/web/services.py` (add function + `_ARABIC_SUBDIR` constant)
- Test: `tests/web/test_services.py`

**Interfaces:**
- Consumes: `parse_path` (already imported in services), the catalog `media_files` columns `filepath, file_size_bytes, audio_languages, audio_profile, duration_ms`.
- Produces: `arabic_audio_movies(conn) -> {"items": [ {filepath, title, size_bytes, audio_profile, audio_languages: list, duration_ms} ], "count": int, "total_bytes": int}` sorted by `title` (case-insensitive).

- [ ] **Step 1: Write the failing tests**

Add to `tests/web/test_services.py` (the `_rec` helper passes extra columns straight through `upsert_media_file`, so `item_type`/`audio_languages` can be set inline):

```python
def test_arabic_audio_movies_filters_and_summarizes(tmp_path):
    from src.web.services import arabic_audio_movies
    conn = _conn(tmp_path)
    # qualifies: movie with an Arabic-tagged track
    upsert_media_file(conn, _rec("/share/Movies/Heat (1995)/Heat (1995).mkv",
                                 item_type="movie", file_size_bytes=1000,
                                 audio_languages='["eng", "ara"]'))
    # qualifies: short tag "ar"
    upsert_media_file(conn, _rec("/share/Movies/Salah (2020)/Salah (2020).mkv",
                                 item_type="movie", file_size_bytes=500,
                                 audio_languages='["ar"]'))
    # excluded: no Arabic track
    upsert_media_file(conn, _rec("/share/Movies/Eng (2001)/Eng (2001).mkv",
                                 item_type="movie", audio_languages='["eng"]'))
    # excluded: not yet probed (audio_languages NULL)
    upsert_media_file(conn, _rec("/share/Movies/Unprobed (2002)/Unprobed (2002).mkv",
                                 item_type="movie"))
    # excluded: TV episode even though Arabic-tagged
    upsert_media_file(conn, _rec("/share/TV Shows/Show/Season 01/Show - S01E01.mkv",
                                 item_type="episode", audio_languages='["ara"]'))
    # excluded: already moved into 02-ArabicReady
    upsert_media_file(conn, _rec("/share/Movies/02-ArabicReady/Done (1999)/Done (1999).mkv",
                                 item_type="movie", audio_languages='["ara"]'))
    out = arabic_audio_movies(conn)
    assert out["count"] == 2
    assert out["total_bytes"] == 1500
    titles = [it["title"] for it in out["items"]]
    assert titles == ["Heat (1995)", "Salah (2020)"]   # sorted by title
    assert out["items"][0]["audio_languages"] == ["eng", "ara"]
```

> Note: detection uses `parse_path(filepath)['item_type']`, NOT the DB `item_type` column — the `item_type` kwarg above is only there to keep the rows realistic. The paths are shaped so `parse_path` classifies them correctly (movies under `/share/Movies/Title (Year)/`, the episode under a `Season NN` folder with an `SxxExx` token).

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/web/test_services.py::test_arabic_audio_movies_filters_and_summarizes -q`
Expected: FAIL with `ImportError: cannot import name 'arabic_audio_movies'`.

- [ ] **Step 3: Implement**

Add to `src/web/services.py` (`json`, `os`, `parse_path` are already imported at the top):

```python
_ARABIC_SUBDIR = "02-ArabicReady"


def arabic_audio_movies(conn):
    """Movies whose audio_languages contains a tagged Arabic track (ara/ar),
    excluding TV, not-yet-probed files, and anything already under 02-ArabicReady."""
    rows = conn.execute(
        "SELECT filepath, file_size_bytes, audio_languages, audio_profile, duration_ms "
        "FROM media_files WHERE audio_languages IS NOT NULL").fetchall()
    items = []
    for r in rows:
        fp = r["filepath"]
        segments = fp.replace("\\", "/").split("/")
        if _ARABIC_SUBDIR in segments:
            continue
        if parse_path(fp)["item_type"] != "movie":
            continue
        langs = json.loads(r["audio_languages"] or "[]")
        if not any(str(l).lower() in ("ara", "ar") for l in langs):
            continue
        items.append({
            "filepath": fp,
            "title": os.path.basename(os.path.dirname(fp.replace("\\", "/"))),
            "size_bytes": r["file_size_bytes"],
            "audio_profile": r["audio_profile"],
            "audio_languages": langs,
            "duration_ms": r["duration_ms"],
        })
    items.sort(key=lambda it: it["title"].lower())
    return {"items": items, "count": len(items),
            "total_bytes": sum(it["size_bytes"] for it in items)}
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest tests/web/test_services.py -q`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add src/web/services.py tests/web/test_services.py
git commit -m "feat: add arabic_audio_movies detection service"
```

---

### Task 3: Backend endpoints (`/api/arabic`, preview, move) + summary count

**Files:**
- Modify: `web_dashboard.py` (import, `ArabicBody` model, 3 endpoints, summary field)
- Test: `tests/web/test_app.py`

**Interfaces:**
- Consumes: `arabic_audio_movies` (Task 2), `arabic_target` (Task 1), existing `pick_roots`, `relocate_file`, `to_local_path`, `update_media_path`, `get_media_row`.
- Produces:
  - `GET /api/arabic` → the Task 2 dict.
  - `POST /api/arabic/preview {filepath}` → `{src, dest, dest_exists}`.
  - `POST /api/arabic/move {filepath, confirm}` → `{src, dest, moved: false}` when `confirm` is false; `{moved: true, dest}` when true (after moving + repointing the catalog row).
  - `/api/summary` gains `"arabic_movies": <int>`.

- [ ] **Step 1: Write the failing tests**

Add to `tests/web/test_app.py`:

```python
def test_arabic_list_and_move(tmp_path):
    db = str(tmp_path / "m.db"); init_db(db); conn = get_connection(db)
    src = "/share/Movies/01-Ready/Heat (1995)/Heat (1995).mkv"
    upsert_media_file(conn, dict(
        filepath=src, filename="Heat (1995).mkv", extension=".mkv",
        parent_directory="/share/Movies/01-Ready/Heat (1995)",
        file_size_bytes=10, fast_hash="fh", os_hash="oh",
        item_type="movie", audio_languages='["ara","eng"]'))
    moved = {}
    app = create_app(
        db, str(tmp_path / "q"),
        media_paths=["/share/TV Shows/01-Ready", "/share/Movies/01-Ready"],
        exists_fn=lambda p: p == src,                  # src exists, dest doesn't
        makedirs_fn=lambda d, exist_ok: moved.update({"mkdir": d}),
        move_fn=lambda s, d: moved.update({"move": (s, d)}))
    client = TestClient(app)
    dest = "/share/Movies/01-Ready/02-ArabicReady/Heat (1995)/Heat (1995).mkv"

    # list
    lst = client.get("/api/arabic").json()
    assert lst["count"] == 1 and lst["items"][0]["filepath"] == src

    # preview moves nothing
    pv = client.post("/api/arabic/preview", json={"filepath": src}).json()
    assert pv["dest"] == dest and "move" not in moved

    # dry-run (confirm omitted) moves nothing
    dr = client.post("/api/arabic/move", json={"filepath": src}).json()
    assert dr["moved"] is False and "move" not in moved

    # confirmed move
    r = client.post("/api/arabic/move", json={"filepath": src, "confirm": True})
    assert r.status_code == 200 and r.json()["moved"] is True
    assert moved["move"] == (src, dest)
    assert get_media_row(conn, dest) is not None      # repointed
    assert get_media_row(conn, src) is None
    # gone from the list now that it lives under 02-ArabicReady
    assert client.get("/api/arabic").json()["count"] == 0


def test_arabic_move_refuses_overwrite(tmp_path):
    db = str(tmp_path / "m.db"); init_db(db); conn = get_connection(db)
    src = "/share/Movies/01-Ready/Heat (1995)/Heat (1995).mkv"
    upsert_media_file(conn, dict(
        filepath=src, filename="Heat (1995).mkv", extension=".mkv",
        parent_directory="/share/Movies/01-Ready/Heat (1995)",
        file_size_bytes=10, fast_hash="fh", os_hash="oh",
        item_type="movie", audio_languages='["ara"]'))
    app = create_app(
        db, str(tmp_path / "q"),
        media_paths=["/share/Movies/01-Ready"],
        exists_fn=lambda p: True,                       # dest already exists
        makedirs_fn=lambda d, exist_ok: None,
        move_fn=lambda s, d: (_ for _ in ()).throw(AssertionError("must not move")))
    client = TestClient(app)
    r = client.post("/api/arabic/move", json={"filepath": src, "confirm": True})
    assert r.status_code == 409
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/web/test_app.py::test_arabic_list_and_move tests/web/test_app.py::test_arabic_move_refuses_overwrite -q`
Expected: FAIL (404/422 — endpoints not defined yet).

- [ ] **Step 3: Implement**

In `web_dashboard.py`:

(a) Extend the relocate import (line 19) to include `arabic_target`:

```python
from src.web.relocate import pick_roots, build_target, relocate_file, arabic_target
```

(b) Add the model next to the other `*Body` classes (after `RelocateBody`):

```python
class ArabicBody(BaseModel):
    filepath: str
    confirm: bool = False
```

(c) Add the import for the service. The existing services import block (lines 14-16) pulls several names; add `arabic_audio_movies` to it. After editing it must include `arabic_audio_movies`, e.g.:

```python
from src.web.services import (library_kpis, variant_conflicts, unmatched_list,
                              ..., arabic_audio_movies)
```

(Keep the existing names; just append `arabic_audio_movies`.)

(d) Add `"arabic_movies"` to the `/api/summary` return dict (inside the `summary()` function, alongside `"unmatched"`):

```python
            "unmatched": len(unmatched_list(c)),
            "arabic_movies": arabic_audio_movies(c)["count"],
```

(e) Add the endpoints near the relocate block (after `relocate_execute`):

```python
    ARABIC_SUBDIR = "02-ArabicReady"

    def _arabic_dest(filepath):
        movies_root, _ = pick_roots(media_paths)
        if not movies_root:
            raise HTTPException(status_code=400, detail="No movies root configured")
        return arabic_target(movies_root, filepath, ARABIC_SUBDIR)

    @app.get("/api/arabic")
    def arabic():
        return arabic_audio_movies(conn())

    @app.post("/api/arabic/preview")
    def arabic_preview(body: ArabicBody):
        if get_media_row(conn(), body.filepath) is None:
            raise HTTPException(status_code=404, detail="Unknown file")
        dest = _arabic_dest(body.filepath)
        return {"src": body.filepath, "dest": dest,
                "dest_exists": exists_fn(to_local_path(dest, path_map))}

    @app.post("/api/arabic/move")
    def arabic_move(body: ArabicBody):
        c = conn()
        if get_media_row(c, body.filepath) is None:
            raise HTTPException(status_code=404, detail="Unknown file")
        dest = _arabic_dest(body.filepath)
        if not body.confirm:
            return {"src": body.filepath, "dest": dest, "moved": False}
        try:
            relocate_file(to_local_path(body.filepath, path_map),
                          to_local_path(dest, path_map), exists_fn, makedirs_fn, move_fn)
        except FileExistsError:
            raise HTTPException(status_code=409, detail=f"Destination already exists: {dest}")
        except FileNotFoundError:
            raise HTTPException(status_code=404, detail="Source file not reachable")
        update_media_path(c, body.filepath, dest)
        return {"moved": True, "dest": dest}
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest tests/web/test_app.py -q`
Expected: PASS (new tests + the existing summary test still green).

- [ ] **Step 5: Commit**

```bash
git add web_dashboard.py tests/web/test_app.py
git commit -m "feat: add /api/arabic list, preview, and move endpoints"
```

---

### Task 4: Arabic Audio tab (nav button, section, JS, overview bullet)

**Files:**
- Modify: `web_dashboard.py` (inline `_INDEX_HTML`: nav, section, JS, overview bullet)
- Test: `tests/web/test_app.py` (HTML smoke assertion)

**Interfaces:**
- Consumes: `GET /api/arabic`, `POST /api/arabic/move` (Task 3), the existing `showTab`, `playFile`, `esc`, `GB` helpers in the inline JS.
- Produces: a `data-tab="arabic"` nav button + `section[data-panel="arabic"]`, a `loadArabic()`/`moveArabic()` JS pair, and one Overview bullet.

- [ ] **Step 1: Write the failing test**

Add to `tests/web/test_app.py`:

```python
def test_index_has_arabic_tab(tmp_path):
    client, _ = _setup(tmp_path)
    html = client.get("/").text
    assert 'data-tab="arabic"' in html
    assert "Arabic Audio" in html
    assert "loadArabic" in html
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/web/test_app.py::test_index_has_arabic_tab -q`
Expected: FAIL (`data-tab="arabic"` not in HTML).

- [ ] **Step 3: Implement (nav button)**

In `web_dashboard.py`, in the `<nav>` block, insert the Arabic Audio button immediately **before** the Needs Review button (the `data-tab="review"` line):

```html
    <button data-tab="arabic"    data-panel="arabic"  class="tab px-4 py-2 -mb-px border-b-2 border-transparent">Arabic Audio</button>
```

- [ ] **Step 4: Implement (section)**

Add a section just before the `<!-- REVIEW -->` / `data-panel="review"` section:

```html
  <!-- ARABIC AUDIO -->
  <section data-panel="arabic" class="hidden">
    <div id="arabic-head" class="flex items-center gap-3 mb-3 text-sm text-slate-600"></div>
    <div id="arabic-list" class="space-y-1 text-sm"></div>
  </section>
```

- [ ] **Step 5: Implement (loader + move JS)**

Add to the inline `<script>` (near the other `load*` functions). Uses existing helpers `esc`, `GB`, `playFile`:

```javascript
// ---- arabic audio ----
async function loadArabic() {
  const d = await (await fetch('/api/arabic')).json();
  window.arabicLoaded = true;
  document.getElementById('arabic-head').innerHTML =
    `<b>${d.count}</b> movie(s) with an Arabic audio track &bull; ${GB(d.total_bytes)}`;
  document.getElementById('arabic-list').innerHTML = d.items.map(it => `
    <div class="flex items-center gap-2 border-b py-1" data-fp="${esc(it.filepath)}">
      <span class="flex-1 truncate" title="${esc(it.filepath)}">${esc(it.title)}
        <span class="text-slate-400">(${(it.audio_languages||[]).join(', ')})</span></span>
      <button onclick="playFile('${esc(it.filepath)}')" class="text-slate-600 hover:underline shrink-0" title="Play in VLC">&#9654;</button>
      <button onclick="moveArabic('${esc(it.filepath)}')" class="text-blue-600 hover:underline shrink-0">Move &rarr; 02-ArabicReady</button>
    </div>`).join('') || '<p class="text-slate-400">No Arabic-audio movies found yet (probe still running?).</p>';
}

async function moveArabic(fp) {
  const pv = await (await fetch('/api/arabic/move', {method:'POST',
    headers:{'Content-Type':'application/json'}, body:JSON.stringify({filepath:fp})})).json();
  if (!confirm('Move this video file?\n\nFrom: ' + pv.src + '\nTo:   ' + pv.dest)) return;
  const r = await fetch('/api/arabic/move', {method:'POST',
    headers:{'Content-Type':'application/json'}, body:JSON.stringify({filepath:fp, confirm:true})});
  if (r.ok) {
    document.querySelector(`#arabic-list [data-fp="${CSS.escape(fp)}"]`)?.remove();
  } else {
    const e = await r.json(); alert('Move failed: ' + (e.detail || 'error'));
  }
}
```

- [ ] **Step 6: Wire the tab into `showTab`**

In `showTab(name)`, add a lazy-load line alongside the other `if (name === ...)` loaders:

```javascript
  if (name === 'arabic' && !window.arabicLoaded) loadArabic();
```

- [ ] **Step 7: Implement (overview bullet)**

In `loadOverview()`, append one bullet to the `overview-extra` template (only when there are any), after the existing bullets:

```javascript
    ${s.arabic_movies ? `<p>&bull; <b>${s.arabic_movies.toLocaleString()}</b> movies with an Arabic audio track. Open the <b>Arabic Audio</b> tab.</p>` : ''}`;
```

(Append inside the existing backtick template that sets `overview-extra`, before the closing backtick.)

- [ ] **Step 8: Run tests to verify they pass**

Run: `python -m pytest tests/web/test_app.py::test_index_has_arabic_tab -q`
Expected: PASS.

- [ ] **Step 9: Full suite**

Run: `python -m pytest -q`
Expected: PASS (all tests).

- [ ] **Step 10: Commit**

```bash
git add web_dashboard.py tests/web/test_app.py
git commit -m "feat: add Arabic Audio dashboard tab (list + move flow)"
```

---

### Task 5: Docs + memory

**Files:**
- Modify: `CLAUDE.md` (dashboard tab list + one invariant), `RUNBOOK.md` (new tab section)
- Modify: memory `arabic-audio-feature.md` + `MEMORY.md` (planned → built)

- [ ] **Step 1: Update CLAUDE.md**

In the "Present (`web_dashboard.py` tabs: …)" line, add `Arabic Audio` before `Needs Review`. Add one invariant bullet to the cross-cutting list:

```markdown
- **The Arabic-audio tab** (`services.arabic_audio_movies`) flags movies whose `audio_languages` JSON contains `ara`/`ar` (tagged only; needs `probe_dupes.py`), and its **Move** reparents the video file to `<movies_root>/02-ArabicReady/<folder>/` via `relocate.arabic_target` + the shared `relocate_file` (no-overwrite). Sidecars are intentionally left behind; the catalog row is repointed so the movie drops off the list.
```

- [ ] **Step 2: Update RUNBOOK.md**

Add a tab section after the Subtitles section (mirror the existing tab write-ups):

```markdown
### Arabic Audio
Movies that have an **Arabic audio track** (detected from the probe data).
- **Move → 02-ArabicReady** — moves just the video file into a `02-ArabicReady`
  folder under your Movies share (keeping its `Title (Year)` folder name). It
  shows the exact From/To and asks you to confirm first; subtitles/NFO are left
  in the original folder. Nothing is deleted.
- The list fills in as `probe_dupes.py` finishes; a movie only appears once its
  audio has been probed.
```

- [ ] **Step 3: Update memory**

Edit `C:\Users\user\.claude\projects\C--Users-user-MyImageApp-media-organize-app-Claude\memory\arabic-audio-feature.md`: change status from "planned" to built, noting the tab, `arabic_audio_movies`, `arabic_target`, and the `02-ArabicReady` reparent. Update its one-line hook in `MEMORY.md` accordingly.

- [ ] **Step 4: Commit**

```bash
git add CLAUDE.md RUNBOOK.md
git commit -m "docs: document the Arabic Audio tab"
```

---

## Self-Review

- **Spec coverage:** detection (Task 2), reparent target (Task 1), endpoints with dry-run/no-overwrite (Task 3), tab UI + overview bullet (Task 4), docs/memory (Task 5) — all spec sections covered.
- **Placeholders:** none — every step has concrete code/commands.
- **Type consistency:** `arabic_target(movies_root, filepath, subdir)` and `arabic_audio_movies(conn) -> {items,count,total_bytes}` are used identically in Tasks 3-4; endpoint shapes match the tests.
- **Scope:** single feature, one plan. Bulk-move, undo, TV, untagged review explicitly out of scope.
