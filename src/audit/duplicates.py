def confirm_exact_duplicates(rows, full_hash_fn):
    by_fast = {}
    for r in rows:
        by_fast.setdefault(r["fast_hash"], []).append(r)

    confirmed = []
    for candidates in by_fast.values():
        if len(candidates) < 2:
            continue  # singleton: never read the full file
        by_full = {}
        for r in candidates:
            fh = full_hash_fn(r["filepath"])
            by_full.setdefault(fh, []).append(r["filepath"])
        for paths in by_full.values():
            if len(paths) >= 2:
                confirmed.append(sorted(paths))
    return confirmed
