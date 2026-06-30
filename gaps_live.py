"""Fetch each matched TV series' full episode list from TVDB and cache it.

Usage:
    python gaps_live.py [config.yaml] [limit]

Populates metadata_cache.episode_map for every series with a `tvdb:` id, so the
dashboard's Missing-Episodes view works offline afterward. Runs locally (network +
DB only); no media files are touched. Already-cached series are skipped.
"""
import json
import sys
import time

from src.config import load_config
from src.database import get_connection
from src.parsing import parse_path
from src.metadata_client import TvdbClient
from src.metadata_repository import cache_metadata, get_cached_metadata


def _series_title(conn, sid):
    row = conn.execute(
        "SELECT filepath FROM media_files WHERE metadata_id = ? LIMIT 1", (sid,)).fetchone()
    if row:
        return parse_path(row["filepath"]).get("series_title") or sid
    return sid


def main(config_path="config.yaml", limit=None):
    cfg = load_config(config_path)
    conn = get_connection(cfg["database_path"])
    tvdb = TvdbClient(cfg["api_keys"]["tvdb"])

    sids = [r["metadata_id"] for r in conn.execute(
        "SELECT DISTINCT metadata_id FROM media_files WHERE metadata_id LIKE 'tvdb:%'")]
    if limit:
        sids = sids[:int(limit)]
    print(f"{len(sids)} TV series with a TVDB id...", flush=True)

    fetched = cached = failed = 0
    start = time.time()
    for i, sid in enumerate(sids, 1):
        existing = get_cached_metadata(conn, sid)
        if existing and existing["episode_map"]:
            cached += 1
        else:
            try:
                eps = tvdb.get_episodes(sid.split(":")[1])
                cache_metadata(conn, sid, _series_title(conn, sid),
                               episode_map=json.dumps(eps))
                fetched += 1
            except Exception:
                failed += 1
        if i % 25 == 0 or i == len(sids):
            rate = i / (time.time() - start)
            print(f"[{i}/{len(sids)}] fetched={fetched} cached={cached} "
                  f"failed={failed} ({rate:.1f}/s)", flush=True)

    print(f"\nDone — fetched {fetched}, already-cached {cached}, failed {failed}.", flush=True)


if __name__ == "__main__":
    main(*sys.argv[1:])
