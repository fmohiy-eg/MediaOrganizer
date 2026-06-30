import os
from src.database import init_db, get_connection
from src.indexer import scan_and_index
from src.repository import get_media_row


def _cfg(root):
    return {
        "media_paths": [root],
        "scan": {"valid_extensions": [".mkv"]},
        "hashing": {"partial_hash_threshold_bytes": 20_000_000, "partial_chunk_bytes": 10_000_000},
        "ffprobe": {"timeout_seconds": 5, "retries": 1},
    }


def _fake_probe(path, timeout, retries):
    return {"duration_ms": 1000, "bitrate": 100, "resolution_width": 1920,
            "resolution_height": 1080, "video_codec": "hevc", "color_profile": "SDR",
            "audio_languages": '["eng"]', "has_english_audio": "yes", "audio_profile": "aac 2ch"}


def test_scan_indexes_media_and_sidecars(tmp_path):
    (tmp_path / "Movie.mkv").write_bytes(b"x" * 1000)
    (tmp_path / "Movie.nfo").write_bytes(b"x")
    db = str(tmp_path / "m.db"); init_db(db); conn = get_connection(db)
    stats = scan_and_index(conn, _cfg(str(tmp_path)), probe_fn=_fake_probe)
    assert stats["media_indexed"] == 1
    assert stats["sidecars_tracked"] == 1
    row = get_media_row(conn, str(tmp_path / "Movie.mkv"))
    assert row["video_codec"] == "hevc" and row["has_english_audio"] == "yes"
    assert row["os_hash"] == ""  # under 64KB


def test_rescan_skips_unchanged(tmp_path):
    (tmp_path / "Movie.mkv").write_bytes(b"x" * 1000)
    db = str(tmp_path / "m.db"); init_db(db); conn = get_connection(db)
    scan_and_index(conn, _cfg(str(tmp_path)), probe_fn=_fake_probe)
    stats2 = scan_and_index(conn, _cfg(str(tmp_path)), probe_fn=_fake_probe)
    assert stats2["skipped"] == 1 and stats2["media_indexed"] == 0


def test_inventory_mode_skips_hashing_and_probe(tmp_path):
    (tmp_path / "Movie.mkv").write_bytes(b"x" * 1000)
    db = str(tmp_path / "m.db"); init_db(db); conn = get_connection(db)
    probe_calls = []

    def spy_probe(path, timeout, retries):
        probe_calls.append(path)
        return _fake_probe(path, timeout, retries)

    stats = scan_and_index(conn, _cfg(str(tmp_path)), probe_fn=spy_probe,
                           compute_hashes=False)
    assert stats["media_indexed"] == 1
    assert probe_calls == []  # no ffprobe in inventory mode
    row = get_media_row(conn, str(tmp_path / "Movie.mkv"))
    assert row["fast_hash"] == "" and row["os_hash"] == ""
    assert row["file_size_bytes"] == 1000  # inventory data still captured


def test_scan_skips_unreadable_file(tmp_path, monkeypatch):
    import src.indexer as idx
    (tmp_path / "Good.mkv").write_bytes(b"x" * 100)
    (tmp_path / "Bad.mkv").write_bytes(b"x" * 100)
    db = str(tmp_path / "m.db"); init_db(db); conn = get_connection(db)
    real_getsize = os.path.getsize

    def flaky(p):
        if p.endswith("Bad.mkv"):
            raise FileNotFoundError(p)
        return real_getsize(p)

    monkeypatch.setattr(idx.os.path, "getsize", flaky)
    stats = scan_and_index(conn, _cfg(str(tmp_path)), probe_fn=_fake_probe,
                           compute_hashes=False)
    assert stats["media_indexed"] == 1
    assert stats["errors"] == 1


def test_progress_cb_called_per_media(tmp_path):
    (tmp_path / "A.mkv").write_bytes(b"x" * 1000)
    (tmp_path / "B.mkv").write_bytes(b"y" * 1000)
    db = str(tmp_path / "m.db"); init_db(db); conn = get_connection(db)
    seen = []
    scan_and_index(conn, _cfg(str(tmp_path)), probe_fn=_fake_probe,
                   progress_cb=lambda n, p: seen.append((n, p)))
    assert [n for n, _ in seen] == [1, 2]
