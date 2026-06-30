import os
from src.scanner import discover
from src.hashing import compute_fast_hash, compute_os_hash
from src.probe import probe_streams
from src.repository import upsert_media_file, get_media_row
from src.database import db_write_lock

_OS_MIN = 64 * 1024


def scan_and_index(conn, config, probe_fn=probe_streams, progress_cb=None,
                   compute_hashes=True):
    exts = config["scan"]["valid_extensions"]
    threshold = config["hashing"]["partial_hash_threshold_bytes"]
    chunk = config["hashing"]["partial_chunk_bytes"]
    timeout = config["ffprobe"]["timeout_seconds"]
    retries = config["ffprobe"]["retries"]

    stats = {"media_indexed": 0, "sidecars_tracked": 0, "skipped": 0, "errors": 0}
    pending_sidecars = []  # (parent_dir, path, asset_type)
    dir_to_media_id = {}   # parent_directory -> a media_file id (best-effort, last wins)

    for kind, path in discover(config["media_paths"], exts):
        if kind == "media":
            try:
                size = os.path.getsize(path)
                existing = get_media_row(conn, path)
                if existing and existing["file_size_bytes"] == size:
                    stats["skipped"] += 1
                    dir_to_media_id[os.path.dirname(path)] = existing["id"]
                    continue
                # Inventory mode (compute_hashes=False) skips byte reads entirely —
                # no fingerprint hashing and no ffprobe — for a fast catalog pass.
                if compute_hashes:
                    fast_hash = compute_fast_hash(path, threshold, chunk)
                    os_hash = compute_os_hash(path) if size >= _OS_MIN else ""
                    probed = probe_fn(path, timeout, retries)
                else:
                    fast_hash = ""
                    os_hash = ""
                    probed = None
                record = {
                    "filepath": path,
                    "filename": os.path.basename(path),
                    "extension": os.path.splitext(path)[1].lower(),
                    "parent_directory": os.path.dirname(path),
                    "file_size_bytes": size,
                    "fast_hash": fast_hash,
                    "os_hash": os_hash,
                }
                if probed:
                    record.update(probed)
                media_id = upsert_media_file(conn, record)
                dir_to_media_id[record["parent_directory"]] = media_id
                stats["media_indexed"] += 1
                if progress_cb:
                    progress_cb(stats["media_indexed"], path)
            except OSError:
                # A vanished/unreadable file must not abort a large scan.
                stats["errors"] += 1
                continue
        else:
            pending_sidecars.append((os.path.dirname(path), path, kind))

    # Link sidecars to a media file in the same directory (best-effort), batched
    # into a single transaction — an in-memory dir->id map avoids a query per file.
    rows = [(dir_to_media_id[parent_dir], path, asset_type)
            for parent_dir, path, asset_type in pending_sidecars
            if parent_dir in dir_to_media_id]
    if rows:
        with db_write_lock:
            conn.executemany(
                "INSERT OR IGNORE INTO sidecar_assets "
                "(media_file_id, asset_path, asset_type) VALUES (?,?,?)", rows)
            conn.commit()
    stats["sidecars_tracked"] = len(rows)
    return stats
