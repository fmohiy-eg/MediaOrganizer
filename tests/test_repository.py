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


def test_update_stream_fields(tmp_path):
    from src.repository import update_stream_fields
    conn = _conn(tmp_path)
    upsert_media_file(conn, _rec("/m/v.mkv"))
    update_stream_fields(conn, "/m/v.mkv",
                         {"duration_ms": 5400000, "resolution_height": 1080,
                          "video_codec": "hevc", "subtitle_languages": "ignored"})
    row = get_media_row(conn, "/m/v.mkv")
    assert row["duration_ms"] == 5400000 and row["resolution_height"] == 1080
    assert row["video_codec"] == "hevc"


def test_update_media_path(tmp_path):
    from src.repository import update_media_path
    conn = _conn(tmp_path)
    upsert_media_file(conn, _rec("/old/wrong.avi"))
    update_media_path(conn, "/old/wrong.avi", "/new/Heat (1995)/Heat (1995).avi",
                      metadata_id="tmdb:949")
    assert get_media_row(conn, "/old/wrong.avi") is None
    row = get_media_row(conn, "/new/Heat (1995)/Heat (1995).avi")
    assert row["filename"] == "Heat (1995).avi"
    assert row["parent_directory"] == "/new/Heat (1995)"
    assert row["metadata_id"] == "tmdb:949" and row["match_status"] == "matched"


def test_all_media_paths(tmp_path):
    conn = _conn(tmp_path)
    upsert_media_file(conn, _rec("/m/a.mkv"))
    upsert_media_file(conn, _rec("/m/b.mkv"))
    assert sorted(all_media_paths(conn)) == ["/m/a.mkv", "/m/b.mkv"]
