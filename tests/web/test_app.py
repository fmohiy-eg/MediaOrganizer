import os
from fastapi.testclient import TestClient
from src.database import init_db, get_connection
from src.repository import upsert_media_file, get_media_row
from web_dashboard import create_app, _search_params

# Audio-flag config matching the original "Arabic Audio" behaviour, for tests that
# exercise the (now configurable) flagged-audio feature.
_AF = {"languages": ["ara", "ar"], "label": "Arabic Audio", "staging_subdir": "02-ArabicReady"}


def test_search_params_movie_constrains_to_movie_type():
    # tmdb_id alone is ambiguous (movie 11519 = "1941", TV 11519 = "Weeds"); the
    # search MUST pin type=movie or it pulls in TV subtitles.
    p = _search_params("/share/Movies/01-Ready/1941 (1979)/1941 (1979).mp4",
                       {"metadata_id": "tmdb:11519"})
    assert p == {"tmdb_id": 11519, "type": "movie"}


def test_search_params_episode_constrains_to_episode_type():
    p = _search_params("/share/TV Shows/Show (2010)/Season 02/Show (2010) - S02E03 - X.mkv",
                       {"metadata_id": "tvdb:5"})
    assert p["type"] == "episode" and p["season_number"] == 2 and p["episode_number"] == 3
    assert p["query"] == "Show"


def test_search_params_unmatched_movie_uses_query_year_and_movie_type():
    p = _search_params("/share/Movies/Heat (1995)/Heat (1995).mkv", {"metadata_id": None})
    assert p["type"] == "movie" and p["query"] == "Heat" and p["year"] == 1995
    assert "tmdb_id" not in p


def test_quality_variants_endpoint_and_tab(tmp_path):
    db = str(tmp_path / "m.db"); init_db(db); conn = get_connection(db)
    for path, h, size in [("/movies/Heat 1080p/Heat.mkv", 1080, 8_000_000_000),
                          ("/movies/Heat 720p/Heat.mkv", 720, 3_000_000_000)]:
        upsert_media_file(conn, dict(
            filepath=path, filename="Heat.mkv", extension=".mkv",
            parent_directory=path.rsplit("/", 1)[0], file_size_bytes=size,
            fast_hash="h", os_hash="o", item_type="movie", metadata_id="tmdb:1",
            resolution_width=1920, resolution_height=h, duration_ms=6_000_000,
            video_codec="hevc", bitrate=8_000_000))
    client = TestClient(create_app(db, str(tmp_path / "q")))
    d = client.get("/api/quality").json()
    assert d["group_count"] == 1 and d["groups"][0]["items"][0]["is_keeper"]
    assert d["total_bytes"] == 3_000_000_000
    html = client.get("/").text
    assert 'data-tab="quality"' in html and "loadQuality" in html


def test_default_title_has_no_nas_and_no_instance_badge(tmp_path):
    client, _ = _setup(tmp_path)
    html = client.get("/").text
    assert "<title>Media Organizer</title>" in html
    assert "NAS Media Organizer" not in html
    assert "__INSTANCE_BADGE__" not in html and "__TITLE_SUFFIX__" not in html


def test_instance_name_shown_in_header_and_title_escaped(tmp_path):
    db = str(tmp_path / "m.db"); init_db(db)
    client = TestClient(create_app(db, str(tmp_path / "q"), instance_name="Fork <test>"))
    html = client.get("/").text
    # appears escaped in BOTH the browser title suffix and the header badge
    assert html.count("Fork &lt;test&gt;") >= 2
    assert "Fork <test>" not in html                     # never injected raw


def test_relocate_preview_clear_error_when_root_name_unrecognized(tmp_path):
    # Folders not named Movies/TV -> pick_roots can't identify them; Fix must return
    # a clear 400, not a 500 crash.
    db = str(tmp_path / "m.db"); init_db(db); conn = get_connection(db)
    src = "/lib/Films/Heat (1995)/Heat (1995).mkv"
    upsert_media_file(conn, dict(filepath=src, filename="Heat (1995).mkv", extension=".mkv",
        parent_directory="/lib/Films/Heat (1995)", file_size_bytes=10, fast_hash="h",
        os_hash="o", item_type="movie"))
    app = create_app(db, str(tmp_path / "q"), media_paths=["/lib/Films", "/lib/Series"])
    r = TestClient(app).post("/api/relocate/preview",
        json={"filepath": src, "kind": "movie", "details": {"title": "Heat", "year": 1995}})
    assert r.status_code == 400
    assert "Movies" in r.json()["detail"]


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
    assert os.path.exists(vid)  # still there


def test_delete_execute_requires_confirm(tmp_path):
    client, vid = _setup(tmp_path)
    r = client.post("/api/delete/execute", json={"filepath": vid, "confirm": False})
    assert r.status_code == 400


def test_delete_execute_quarantines(tmp_path):
    client, vid = _setup(tmp_path)
    r = client.post("/api/delete/execute", json={"filepath": vid, "confirm": True})
    assert r.status_code == 200
    assert not os.path.exists(vid)  # moved to quarantine


def test_relocate_execute_moves_and_updates_db(tmp_path):
    db = str(tmp_path / "m.db"); init_db(db); conn = get_connection(db)
    src = "/share/Movies/01-Ready/Wrong Name/wrong.avi"
    upsert_media_file(conn, dict(
        filepath=src, filename="wrong.avi", extension=".avi",
        parent_directory="/share/Movies/01-Ready/Wrong Name",
        file_size_bytes=1, fast_hash="fh", os_hash="oh"))
    moved = {}
    app = create_app(
        db, str(tmp_path / "q"),
        media_paths=["/share/TV Shows/01-Ready", "/share/Movies/01-Ready"],
        exists_fn=lambda p: p == src,                       # src exists, dest doesn't
        makedirs_fn=lambda d, exist_ok: moved.update({"mkdir": d}),
        move_fn=lambda s, d: moved.update({"move": (s, d)}))
    client = TestClient(app)
    body = {"filepath": src, "kind": "movie",
            "details": {"title": "Heat", "year": 1995, "metadata_id": "tmdb:949"},
            "confirm": True}
    dest = "/share/Movies/01-Ready/Heat (1995)/Heat (1995).avi"
    assert client.post("/api/relocate/preview", json=body).json()["dest"] == dest
    r = client.post("/api/relocate/execute", json=body)
    assert r.status_code == 200 and r.json()["dest"] == dest
    assert moved["move"] == (src, dest)
    assert get_media_row(conn, dest) is not None        # DB row repointed
    assert get_media_row(conn, src) is None


def test_relocate_smb_media_paths_stores_nas_dest(tmp_path):
    # PC config reality: media_paths are SMB, path_map maps NAS->SMB. The catalog
    # must stay NAS-style, so the repointed row must be a /share path, not backslash.
    db = str(tmp_path / "m.db"); init_db(db); conn = get_connection(db)
    src = "/share/Movies/01-Ready/Wrong Name/wrong.avi"
    upsert_media_file(conn, dict(
        filepath=src, filename="wrong.avi", extension=".avi",
        parent_directory="/share/Movies/01-Ready/Wrong Name",
        file_size_bytes=1, fast_hash="fh", os_hash="oh"))
    smb_src = r"\\nas\Movies\01-Ready\Wrong Name\wrong.avi"
    smb_dest = r"\\nas\Movies\01-Ready\Heat (1995)\Heat (1995).avi"
    moved = {}
    app = create_app(
        db, str(tmp_path / "q"),
        media_paths=[r"\\nas\TV Shows\01-Ready", r"\\nas\Movies\01-Ready"],
        path_map={"/share/TV Shows": r"\\nas\TV Shows", "/share/Movies": r"\\nas\Movies"},
        exists_fn=lambda p: p == smb_src,                   # src exists, dest doesn't
        makedirs_fn=lambda d, exist_ok: moved.update({"mkdir": d}),
        move_fn=lambda s, d: moved.update({"move": (s, d)}))
    client = TestClient(app)
    body = {"filepath": src, "kind": "movie",
            "details": {"title": "Heat", "year": 1995, "metadata_id": "tmdb:949"},
            "confirm": True}
    nas_dest = "/share/Movies/01-Ready/Heat (1995)/Heat (1995).avi"
    assert client.post("/api/relocate/preview", json=body).json()["dest"] == nas_dest
    r = client.post("/api/relocate/execute", json=body)
    assert r.status_code == 200 and r.json()["dest"] == nas_dest
    assert moved["move"] == (smb_src, smb_dest)             # disk op uses SMB paths
    assert get_media_row(conn, nas_dest) is not None        # catalog stays NAS-style
    assert get_media_row(conn, src) is None


def test_arabic_move_smb_media_paths_stores_nas_dest(tmp_path):
    db = str(tmp_path / "m.db"); init_db(db); conn = get_connection(db)
    src = "/share/Movies/01-Ready/Heat (1995)/Heat (1995).mkv"
    upsert_media_file(conn, dict(
        filepath=src, filename="Heat (1995).mkv", extension=".mkv",
        parent_directory="/share/Movies/01-Ready/Heat (1995)",
        file_size_bytes=10, fast_hash="fh", os_hash="oh",
        item_type="movie", audio_languages='["ara"]'))
    smb_src = r"\\nas\Movies\01-Ready\Heat (1995)\Heat (1995).mkv"
    smb_dest = r"\\nas\Movies\01-Ready\02-ArabicReady\Heat (1995)\Heat (1995).mkv"
    moved = {}
    app = create_app(
        db, str(tmp_path / "q"),
        media_paths=[r"\\nas\Movies\01-Ready"],
        path_map={"/share/Movies": r"\\nas\Movies"},
        audio_flag={"languages": ["ara"], "label": "Arabic Audio",
                    "staging_subdir": "02-ArabicReady"},
        exists_fn=lambda p: p == smb_src,
        makedirs_fn=lambda d, exist_ok: moved.update({"mkdir": d}),
        move_fn=lambda s, d: moved.update({"move": (s, d)}))
    client = TestClient(app)
    nas_dest = "/share/Movies/01-Ready/02-ArabicReady/Heat (1995)/Heat (1995).mkv"
    assert client.post("/api/audioflag/preview", json={"filepath": src}).json()["dest"] == nas_dest
    r = client.post("/api/audioflag/move", json={"filepath": src, "confirm": True})
    assert r.status_code == 200 and r.json()["dest"] == nas_dest
    assert moved["move"] == (smb_src, smb_dest)
    assert get_media_row(conn, nas_dest) is not None
    assert get_media_row(conn, src) is None


def test_index_shows_build_id(tmp_path):
    db = str(tmp_path / "m.db"); init_db(db)
    app = create_app(db, str(tmp_path / "q"), build_id="2026-06-25T10:00 abc1234")
    html = TestClient(app).get("/").text
    assert 'id="build"' in html
    assert "2026-06-25T10:00 abc1234" in html      # so a stale server is visible at a glance


def test_index_build_id_defaults_without_crashing(tmp_path):
    db = str(tmp_path / "m.db"); init_db(db)
    html = TestClient(create_app(db, str(tmp_path / "q"))).get("/").text
    assert 'id="build"' in html


class _FakeTvdb:
    def search(self, parsed):
        if parsed.get("series_title") == "Breaking Bad":
            return [{"metadata_id": "tvdb:81189", "title": "Breaking Bad", "year": 2008}]
        return []

    def get_episodes(self, series_id):
        return [{"season": 2, "episode": 5, "air_date": "2008-04-13", "name": "Breakage"}]


_BB_DEST = ("/share/TV Shows/01-Ready/Breaking Bad (2008)/Season 02/"
            "Breaking Bad (2008) - S02E05 - Breakage")


def test_organize_scan_lists_matched_unmatched_and_no_tags(tmp_path):
    db = str(tmp_path / "m.db"); init_db(db)
    files = ["/in/a.mkv", "/in/a.en.srt", "/in/a.nfo", "/in/b.mkv", "/in/c.mkv"]
    probes = {
        "/in/a.mkv": {"format": {"tags": {"show": "Breaking Bad", "season_number": "2",
                                          "episode_id": "5"}}, "streams": []},
        "/in/b.mkv": {"format": {"tags": {"show": "Nope Show", "season_number": "1",
                                          "episode_id": "1"}}, "streams": []},
        "/in/c.mkv": {"format": {"tags": {}}, "streams": []},
    }
    app = create_app(db, str(tmp_path / "q"), media_paths=["/share/TV Shows/01-Ready"],
                     tvdb_client=_FakeTvdb(), walk_fn=lambda f: files,
                     probe_json_fn=lambda p, *a: probes.get(p), exists_fn=lambda p: True)
    r = TestClient(app).post("/api/organize/scan", json={"folder": "/in"}).json()
    assert r["counts"] == {"matched": 1, "unmatched": 1, "no_tags": 1}
    m = next(it for it in r["items"] if it["status"] == "matched")
    assert m["dest"] == _BB_DEST + ".mkv"
    assert m["subtitles"][0]["src"] == "/in/a.en.srt"
    assert m["remove"] == ["/in/a.nfo"]


def test_organize_scan_404_when_folder_unreachable(tmp_path):
    db = str(tmp_path / "m.db"); init_db(db)
    app = create_app(db, str(tmp_path / "q"), media_paths=["/share/TV Shows/01-Ready"],
                     exists_fn=lambda p: False)
    assert TestClient(app).post("/api/organize/scan", json={"folder": "/nope"}).status_code == 404


def test_organize_apply_moves_subs_quarantines_and_indexes(tmp_path):
    db = str(tmp_path / "m.db"); init_db(db); conn = get_connection(db)
    moved = []
    srcs = {"/in/a.mkv", "/in/a.en.srt", "/in/a.nfo"}
    item = {"status": "matched", "src": "/in/a.mkv", "series": "Breaking Bad", "year": 2008,
            "season": 2, "episode": 5, "ep_title": "Breakage", "ext": ".mkv",
            "metadata_id": "tvdb:81189",
            "subtitles": [{"src": "/in/a.en.srt", "dest": "ignored-recomputed"}],
            "remove": ["/in/a.nfo"]}
    app = create_app(db, str(tmp_path / "q"), media_paths=["/share/TV Shows/01-Ready"],
                     exists_fn=lambda p: p in srcs,            # srcs exist, dests don't
                     makedirs_fn=lambda d, exist_ok: None,
                     move_fn=lambda s, d: moved.append((s, d)),
                     getsize_fn=lambda p: 123)
    r = TestClient(app).post("/api/organize/apply", json={"items": [item], "confirm": True})
    assert r.status_code == 200
    assert r.json() == {"moved": 1, "subtitles_moved": 1, "removed": 1, "skipped": 0,
                        "errors": [], "cleanup": None}
    assert ("/in/a.mkv", _BB_DEST + ".mkv") in moved
    assert ("/in/a.en.srt", _BB_DEST + ".en.srt") in moved
    assert any(s == "/in/a.nfo" for s, _ in moved)            # nfo quarantined
    row = get_media_row(conn, _BB_DEST + ".mkv")              # indexed into catalog
    assert row is not None and row["item_type"] == "episode" and row["file_size_bytes"] == 123


def test_organize_apply_repoints_existing_catalog_row(tmp_path):
    # Real use case: the source folder is UNDER Movies, so the file already has a
    # catalog row (a 'movie'). Moving it must remove that stale row and carry the
    # already-probed stream data onto the new episode row — no ghost left behind.
    db = str(tmp_path / "m.db"); init_db(db); conn = get_connection(db)
    old_nas = "/share/Movies/Misfiled/ep.mkv"
    upsert_media_file(conn, dict(
        filepath=old_nas, filename="ep.mkv", extension=".mkv",
        parent_directory="/share/Movies/Misfiled", file_size_bytes=999,
        fast_hash="FH", os_hash="OH", item_type="movie",
        duration_ms=1234000, audio_languages='["eng"]'))
    src = "//nas/Movies/Misfiled/ep.mkv"            # what walk_fn yields on the PC
    moved = []
    item = {"status": "matched", "src": src, "series": "Breaking Bad", "year": 2008,
            "season": 2, "episode": 5, "ep_title": "Breakage", "ext": ".mkv",
            "metadata_id": "tvdb:81189", "subtitles": [], "remove": []}
    app = create_app(db, str(tmp_path / "q"),
                     media_paths=[r"\\nas\TV Shows\01-Ready", r"\\nas\Movies\01-Ready"],
                     path_map={"/share/TV Shows": r"\\nas\TV Shows", "/share/Movies": r"\\nas\Movies"},
                     exists_fn=lambda p: p == src, makedirs_fn=lambda d, exist_ok: None,
                     move_fn=lambda s, d: moved.append((s, d)), getsize_fn=lambda p: 0)
    r = TestClient(app).post("/api/organize/apply", json={"items": [item], "confirm": True})
    assert r.status_code == 200 and r.json()["moved"] == 1
    new_dest = _BB_DEST + ".mkv"
    assert get_media_row(conn, old_nas) is None        # stale Movies row removed
    row = get_media_row(conn, new_dest)
    assert row is not None and row["item_type"] == "episode"
    assert row["season_number"] == 2 and row["episode_number"] == 5
    assert row["duration_ms"] == 1234000               # probe data carried over
    assert row["file_size_bytes"] == 999               # size carried over (getsize gave 0)


def test_organize_apply_cleanup_sweeps_leftovers_and_removes_empty_folder(tmp_path):
    db = str(tmp_path / "m.db"); init_db(db)
    folder = "//nas/Movies/WW"
    src = folder + "/ep.mkv"
    leftovers = [folder + "/poster.jpg", folder + "/movie.nfo", folder + "/ep.trickplay"]
    moved, removed_dirs = [], []
    item = {"status": "matched", "src": src, "series": "Breaking Bad", "year": 2008,
            "season": 2, "episode": 5, "ep_title": "Breakage", "ext": ".mkv",
            "metadata_id": "tvdb:81189", "subtitles": [], "remove": []}
    app = create_app(db, str(tmp_path / "q"),
                     media_paths=[r"\\nas\TV Shows\01-Ready", r"\\nas\Movies\01-Ready"],
                     path_map={"/share/TV Shows": r"\\nas\TV Shows", "/share/Movies": r"\\nas\Movies"},
                     exists_fn=lambda p: p == src or p in leftovers,  # src+leftovers exist, dests don't
                     makedirs_fn=lambda d, exist_ok: None,
                     move_fn=lambda s, d: moved.append((s, d)),
                     scandir_fn=lambda f: list(leftovers),     # what remains after the move
                     rmdir_fn=lambda f: removed_dirs.append(f))
    r = TestClient(app).post("/api/organize/apply",
                             json={"folder": folder, "items": [item], "cleanup": True, "confirm": True})
    body = r.json()
    assert body["moved"] == 1
    assert body["cleanup"]["swept"] == 3 and body["cleanup"]["folder_removed"] is True
    assert removed_dirs == [folder]
    swept_srcs = {s for s, _ in moved}
    assert set(leftovers).issubset(swept_srcs)


def test_organize_apply_cleanup_skips_when_a_video_remains(tmp_path):
    db = str(tmp_path / "m.db"); init_db(db)
    folder = "//nas/Movies/WW"
    src = folder + "/ep.mkv"
    after = [folder + "/other.mkv", folder + "/poster.jpg"]   # a video still present
    removed_dirs = []
    item = {"status": "matched", "src": src, "series": "Breaking Bad", "year": 2008,
            "season": 2, "episode": 5, "ep_title": "Breakage", "ext": ".mkv",
            "metadata_id": "tvdb:81189", "subtitles": [], "remove": []}
    app = create_app(db, str(tmp_path / "q"),
                     media_paths=[r"\\nas\TV Shows\01-Ready", r"\\nas\Movies\01-Ready"],
                     path_map={"/share/TV Shows": r"\\nas\TV Shows", "/share/Movies": r"\\nas\Movies"},
                     exists_fn=lambda p: p == src, makedirs_fn=lambda d, exist_ok: None,
                     move_fn=lambda s, d: None, scandir_fn=lambda f: list(after),
                     rmdir_fn=lambda f: removed_dirs.append(f))
    body = TestClient(app).post("/api/organize/apply",
                                json={"folder": folder, "items": [item], "cleanup": True, "confirm": True}).json()
    assert body["cleanup"]["swept"] == 0 and body["cleanup"]["folder_removed"] is False
    assert removed_dirs == []                      # folder left intact (a video remains)


def test_organize_apply_requires_confirm(tmp_path):
    db = str(tmp_path / "m.db"); init_db(db)
    app = create_app(db, str(tmp_path / "q"), media_paths=["/share/TV Shows/01-Ready"])
    assert TestClient(app).post("/api/organize/apply", json={"items": []}).status_code == 400


def test_index_has_organize_tab(tmp_path):
    db = str(tmp_path / "m.db"); init_db(db)
    html = TestClient(create_app(db, str(tmp_path / "q"))).get("/").text
    assert 'data-tab="organize"' in html
    assert 'id="orgFolder"' in html


def test_index_has_admin_tab(tmp_path):
    db = str(tmp_path / "m.db"); init_db(db)
    html = TestClient(create_app(db, str(tmp_path / "q"))).get("/").text
    assert 'data-tab="admin"' in html
    assert 'id="admin-status"' in html and 'id="admin-sync-btn"' in html


def test_admin_status_and_integrity(tmp_path):
    db = str(tmp_path / "m.db"); init_db(db); conn = get_connection(db)
    upsert_media_file(conn, dict(filepath="/share/Movies/a.mkv", filename="a.mkv",
        extension=".mkv", parent_directory="/share/Movies", file_size_bytes=1,
        fast_hash="h", os_hash="o"))
    app = create_app(db, str(tmp_path / "q"), build_id="B1")
    client = TestClient(app)
    s = client.get("/api/admin/status").json()
    assert s["rows"] == 1 and s["build_id"] == "B1" and s["db_mtime"] is not None
    assert client.get("/api/admin/integrity").json()["result"] == "ok"


def test_admin_backup_creates_openable_snapshot(tmp_path):
    db = str(tmp_path / "m.db"); init_db(db); conn = get_connection(db)
    upsert_media_file(conn, dict(filepath="/x/a.mkv", filename="a.mkv", extension=".mkv",
        parent_directory="/x", file_size_bytes=1, fast_hash="h", os_hash="o"))
    r = TestClient(create_app(db, str(tmp_path / "q"))).post("/api/admin/backup").json()
    assert os.path.exists(r["path"]) and r["size_bytes"] > 0
    snap = get_connection(r["path"])
    assert snap.execute("SELECT COUNT(*) FROM media_files").fetchone()[0] == 1


def test_admin_sync_deletions_scan_and_apply(tmp_path):
    import time
    db = str(tmp_path / "m.db"); init_db(db); conn = get_connection(db)
    for p in ("/share/Movies/present.mkv", "/share/Movies/gone.mkv"):
        upsert_media_file(conn, dict(filepath=p, filename="x.mkv", extension=".mkv",
            parent_directory="/share/Movies", file_size_bytes=1, fast_hash="h", os_hash="o"))
    app = create_app(db, str(tmp_path / "q"),
                     exists_fn=lambda p: p == "/share/Movies/present.mkv")
    client = TestClient(app)
    assert client.get("/api/admin/sync/status").json()["phase"] == "idle"
    assert client.post("/api/admin/sync/scan").json()["started"] is True
    for _ in range(200):
        st = client.get("/api/admin/sync/status").json()
        if not st["running"] and st["phase"] == "done":
            break
        time.sleep(0.02)
    assert st["phase"] == "done" and st["missing_count"] == 1
    assert st["sample"] == ["/share/Movies/gone.mkv"]
    # apply requires confirm
    assert client.post("/api/admin/sync/apply", json={}).status_code == 400
    r = client.post("/api/admin/sync/apply", json={"confirm": True}).json()
    assert r["removed"] == 1
    assert get_media_row(conn, "/share/Movies/gone.mkv") is None
    assert get_media_row(conn, "/share/Movies/present.mkv") is not None


def test_admin_quarantine_scan_and_purge(tmp_path):
    import time
    db = str(tmp_path / "m.db"); init_db(db)
    q = tmp_path / "quar"
    (q / "share" / "Movies").mkdir(parents=True)
    (q / "share" / "Movies" / "big.mkv").write_bytes(b"x" * 1000)
    (q / "loose.nfo").write_bytes(b"y" * 50)
    client = TestClient(create_app(db, str(q)))
    assert client.post("/api/admin/quarantine/scan").json()["started"] is True
    for _ in range(200):
        st = client.get("/api/admin/quarantine/status").json()
        if not st["running"] and st["phase"] == "done":
            break
        time.sleep(0.02)
    assert st["count"] == 2 and st["bytes"] == 1050
    assert st["largest"][0]["bytes"] == 1000             # biggest first
    # purge requires confirm, then empties the quarantine
    assert client.post("/api/admin/quarantine/purge", json={}).status_code == 400
    r = client.post("/api/admin/quarantine/purge", json={"confirm": True}).json()
    assert r["removed"] == 2
    assert list(q.iterdir()) == []


def test_admin_quarantine_scan_empty_when_missing(tmp_path):
    db = str(tmp_path / "m.db"); init_db(db)
    import time
    client = TestClient(create_app(db, str(tmp_path / "nope_quar")))
    client.post("/api/admin/quarantine/scan")
    for _ in range(200):
        st = client.get("/api/admin/quarantine/status").json()
        if st["phase"] == "done":
            break
        time.sleep(0.02)
    assert st["count"] == 0 and st["bytes"] == 0


class _FakeTmdbMatch:
    def search(self, parsed):
        return [{"metadata_id": "tmdb:949", "title": "Heat", "year": 1995}]


class _FakeProc:
    def __init__(self):
        self._alive = True
    def poll(self):
        return None if self._alive else 0
    def terminate(self):
        self._alive = False


def test_admin_rematch_matches_unmatched(tmp_path):
    import time
    db = str(tmp_path / "m.db"); init_db(db); conn = get_connection(db)
    for fp in ("/share/Movies/Heat (1995)/Heat (1995).mkv",
               "/share/Movies/Heat (1995)/Heat (1995).avi"):
        upsert_media_file(conn, dict(filepath=fp, filename=os.path.basename(fp),
            extension=os.path.splitext(fp)[1], parent_directory="/share/Movies/Heat (1995)",
            file_size_bytes=1, fast_hash="h", os_hash="o", match_status="unmatched"))
    app = create_app(db, str(tmp_path / "q"), tmdb_client=_FakeTmdbMatch())
    client = TestClient(app)
    assert client.post("/api/admin/rematch/start").json()["started"] is True
    for _ in range(200):
        st = client.get("/api/admin/rematch/status").json()
        if not st["running"] and st["phase"] == "done":
            break
        time.sleep(0.02)
    assert st["newly_matched"] == 1 and st["groups"] == 1
    row = get_media_row(conn, "/share/Movies/Heat (1995)/Heat (1995).mkv")
    assert row["match_status"] == "matched" and row["metadata_id"] == "tmdb:949"


def test_admin_probe_start_status_stop(tmp_path):
    db = str(tmp_path / "m.db"); init_db(db); conn = get_connection(db)
    upsert_media_file(conn, dict(filepath="/x/a.mkv", filename="a.mkv", extension=".mkv",
        parent_directory="/x", file_size_bytes=1, fast_hash="h", os_hash="o",
        duration_ms=1000))
    app = create_app(db, str(tmp_path / "q"), spawn_probe_fn=lambda: _FakeProc())
    client = TestClient(app)
    st = client.get("/api/admin/probe/status").json()
    assert st["running"] is False and st["probed"] == 1
    assert st["target"] == 1 and st["remaining"] == 0      # the lone movie is the whole target
    assert st["remaining_paths"] == []
    assert client.post("/api/admin/probe/start").json()["started"] is True
    assert client.get("/api/admin/probe/status").json()["running"] is True
    assert client.post("/api/admin/probe/start").json() == {"started": False, "running": True}
    assert client.post("/api/admin/probe/stop").json()["stopped"] is True
    assert client.get("/api/admin/probe/status").json()["running"] is False


def test_play_launches_translated_path(tmp_path):
    db = str(tmp_path / "m.db"); init_db(db); conn = get_connection(db)
    vid = tmp_path / "v.mkv"; vid.write_bytes(b"x")
    upsert_media_file(conn, dict(
        filepath="/share/Movies/v.mkv", filename="v.mkv", extension=".mkv",
        parent_directory="/share/Movies", file_size_bytes=1, fast_hash="fh", os_hash="oh"))
    opened = {}
    app = create_app(db, str(tmp_path / "q"),
                     path_map={"/share/Movies": str(tmp_path)},
                     player_fn=lambda p: opened.update({"path": p}))
    client = TestClient(app)
    r = client.post("/api/play", json={"filepath": "/share/Movies/v.mkv"})
    assert r.status_code == 200
    assert opened["path"] == str(vid)  # NAS path translated to the local file, then "played"


def test_play_unknown_file_404(tmp_path):
    db = str(tmp_path / "m.db"); init_db(db)
    client = TestClient(create_app(db, str(tmp_path / "q"), player_fn=lambda p: None))
    assert client.post("/api/play", json={"filepath": "/nope.mkv"}).status_code == 404


def test_cleanup_legacy_execute_quarantines_legacy_only(tmp_path):
    db = str(tmp_path / "m.db"); init_db(db); conn = get_connection(db)
    d = tmp_path / "Movie (2010)"; d.mkdir()
    modern = d / "Movie (2010).mkv"; modern.write_bytes(b"x")
    legacy = d / "Movie (2010).rm"; legacy.write_bytes(b"y")
    for f, ext in [(modern, ".mkv"), (legacy, ".rm")]:
        upsert_media_file(conn, dict(
            filepath=str(f), filename=f.name, extension=ext, parent_directory=str(d),
            file_size_bytes=1, fast_hash="fh", os_hash="oh"))
    app = create_app(db, str(tmp_path / "q"))
    client = TestClient(app)
    assert client.get("/api/cleanup/legacy").json()["count"] == 1
    r = client.post("/api/cleanup/legacy/execute", json={"confirm": True})
    assert r.status_code == 200 and r.json()["moved"] == 1
    assert not legacy.exists() and modern.exists()  # only the legacy copy moved


class _FakeOsClient:
    def login(self, u, p):
        return {"token": "SESSION"} if p == "good" else (_ for _ in ()).throw(RuntimeError("bad"))
    def search(self, **params):
        return [{"file_id": 7, "download_count": 10, "release": "R"}]
    def download(self, file_id, token):
        return {"ok": True, "link": "http://x/s.srt", "quota": {"remaining": 17}}
    def user_info(self, token):
        return {"allowed_downloads": 100, "downloads_count": 7,
                "remaining_downloads": 93, "reset_time": "11 hours"}


class _DLResp:
    content = b"1\n00:00:01,000 --> 00:00:02,000\nHi\n"


def _sub_setup(tmp_path):
    db = str(tmp_path / "m.db"); init_db(db); conn = get_connection(db)
    vid = tmp_path / "Movie (2012).mkv"; vid.write_bytes(b"x")
    upsert_media_file(conn, dict(
        filepath=str(vid), filename="Movie (2012).mkv", extension=".mkv",
        parent_directory=str(tmp_path), file_size_bytes=1, fast_hash="fh", os_hash="oh",
        metadata_id="tmdb:329"))
    app = create_app(db, str(tmp_path / "q"), os_client=_FakeOsClient(),
                     http_get=lambda url, timeout=None: _DLResp())
    return TestClient(app), str(vid)


def test_fetch_requires_login(tmp_path):
    client, vid = _sub_setup(tmp_path)
    r = client.post("/api/subtitles/fetch", json={"filepath": vid})
    assert r.status_code == 401


def test_login_then_fetch_writes_srt(tmp_path):
    client, vid = _sub_setup(tmp_path)
    assert client.post("/api/subtitles/login",
                       json={"username": "u", "password": "good"}).status_code == 200
    r = client.post("/api/subtitles/fetch", json={"filepath": vid})
    assert r.status_code == 200
    body = r.json()
    assert body["ok"] and body["quota"]["remaining"] == 17
    assert os.path.exists(os.path.splitext(vid)[0] + ".eng.srt")


def test_quota_requires_login_then_reports(tmp_path):
    client, _ = _sub_setup(tmp_path)
    assert client.get("/api/subtitles/quota").json() == {"logged_in": False}
    client.post("/api/subtitles/login", json={"username": "u", "password": "good"})
    q = client.get("/api/subtitles/quota").json()
    assert q["logged_in"] and q["used"] == 7 and q["remaining"] == 93
    assert q["allowed"] == 100 and q["reset_time"] == "11 hours"


def test_bad_login_rejected(tmp_path):
    client, _ = _sub_setup(tmp_path)
    r = client.post("/api/subtitles/login", json={"username": "u", "password": "bad"})
    assert r.status_code == 401


def test_audioflag_list_and_move(tmp_path):
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
        audio_flag=_AF,
        exists_fn=lambda p: p == src,                  # src exists, dest doesn't
        makedirs_fn=lambda d, exist_ok: moved.update({"mkdir": d}),
        move_fn=lambda s, d: moved.update({"move": (s, d)}))
    client = TestClient(app)
    dest = "/share/Movies/01-Ready/02-ArabicReady/Heat (1995)/Heat (1995).mkv"

    lst = client.get("/api/audioflag").json()
    assert lst["count"] == 1 and lst["items"][0]["filepath"] == src

    pv = client.post("/api/audioflag/preview", json={"filepath": src}).json()
    assert pv["dest"] == dest and "move" not in moved

    dr = client.post("/api/audioflag/move", json={"filepath": src}).json()
    assert dr["moved"] is False and "move" not in moved

    r = client.post("/api/audioflag/move", json={"filepath": src, "confirm": True})
    assert r.status_code == 200 and r.json()["moved"] is True
    assert moved["move"] == (src, dest)
    assert get_media_row(conn, dest) is not None      # repointed
    assert get_media_row(conn, src) is None
    assert client.get("/api/audioflag").json()["count"] == 0


def test_audioflag_disabled_when_no_languages(tmp_path):
    db = str(tmp_path / "m.db"); init_db(db); conn = get_connection(db)
    src = "/share/Movies/01-Ready/Heat (1995)/Heat (1995).mkv"
    upsert_media_file(conn, dict(
        filepath=src, filename="Heat (1995).mkv", extension=".mkv",
        parent_directory="/share/Movies/01-Ready/Heat (1995)",
        file_size_bytes=10, fast_hash="fh", os_hash="oh",
        item_type="movie", audio_languages='["ara"]'))
    # no audio_flag passed => feature disabled
    client = TestClient(create_app(db, str(tmp_path / "q"),
                                   media_paths=["/share/Movies/01-Ready"]))
    assert client.get("/api/audioflag").json()["count"] == 0
    cfg = client.get("/api/config").json()
    assert cfg["audio_flag"]["enabled"] is False


def test_audioflag_move_refuses_overwrite(tmp_path):
    db = str(tmp_path / "m.db"); init_db(db); conn = get_connection(db)
    src = "/share/Movies/01-Ready/Heat (1995)/Heat (1995).mkv"
    upsert_media_file(conn, dict(
        filepath=src, filename="Heat (1995).mkv", extension=".mkv",
        parent_directory="/share/Movies/01-Ready/Heat (1995)",
        file_size_bytes=10, fast_hash="fh", os_hash="oh",
        item_type="movie", audio_languages='["ara"]'))
    app = create_app(
        db, str(tmp_path / "q"),
        media_paths=["/share/Movies/01-Ready"], audio_flag=_AF,
        exists_fn=lambda p: True,                       # dest already exists
        makedirs_fn=lambda d, exist_ok: None,
        move_fn=lambda s, d: (_ for _ in ()).throw(AssertionError("must not move")))
    client = TestClient(app)
    r = client.post("/api/audioflag/move", json={"filepath": src, "confirm": True})
    assert r.status_code == 409


def test_index_has_audioflag_tab(tmp_path):
    client, _ = _setup(tmp_path)
    html = client.get("/").text
    assert 'data-tab="audioflag"' in html
    assert 'id="tab-audioflag"' in html
    assert "loadAudioFlag" in html
    assert "bootstrapConfig" in html


def test_config_endpoint_reports_audio_flag(tmp_path):
    db = str(tmp_path / "m.db"); init_db(db)
    client = TestClient(create_app(db, str(tmp_path / "q"),
                                   media_paths=["/share/Movies/01-Ready"], audio_flag=_AF))
    cfg = client.get("/api/config").json()["audio_flag"]
    assert cfg == {"enabled": True, "label": "Arabic Audio", "staging_subdir": "02-ArabicReady"}


def test_dup_rows_have_audioflag_move_link(tmp_path):
    client, _ = _setup(tmp_path)
    html = client.get("/").text
    # the per-file "move just this file to the staging folder" link lives in the dup card
    assert "Move just this file to" in html
    assert "moveAudioFlag" in html


def test_mismatch_endpoint(tmp_path):
    db = str(tmp_path / "m.db"); init_db(db); conn = get_connection(db)
    P = "/share/Movies/01-Ready/Superman (1978)"
    upsert_media_file(conn, dict(filepath=P + "/Superman (1978).mkv", filename="Superman (1978).mkv",
        extension=".mkv", parent_directory=P, file_size_bytes=100, fast_hash="h", os_hash="o"))
    upsert_media_file(conn, dict(filepath=P + "/Superman (1978) - CD1.mkv", filename="Superman (1978) - CD1.mkv",
        extension=".mkv", parent_directory=P, file_size_bytes=10, fast_hash="h", os_hash="o"))
    app = create_app(db, str(tmp_path / "q"), path_map={"/share/Movies": "\\h\Movies"})
    client = TestClient(app)
    d = client.get("/api/mismatch").json()
    assert d["group_count"] == 1 and d["file_count"] == 1
    assert d["groups"][0]["items"][0]["filename"] == "Superman (1978) - CD1.mkv"


def test_mismatch_single_machine_empty_path_map(tmp_path):
    # Single-machine: no path_map; catalog stores local media_paths directly. The
    # movies prefix must come from media_paths so the Mismatch tab still works.
    db = str(tmp_path / "m.db"); init_db(db); conn = get_connection(db)
    P = "/mnt/media/Movies/Superman (1978)"
    upsert_media_file(conn, dict(filepath=P + "/Superman (1978).mkv", filename="Superman (1978).mkv",
        extension=".mkv", parent_directory=P, file_size_bytes=100, fast_hash="h", os_hash="o"))
    upsert_media_file(conn, dict(filepath=P + "/Superman (1978) - CD1.mkv", filename="Superman (1978) - CD1.mkv",
        extension=".mkv", parent_directory=P, file_size_bytes=10, fast_hash="h", os_hash="o"))
    app = create_app(db, str(tmp_path / "q"),
                     media_paths=["/mnt/media/Movies", "/mnt/media/TV Shows"])  # no path_map
    d = TestClient(app).get("/api/mismatch").json()
    assert d["group_count"] == 1 and d["file_count"] == 1
    assert d["groups"][0]["items"][0]["filename"] == "Superman (1978) - CD1.mkv"


def test_index_has_mismatch_tab(tmp_path):
    client, _ = _setup(tmp_path)
    html = client.get("/").text
    assert 'data-tab="mismatch"' in html
    assert "Mismatch Videos" in html
    assert "loadMismatch" in html
    assert "mismatchDelete" in html


def test_audioflag_preview_reports_dest_exists(tmp_path):
    db = str(tmp_path / "m.db"); init_db(db); conn = get_connection(db)
    src = "/share/Movies/01-Ready/Heat (1995)/Heat (1995).mkv"
    upsert_media_file(conn, dict(filepath=src, filename="Heat (1995).mkv", extension=".mkv",
        parent_directory="/share/Movies/01-Ready/Heat (1995)", file_size_bytes=10,
        fast_hash="h", os_hash="o", item_type="movie", audio_languages='["ara"]'))
    # exists_fn says the destination is already there
    app = create_app(db, str(tmp_path / "q"), media_paths=["/share/Movies/01-Ready"],
                     audio_flag=_AF, exists_fn=lambda p: True)
    r = TestClient(app).post("/api/audioflag/preview", json={"filepath": src}).json()
    assert r["dest_exists"] is True
    # and when nothing exists at dest
    app2 = create_app(db, str(tmp_path / "q"), media_paths=["/share/Movies/01-Ready"],
                      audio_flag=_AF, exists_fn=lambda p: False)
    r2 = TestClient(app2).post("/api/audioflag/preview", json={"filepath": src}).json()
    assert r2["dest_exists"] is False


def test_audioflag_move_uses_preview_for_overwrite_warning(tmp_path):
    client, _ = _setup(tmp_path)
    html = client.get("/").text
    assert "/api/audioflag/preview" in html   # moveAudioFlag checks the target up front
    assert "dest_exists" in html


def test_index_has_dup_prefetch(tmp_path):
    client, _ = _setup(tmp_path)
    html = client.get("/").text
    assert "fetchGroupProbe" in html
    assert "prefetchDupGroups" in html


def test_index_has_dup_jump(tmp_path):
    client, _ = _setup(tmp_path)
    html = client.get("/").text
    assert "function dupJump" in html
    assert 'id="dupjump"' in html


def test_index_has_dup_kind_filter(tmp_path):
    client, _ = _setup(tmp_path)
    html = client.get("/").text
    assert 'id="dupkind"' in html
    assert "function dupSetKind" in html


def test_delete_unreachable_file_keeps_db_row(tmp_path):
    # Reproduces the original bug: a catalog NAS path that maps to a missing local
    # file must NOT drop the DB row (and must report an error), not silently vanish.
    db = str(tmp_path / "m.db"); init_db(db); conn = get_connection(db)
    nas = "/share/Movies/01-Ready/Heat (1995)/Heat (1995).mkv"
    upsert_media_file(conn, dict(filepath=nas, filename="Heat (1995).mkv", extension=".mkv",
        parent_directory="/share/Movies/01-Ready/Heat (1995)", file_size_bytes=10,
        fast_hash="h", os_hash="o"))
    # path_map points at a directory that doesn't contain the file -> unreachable
    app = create_app(db, str(tmp_path / "q"),
                     path_map={"/share/Movies": str(tmp_path / "nope")})
    r = TestClient(app).post("/api/delete/execute", json={"filepath": nas, "confirm": True})
    assert r.status_code == 404
    assert get_media_row(conn, nas) is not None    # row preserved — file was NOT lost


def test_delete_quarantines_via_path_map(tmp_path):
    # A reachable file (via path_map) is moved to quarantine and its row removed.
    db = str(tmp_path / "m.db"); init_db(db); conn = get_connection(db)
    realdir = tmp_path / "smb" / "Heat (1995)"; realdir.mkdir(parents=True)
    (realdir / "Heat (1995).mkv").write_bytes(b"x")
    nas = "/share/Movies/Heat (1995)/Heat (1995).mkv"
    upsert_media_file(conn, dict(filepath=nas, filename="Heat (1995).mkv", extension=".mkv",
        parent_directory="/share/Movies/Heat (1995)", file_size_bytes=1,
        fast_hash="h", os_hash="o"))
    q = tmp_path / "q"
    app = create_app(db, str(q), path_map={"/share/Movies": str(tmp_path / "smb")})
    r = TestClient(app).post("/api/delete/execute", json={"filepath": nas, "confirm": True})
    assert r.status_code == 200
    assert get_media_row(conn, nas) is None                       # row removed
    assert not (realdir / "Heat (1995).mkv").exists()             # file moved out
    assert r.json()["moved"]                                       # something was quarantined


def test_esc_escapes_backslashes(tmp_path):
    # onclick handlers embed filepaths in JS string literals; backslash paths
    # (e.g. SMB paths from a prior move) must be escaped or they corrupt the path.
    client, _ = _setup(tmp_path)
    html = client.get("/").text
    B = chr(92)
    # esc must include a backslash-doubling pass:  replace(/\\/g, '\\\\')
    assert ("/" + B * 2 + "/g, '" + B * 4 + "'") in html
