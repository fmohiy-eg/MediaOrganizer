from src.database import db_write_lock


def cache_metadata(conn, metadata_id, title, release_date=None,
                   theatrical_duration_minutes=None, episode_map=None):
    with db_write_lock:
        conn.execute(
            "INSERT INTO metadata_cache "
            "(metadata_id, title, release_date, theatrical_duration_minutes, episode_map, expires_at) "
            "VALUES (?,?,?,?,?, datetime('now','+30 days')) "
            "ON CONFLICT(metadata_id) DO UPDATE SET title=excluded.title, "
            "release_date=excluded.release_date, "
            "theatrical_duration_minutes=excluded.theatrical_duration_minutes, "
            "episode_map=excluded.episode_map, last_updated=CURRENT_TIMESTAMP, "
            "expires_at=datetime('now','+30 days')",
            (metadata_id, title, release_date, theatrical_duration_minutes, episode_map))
        conn.commit()


def get_cached_metadata(conn, metadata_id):
    return conn.execute("SELECT * FROM metadata_cache WHERE metadata_id = ?",
                        (metadata_id,)).fetchone()


def set_match(conn, filepath, metadata_id, status):
    with db_write_lock:
        conn.execute("UPDATE media_files SET metadata_id = ?, match_status = ? WHERE filepath = ?",
                     (metadata_id, status, filepath))
        conn.commit()


def unmatched_items(conn):
    return conn.execute(
        "SELECT * FROM media_files WHERE match_status IN ('unmatched','ambiguous')").fetchall()
