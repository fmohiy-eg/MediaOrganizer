from src.database import init_db, get_connection
from src.repository import upsert_media_file, get_media_row
from prune_live import find_stale, delete_rows


def _rec(fp):
    return dict(filepath=fp, filename="x.mkv", extension=".mkv", parent_directory="d",
                file_size_bytes=1, fast_hash="h", os_hash="o")


def test_find_stale_lists_only_missing_files(tmp_path):
    db = str(tmp_path / "m.db"); init_db(db); conn = get_connection(db)
    real = tmp_path / "real.mkv"; real.write_bytes(b"x")
    gone = str(tmp_path / "gone.mkv")
    upsert_media_file(conn, _rec(str(real)))
    upsert_media_file(conn, _rec(gone))
    stale, total = find_stale(conn)
    assert total == 2
    assert stale == [gone]                       # only the missing file


def test_delete_rows_removes_only_listed(tmp_path):
    db = str(tmp_path / "m.db"); init_db(db); conn = get_connection(db)
    real = tmp_path / "real.mkv"; real.write_bytes(b"x")
    gone = str(tmp_path / "gone.mkv")
    upsert_media_file(conn, _rec(str(real)))
    upsert_media_file(conn, _rec(gone))
    delete_rows(conn, [gone])
    assert get_media_row(conn, gone) is None
    assert get_media_row(conn, str(real)) is not None


def test_find_stale_empty_when_all_present(tmp_path):
    db = str(tmp_path / "m.db"); init_db(db); conn = get_connection(db)
    real = tmp_path / "real.mkv"; real.write_bytes(b"x")
    upsert_media_file(conn, _rec(str(real)))
    stale, total = find_stale(conn)
    assert stale == [] and total == 1
