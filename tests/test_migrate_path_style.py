from src.database import init_db, get_connection
from src.repository import upsert_media_file, get_media_row
from migrate_path_style import plan_migration, apply_migration

PM = {"/share/TV Shows": r"\\nas\TV Shows", "/share/Movies": r"\\nas\Movies"}


def _add(conn, filepath):
    upsert_media_file(conn, dict(
        filepath=filepath, filename=filepath.split("/")[-1].split("\\")[-1],
        extension=".mkv", parent_directory="x",
        file_size_bytes=1, fast_hash="fh", os_hash="oh"))


def test_plan_only_targets_backslash_rows(tmp_path):
    db = str(tmp_path / "m.db"); init_db(db); conn = get_connection(db)
    smb = r"\\nas\Movies\01-Ready/02-ArabicReady/Heat (1995)/Heat (1995).mkv"
    nas = "/share/TV Shows/01-Ready/Show/ep.mkv"
    _add(conn, smb)
    _add(conn, nas)
    changes = plan_migration(conn, PM)
    assert changes == [(smb, "/share/Movies/01-Ready/02-ArabicReady/Heat (1995)/Heat (1995).mkv")]


def test_apply_rewrites_filepath_filename_and_parent(tmp_path):
    db = str(tmp_path / "m.db"); init_db(db); conn = get_connection(db)
    smb = r"\\nas\Movies\01-Ready/02-ArabicReady/Heat (1995)/Heat (1995).mkv"
    _add(conn, smb)
    apply_migration(conn, plan_migration(conn, PM))
    new = "/share/Movies/01-Ready/02-ArabicReady/Heat (1995)/Heat (1995).mkv"
    row = get_media_row(conn, new)
    assert row is not None
    assert get_media_row(conn, smb) is None
    assert row["filename"] == "Heat (1995).mkv"
    assert row["parent_directory"] == "/share/Movies/01-Ready/02-ArabicReady/Heat (1995)"


def test_idempotent_rerun_is_noop(tmp_path):
    db = str(tmp_path / "m.db"); init_db(db); conn = get_connection(db)
    _add(conn, r"\\nas\Movies\01-Ready/X/X.mkv")
    apply_migration(conn, plan_migration(conn, PM))
    assert plan_migration(conn, PM) == []
