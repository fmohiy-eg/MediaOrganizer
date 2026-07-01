"""Populate metadata IDs from Jellyfin/Kodi .nfo sidecars (no API calls).

Usage:
    python read_nfo_ids.py [config.yaml]

Reads each movie folder's movie.nfo (tmdb id) and each series folder's
tvshow.nfo (tvdb id), caching per series, and writes metadata_id +
match_status into the catalog. Runs locally on the NAS; touches no media.
"""
import collections
import os
import sys

from src.config import load_config_or_exit
from src.database import get_connection, db_write_lock
from src.parsing import parse_path
from src.nfo import extract_ids
from src.repository import all_media_paths


def _read(path):
    try:
        with open(path, "r", encoding="utf-8", errors="ignore") as f:
            return f.read()
    except OSError:
        return ""


def _series_folder(path):
    parent = os.path.dirname(path)
    pname = os.path.basename(parent).lower()
    if pname.startswith("season") or pname == "specials":
        return os.path.dirname(parent)
    return parent


def main(config_path="config.yaml"):
    cfg = load_config_or_exit(config_path)
    conn = get_connection(cfg["database_path"])
    paths = all_media_paths(conn)
    total = len(paths)

    series_cache = {}     # series_folder -> 'tvdb:<id>' or None
    updates = []          # (metadata_id, status, filepath)
    stats = collections.Counter()

    for i, path in enumerate(paths, 1):
        p = parse_path(path)
        mid = None
        if p["item_type"] == "movie":
            d = os.path.dirname(path)
            for cand in (os.path.join(d, "movie.nfo"), os.path.splitext(path)[0] + ".nfo"):
                if os.path.isfile(cand):
                    ids = extract_ids(_read(cand))
                    if ids.get("tmdb"):
                        mid = "tmdb:" + ids["tmdb"]
                        break
        elif p["item_type"] == "episode":
            sf = _series_folder(path)
            if sf not in series_cache:
                nfo = os.path.join(sf, "tvshow.nfo")
                ids = extract_ids(_read(nfo)) if os.path.isfile(nfo) else {}
                series_cache[sf] = ("tvdb:" + ids["tvdb"]) if ids.get("tvdb") else None
            mid = series_cache[sf]

        status = "matched" if mid else "unmatched"
        stats[status] += 1
        updates.append((mid, status, path))
        if i % 5000 == 0 or i == total:
            print(f"[{i}/{total}] matched={stats['matched']} "
                  f"unmatched={stats['unmatched']}", flush=True)

    with db_write_lock:
        conn.executemany(
            "UPDATE media_files SET metadata_id = ?, match_status = ? WHERE filepath = ?",
            updates)
        conn.commit()
    print(f"\nDone — {dict(stats)}; {len(series_cache)} series folders read.", flush=True)


if __name__ == "__main__":
    main(sys.argv[1] if len(sys.argv) > 1 else "config.yaml")
