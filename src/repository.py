from src.database import db_write_lock

_REQUIRED = ("filepath", "filename", "extension", "parent_directory",
             "file_size_bytes", "fast_hash", "os_hash")


def upsert_media_file(conn, record):
    for key in _REQUIRED:
        if key not in record:
            raise ValueError(f"record missing required field: {key}")
    cols = list(record.keys())
    placeholders = ",".join("?" for _ in cols)
    updates = ",".join(f"{c}=excluded.{c}" for c in cols if c != "filepath")
    sql = (f"INSERT INTO media_files ({','.join(cols)}) VALUES ({placeholders}) "
           f"ON CONFLICT(filepath) DO UPDATE SET {updates}")
    with db_write_lock:
        conn.execute(sql, [record[c] for c in cols])
        conn.commit()
    return get_media_row(conn, record["filepath"])["id"]


def get_media_row(conn, filepath):
    return conn.execute("SELECT * FROM media_files WHERE filepath = ?", (filepath,)).fetchone()


def add_sidecar(conn, media_id, asset_path, asset_type):
    with db_write_lock:
        conn.execute(
            "INSERT OR IGNORE INTO sidecar_assets (media_file_id, asset_path, asset_type) "
            "VALUES (?,?,?)", (media_id, asset_path, asset_type))
        conn.commit()


def all_media_paths(conn):
    return [r["filepath"] for r in conn.execute("SELECT filepath FROM media_files")]


_STREAM_COLS = ("duration_ms", "bitrate", "resolution_width", "resolution_height",
                "video_codec", "color_profile", "audio_languages", "has_english_audio",
                "audio_profile", "subtitle_languages", "has_embedded_english_subtitle")


def update_stream_fields(conn, filepath, probed):
    """Store ffprobe results (only the columns the schema has) onto a media row."""
    cols = [c for c in _STREAM_COLS if c in probed]
    if not cols:
        return
    sql = "UPDATE media_files SET " + ", ".join(f"{c} = ?" for c in cols) + " WHERE filepath = ?"
    with db_write_lock:
        conn.execute(sql, [probed[c] for c in cols] + [filepath])
        conn.commit()


def update_media_path(conn, old_path, new_path, metadata_id=None, match_status="matched"):
    import os
    with db_write_lock:
        conn.execute(
            "UPDATE media_files SET filepath = ?, filename = ?, parent_directory = ?, "
            "metadata_id = COALESCE(?, metadata_id), match_status = ? WHERE filepath = ?",
            (new_path, os.path.basename(new_path), os.path.dirname(new_path),
             metadata_id, match_status, old_path))
        conn.commit()


def delete_media_by_path(conn, filepath):
    with db_write_lock:
        conn.execute("DELETE FROM media_files WHERE filepath = ?", (filepath,))
        conn.commit()
