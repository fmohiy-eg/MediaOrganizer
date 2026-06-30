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
