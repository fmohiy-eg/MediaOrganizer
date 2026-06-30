"""Prune catalog rows whose media file no longer exists on disk — the removal half
of a full sync (scan_live.py adds/updates; this removes vanished files).

Run where the catalog paths actually resolve on local disk. In the NAS+PC split that
means ON THE NAS (catalog is '/share/...'); on a single-machine setup the catalog
stores the local media_paths, so running it there is correct. Running it on a machine
where the stored paths DON'T resolve (e.g. the PC in a NAS split, which only reaches
files over SMB via path_map) would see every path as missing and wipe the whole
catalog — which is why it is intentionally NOT wired into the dashboard. The dashboard
Admin "Sync deletions" panel is the path-map-aware equivalent. NAS-safe: no network deps.

Usage:
    python prune_live.py [config.yaml]            # dry-run (default): report only
    python prune_live.py config.yaml --apply      # delete the stale rows

Touches no media files; only deletes DB rows (recover by re-running scan_live.py).
"""
import os
import sys
import time

from src.config import load_config
from src.database import get_connection, db_write_lock
from src.repository import all_media_paths


def find_stale(conn, progress_cb=None):
    """Catalog filepaths whose file is no longer on disk. Returns (stale, total)."""
    paths = all_media_paths(conn)
    stale = []
    for i, path in enumerate(paths, 1):
        if not os.path.exists(path):
            stale.append(path)
        if progress_cb:
            progress_cb(i, len(paths))
    return stale, len(paths)


def delete_rows(conn, paths):
    """Delete the given catalog rows in one transaction. Returns the count."""
    if not paths:
        return 0
    with db_write_lock:
        conn.executemany("DELETE FROM media_files WHERE filepath = ?",
                         [(p,) for p in paths])
        conn.commit()
    return len(paths)


def main(config_path="config.yaml", apply=False):
    cfg = load_config(config_path)
    conn = get_connection(cfg["database_path"])
    start = time.time()
    print("Checking catalog rows against disk...", flush=True)

    def progress(i, total):
        if i % 5000 == 0 or i == total:
            print(f"  checked {i}/{total}...", flush=True)

    stale, total = find_stale(conn, progress_cb=progress)
    print(f"\n{len(stale)} of {total} catalog rows point to files no longer on disk.",
          flush=True)
    for p in stale[:20]:
        print(f"  - {p}", flush=True)
    if len(stale) > 20:
        print(f"  ... and {len(stale) - 20} more", flush=True)

    if not stale:
        print("Catalog is in sync — nothing to prune.", flush=True)
        return
    if not apply:
        print("\nDry-run (default). Re-run with --apply to delete these rows.", flush=True)
        return

    delete_rows(conn, stale)
    print(f"\nPruned {len(stale)} stale row(s) in {time.time() - start:.0f}s. "
          f"Re-copy the catalog to the laptop.", flush=True)


if __name__ == "__main__":
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    apply = "--apply" in sys.argv[1:]
    main(args[0] if args else "config.yaml", apply=apply)
