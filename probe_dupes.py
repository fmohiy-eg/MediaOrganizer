"""Probe stream details (runtime, resolution, codec, audio languages) and store them
in the catalog. Covers BOTH:
  - every file in a duplicate group  -> the Duplicates same/different-runtime split, and
  - every movie file                 -> the Arabic-audio feature (audio_languages).
Run on the PC (uses the local ffprobe over SMB via path_map).

Usage:
    python probe_dupes.py [config.yaml] [limit]

Only files without a stored runtime are touched, so it resumes safely after a stop.
"""
import sys
import time

from src.config import load_config
from src.database import get_connection
from src.repository import update_stream_fields
from src.web.services import probe_targets
from src.web.subtitle_fetch import to_local_path
from src.probe import probe_streams


def main(config_path="config.yaml", limit=None):
    cfg = load_config(config_path)
    conn = get_connection(cfg["database_path"])
    pm = cfg.get("path_map", {})
    binary = cfg["ffprobe"].get("binary", "ffprobe")

    target = probe_targets(conn)   # dup-group files + movies, minus DVD VIDEO_TS fragments
    already_probed = {r["filepath"] for r in conn.execute(
        "SELECT filepath FROM media_files WHERE duration_ms IS NOT NULL")}
    todo = sorted(target - already_probed)
    if limit:
        todo = todo[:int(limit)]
    print(f"{len(todo)} files to probe (movies + duplicate-group files, "
          f"excl. DVD VIDEO_TS fragments)...", flush=True)

    ok = fail = 0
    start = time.time()
    for i, fp in enumerate(todo, 1):
        probed = probe_streams(to_local_path(fp, pm), 30, 1, binary)
        if probed and probed.get("duration_ms"):
            update_stream_fields(conn, fp, probed)
            ok += 1
        else:
            fail += 1
        if i % 25 == 0 or i == len(todo):
            rate = i / (time.time() - start)
            eta = (len(todo) - i) / rate / 60 if rate else 0
            print(f"[{i}/{len(todo)}] probed={ok} failed={fail} "
                  f"({rate:.1f}/s, ~{eta:.0f} min left)", flush=True)

    print(f"\nDone — probed {ok}, failed {fail}. Reload the dashboard to see the split.",
          flush=True)


if __name__ == "__main__":
    main(*sys.argv[1:])
