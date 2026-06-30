import os
import sqlite3
import threading

db_write_lock = threading.Lock()

SCHEMA = """
CREATE TABLE IF NOT EXISTS media_files (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    filepath TEXT UNIQUE NOT NULL,
    filename TEXT NOT NULL,
    extension TEXT NOT NULL,
    parent_directory TEXT NOT NULL,
    file_size_bytes INTEGER NOT NULL,
    fast_hash TEXT NOT NULL,
    full_hash TEXT,
    os_hash TEXT NOT NULL,
    duration_ms INTEGER,
    bitrate INTEGER,
    resolution_width INTEGER,
    resolution_height INTEGER,
    video_codec TEXT,
    color_profile TEXT,
    audio_languages TEXT,
    has_english_audio TEXT,
    audio_profile TEXT,
    metadata_id TEXT,
    match_status TEXT,
    item_type TEXT CHECK(item_type IN ('movie', 'episode')),
    season_number INTEGER,
    episode_number INTEGER,
    episode_number_end INTEGER,
    last_scanned TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
CREATE TABLE IF NOT EXISTS external_subtitles (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    media_file_id INTEGER NOT NULL,
    filepath TEXT UNIQUE NOT NULL,
    language_tag TEXT,
    is_sdh INTEGER DEFAULT 0,
    is_forced INTEGER DEFAULT 0,
    FOREIGN KEY(media_file_id) REFERENCES media_files(id) ON DELETE CASCADE
);
CREATE TABLE IF NOT EXISTS sidecar_assets (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    media_file_id INTEGER NOT NULL,
    asset_path TEXT UNIQUE NOT NULL,
    asset_type TEXT CHECK(asset_type IN ('nfo', 'trickplay_dir', 'artwork', 'subtitle', 'scene_junk')),
    FOREIGN KEY(media_file_id) REFERENCES media_files(id) ON DELETE CASCADE
);
CREATE TABLE IF NOT EXISTS metadata_cache (
    metadata_id TEXT PRIMARY KEY,
    title TEXT NOT NULL,
    release_date TEXT,
    theatrical_duration_minutes INTEGER,
    episode_map TEXT,
    last_updated TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    expires_at TIMESTAMP
);

-- Indexes for the correlated lookups the audit/subtitle queries run at scale.
CREATE INDEX IF NOT EXISTS idx_sidecar_media ON sidecar_assets(media_file_id);
CREATE INDEX IF NOT EXISTS idx_subtitle_media ON external_subtitles(media_file_id);
CREATE INDEX IF NOT EXISTS idx_media_metadata ON media_files(metadata_id);
CREATE INDEX IF NOT EXISTS idx_media_parent ON media_files(parent_directory);
"""


def get_connection(db_path):
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    conn.execute("PRAGMA journal_mode = WAL")
    # Multiple processes (dashboard + detached probe/sync) write this DB; wait for a
    # lock instead of failing immediately with "database is locked".
    conn.execute("PRAGMA busy_timeout = 5000")
    return conn


def init_db(db_path):
    parent = os.path.dirname(db_path)
    if parent:
        os.makedirs(parent, exist_ok=True)
    conn = get_connection(db_path)
    try:
        with db_write_lock:
            conn.executescript(SCHEMA)
            conn.commit()
    finally:
        conn.close()
