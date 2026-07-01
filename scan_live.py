"""Observable inventory scan runner — fast catalog pass with live progress.

Usage:
    python scan_live.py [config.yaml]

Inventory mode: records path/size/name/season-episode/sidecars for every file
by reading directory listings only (no per-file byte reads), so it finishes in
minutes even on huge libraries. Fingerprint hashing is a separate later pass.
Prints "[n/total] path" per indexed file (flushed). Read-only on media; writes
only the local database.
"""
import os
import sys
import time

from src.config import load_config_or_exit
from src.database import init_db, get_connection
from src.scanner import discover
from src.indexer import scan_and_index


def main(config_path="config.yaml"):
    config = load_config_or_exit(config_path)
    init_db(config["database_path"])
    conn = get_connection(config["database_path"])

    print("Counting media files (skips .trickplay)...", flush=True)
    exts = config["scan"]["valid_extensions"]
    total = sum(1 for kind, _ in discover(config["media_paths"], exts) if kind == "media")
    print(f"Found {total} media files. Cataloging (inventory mode, no byte reads)...",
          flush=True)

    start = time.time()

    def progress(n, path):
        elapsed = time.time() - start
        rate = n / elapsed if elapsed else 0
        if n % 50 == 0 or n == total:
            print(f"[{n}/{total}] {rate:.0f}/s  {os.path.basename(path)}", flush=True)

    stats = scan_and_index(conn, config, progress_cb=progress, compute_hashes=False)
    print(f"\nDone in {time.time() - start:.0f}s — "
          f"indexed {stats['media_indexed']}, sidecars {stats['sidecars_tracked']}, "
          f"skipped {stats['skipped']}, errors {stats['errors']}.", flush=True)


if __name__ == "__main__":
    main(sys.argv[1] if len(sys.argv) > 1 else "config.yaml")
