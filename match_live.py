"""Observable metadata-matching runner.

Usage:
    python match_live.py [config.yaml] [limit]

Matches each DISTINCT title once (movies via TMDB, series via TVDB) and applies
the result to every file sharing that identity, so ~6k lookups cover ~57k files.
Ambiguous/failed matches are flagged for manual review, never guessed. Writes
metadata_id + match_status into the database; no media files are touched.
"""
import collections
import sys
import time

from src.config import load_config_or_exit
from src.database import get_connection
from src.parsing import parse_path
from src.matcher import decide_match
from src.metadata_client import TmdbClient, TvdbClient
from src.metadata_repository import set_match, cache_metadata
from src.repository import all_media_paths


def identity_key(p):
    if p["item_type"] == "movie":
        return ("movie", (p.get("movie_title") or "").lower().strip(), p.get("year"))
    if p["item_type"] == "episode":
        return ("episode", (p.get("series_title") or "").lower().strip(), p.get("year"))
    return None


def _search_with_retry(provider, parsed, retries=2):
    for attempt in range(retries + 1):
        try:
            return provider.search(parsed)
        except Exception:
            if attempt < retries:
                time.sleep(2)
            else:
                return None


def main(config_path="config.yaml", limit=None):
    cfg = load_config_or_exit(config_path)
    conn = get_connection(cfg["database_path"])
    keys = cfg["api_keys"]
    tmdb = TmdbClient(keys["tmdb"])
    tvdb = TvdbClient(keys["tvdb"])

    paths = all_media_paths(conn)
    groups = collections.defaultdict(list)
    rep = {}
    for path in paths:
        p = parse_path(path)
        key = identity_key(p)
        if key is None:
            continue
        groups[key].append(path)
        rep.setdefault(key, p)

    work = list(groups)
    if limit:
        work = work[:int(limit)]
    print(f"{len(groups)} distinct titles across {len(paths)} files; "
          f"matching {len(work)}...", flush=True)

    stats = collections.Counter()
    start = time.time()
    for i, key in enumerate(work, 1):
        p = rep[key]
        provider = tvdb if key[0] == "episode" else tmdb
        cands = _search_with_retry(provider, p) or []
        result = decide_match(cands, p)
        status, mid = result["status"], result["metadata_id"]
        if mid:
            chosen = next((c for c in cands if c["metadata_id"] == mid), None)
            if chosen:
                cache_metadata(conn, mid, chosen.get("title") or key[1],
                               release_date=str(chosen.get("year") or ""))
        for path in groups[key]:
            set_match(conn, path, mid, status)
        stats[status] += 1
        if i % 50 == 0 or i == len(work):
            rate = i / (time.time() - start)
            print(f"[{i}/{len(work)}] {rate:.0f}/s  "
                  f"matched={stats['matched']} ambiguous={stats['ambiguous']} "
                  f"unmatched={stats['unmatched']}", flush=True)

    print(f"\nDone — {dict(stats)} over {len(work)} titles.", flush=True)


if __name__ == "__main__":
    cfg = sys.argv[1] if len(sys.argv) > 1 else "config.yaml"
    lim = sys.argv[2] if len(sys.argv) > 2 else None
    main(cfg, lim)
