import os
from src.repository import all_media_paths, delete_media_by_path


def prune_stale(conn):
    removed = 0
    for path in all_media_paths(conn):
        if not os.path.exists(path):
            delete_media_by_path(conn, path)
            removed += 1
    return removed
