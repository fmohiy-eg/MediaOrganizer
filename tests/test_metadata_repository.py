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
