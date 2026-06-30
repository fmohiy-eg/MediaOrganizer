"""One-time migration: rewrite catalog rows that were repointed to SMB backslash
paths (by older Fix/Move-to-Arabic flows) back to the uniform NAS /share style.

Background: the catalog stores NAS paths (`/share/Movies/...`). Before the
to_nas_path fix, `relocate_execute`/`arabic_move` built destinations from the PC
config's SMB `media_paths` and stored those backslash paths verbatim, mixing path
styles. A future scan_live.py would then re-add the `/share/...` form as a
duplicate row. This rewrites only the stored `filepath`/`filename`/
`parent_directory` strings — no files are moved, and it is reversible.

Usage:
    python migrate_path_style.py [config.yaml]            # dry-run (default)
    python migrate_path_style.py config.yaml --apply      # commit changes

Safe to re-run: rows already in NAS form (no path_map prefix matches) are skipped.
"""
import posixpath
import sys

from src.config import load_config
from src.database import get_connection, db_write_lock
from src.web.subtitle_fetch import to_nas_path


def plan_migration(conn, path_map):
    """Return [(old_filepath, new_filepath), ...] for rows to_nas_path would change."""
    changes = []
    for (old,) in conn.execute(
            "SELECT filepath FROM media_files WHERE instr(filepath, char(92)) > 0"):
        new = to_nas_path(old, path_map)
        if new != old:
            changes.append((old, new))
    return changes


def apply_migration(conn, changes):
    with db_write_lock:
        for old, new in changes:
            conn.execute(
                "UPDATE media_files SET filepath = ?, filename = ?, parent_directory = ? "
                "WHERE filepath = ?",
                (new, posixpath.basename(new), posixpath.dirname(new), old))
        conn.commit()


def main(config_path="config.yaml", apply=False):
    cfg = load_config(config_path)
    conn = get_connection(cfg["database_path"])
    path_map = cfg.get("path_map", {})
    if not path_map:
        print("No path_map configured; nothing to migrate.")
        return

    changes = plan_migration(conn, path_map)
    print(f"{len(changes)} row(s) would be rewritten to NAS-style paths.")
    for old, new in changes[:10]:
        print(f"  {old}\n    -> {new}")
    if len(changes) > 10:
        print(f"  ... and {len(changes) - 10} more")

    if not changes:
        return
    if not apply:
        print("\nDry-run (default). Re-run with --apply to commit.")
        return

    apply_migration(conn, changes)
    print(f"\nApplied: {len(changes)} row(s) rewritten.")


if __name__ == "__main__":
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    apply = "--apply" in sys.argv[1:]
    main(args[0] if args else "config.yaml", apply=apply)
