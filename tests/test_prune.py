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
