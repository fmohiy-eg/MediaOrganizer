"""PC-side catalog sync helpers.

find_missing: check a list of catalog paths for on-disk existence in parallel
(SMB stat calls are I/O-bound, so threads help a lot) and return the ones that no
longer exist — the deletion half of a sync, done from the PC without SSH.
"""
from concurrent.futures import ThreadPoolExecutor


def find_missing(paths, exists_local, max_workers=16, progress=None):
    """`exists_local(path)` -> bool tells whether the (locally-reachable) file exists.
    Returns paths whose file is gone, preserving input order. Calls
    `progress(done, total)` after each check if given."""
    paths = list(paths)
    total = len(paths)
    missing = []
    done = 0
    with ThreadPoolExecutor(max_workers=max(1, max_workers)) as ex:
        for path, present in ex.map(lambda p: (p, exists_local(p)), paths):
            done += 1
            if not present:
                missing.append(path)
            if progress:
                progress(done, total)
    return missing
