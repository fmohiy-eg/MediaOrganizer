import os
import shutil


def _dest_for(source, quarantine_path):
    _drive, rest = os.path.splitdrive(source.replace("\\", "/"))
    rest = rest.lstrip("/")
    return os.path.join(quarantine_path, rest)


def plan_moves(plan, quarantine_path):
    sources = [plan["video"]] + list(plan.get("cascade", []))
    return [(s, _dest_for(s, quarantine_path)) for s in sources]


def execute_plan(plan, quarantine_path, dry_run=True, to_local=None):
    """Move the plan's files into quarantine and return the pairs actually moved.

    `to_local` maps a catalog path (e.g. a NAS '/share/...' path) to a reachable
    local/SMB path; it defaults to identity. The quarantine destination is derived
    from the original catalog path, so the quarantine mirrors the library layout.

    The primary video MUST be reachable — if it isn't, this raises FileNotFoundError
    and moves nothing, so a caller never drops a DB row for a file it didn't actually
    quarantine. Sidecars that are already gone are skipped (not fatal).
    """
    pairs = plan_moves(plan, quarantine_path)
    if dry_run:
        return pairs
    to_local = to_local or (lambda p: p)
    if not pairs:
        return []
    # pairs[0] is the video (plan_moves lists it first); it must exist.
    if not os.path.exists(to_local(pairs[0][0])):
        raise FileNotFoundError(to_local(pairs[0][0]))
    moved = []
    for source, dest in pairs:
        local_src = to_local(source)
        if not os.path.exists(local_src):
            continue  # a sidecar already gone — skip, don't fail the whole delete
        os.makedirs(os.path.dirname(dest), exist_ok=True)
        shutil.move(local_src, dest)
        moved.append((source, dest))
    return moved
