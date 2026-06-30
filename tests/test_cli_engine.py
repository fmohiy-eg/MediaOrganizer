import os
from src.database import init_db
from src.repository import upsert_media_file, get_media_row
from src.database import get_connection
import cli_engine


def _config(tmp_path, media_dir):
    return {
        "media_paths": [str(media_dir)],
        "database_path": str(tmp_path / "m.db"),
        "log_directory": str(tmp_path / "logs"),
        "quarantine_path": str(tmp_path / "q" / ".quarantine"),
        "api_keys": {"tmdb": "K", "tvdb": "K"},
        "scan": {"valid_extensions": [".mkv"]},
        "hashing": {"partial_hash_threshold_bytes": 20_000_000, "partial_chunk_bytes": 10_000_000},
        "ffprobe": {"timeout_seconds": 5, "retries": 1},
    }


def test_get_valid_choice_rejects_bad_then_accepts():
    answers = iter(["nine", "0", "8", "3"])
    assert cli_engine.get_valid_choice(lambda _prompt: next(answers)) == 3


def test_scan_then_prune_then_export(tmp_path):
    media = tmp_path / "media"; media.mkdir()
    (media / "Movie (2020).mkv").write_bytes(b"x" * 500)
    cfg = _config(tmp_path, media)
    init_db(cfg["database_path"])

    msg = cli_engine.run_task(1, cfg)          # scan
    assert "Indexed 1 media" in msg

    msg = cli_engine.run_task(6, cfg)          # export
    assert os.path.exists(os.path.join(cfg["log_directory"], "library_report.md"))

    # delete the file on disk, then prune should remove the row
    (media / "Movie (2020).mkv").unlink()
    msg = cli_engine.run_task(4, cfg)          # prune
    assert "Pruned 1" in msg


def test_audit_groups_same_name_variants_not_by_metadata_id(tmp_path):
    # Two formats of one movie in a folder = 1 variant group; two different episodes
    # sharing a series tvdb id must NOT be grouped.
    cfg = _config(tmp_path, tmp_path / "media")
    init_db(cfg["database_path"])
    conn = get_connection(cfg["database_path"])
    base = dict(file_size_bytes=1, fast_hash="h", os_hash="o", metadata_id="tvdb:1")
    upsert_media_file(conn, dict(filepath="/m/Movie.mkv", filename="Movie.mkv",
        extension=".mkv", parent_directory="/m", **base))
    upsert_media_file(conn, dict(filepath="/m/Movie.avi", filename="Movie.avi",
        extension=".avi", parent_directory="/m", **base))
    upsert_media_file(conn, dict(filepath="/s/Show - S01E02.mkv", filename="Show - S01E02.mkv",
        extension=".mkv", parent_directory="/s", **base))
    msg = cli_engine.run_task(3, cfg)
    assert "1 variant conflict group(s)" in msg


def test_validate_reports_missing_path(tmp_path):
    cfg = _config(tmp_path, tmp_path / "does_not_exist")
    msg = cli_engine.run_task(5, cfg)
    assert "not reachable" in msg
