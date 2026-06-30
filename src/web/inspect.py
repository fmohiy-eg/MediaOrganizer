"""Helpers for inspecting a duplicate group's real stream metadata before deletion.

The key safety check: copies whose runtimes differ, or whose names carry an edition
marker (Director's Cut, Extended...), are probably DIFFERENT versions — not
duplicates — and must not be auto-suggested for removal (spec Release Protection).
"""


from src.audit.contamination import normalize_title


def title_mismatch(filename_title, container_title):
    """True when the file's embedded container title clearly differs from the name
    parsed from its filename — a strong hint the file is mislabeled."""
    a = normalize_title(filename_title or "")
    b = normalize_title(container_title or "")
    if not a or not b:
        return False
    return a not in b and b not in a


def format_duration(ms):
    if not ms:
        return None
    total = int(ms // 1000)
    h, rem = divmod(total, 3600)
    m, s = divmod(rem, 60)
    return f"{h}:{m:02d}:{s:02d}" if h else f"{m}:{s:02d}"


def assess_versions(items, deviation_seconds=120):
    """`items` each have `duration_ms` (may be None) and `edition` (may be None).
    Returns whether the group likely holds different versions, with a reason."""
    editions = sorted({it["edition"] for it in items if it.get("edition")})
    durations = [it["duration_ms"] for it in items if it.get("duration_ms")]
    if editions:
        return {"possible_versions": True,
                "reason": "Edition marker(s): " + ", ".join(editions)}
    if len(durations) >= 2:
        spread = (max(durations) - min(durations)) / 1000.0
        if spread >= deviation_seconds:
            mins = spread / 60.0
            return {"possible_versions": True,
                    "reason": f"Runtimes differ by {mins:.1f} min — possibly different cuts"}
        return {"possible_versions": False,
                "reason": "Runtimes match — looks like true duplicates"}
    if not durations:
        return {"possible_versions": False,
                "reason": "Could not read runtimes (probe failed) — verify manually"}
    return {"possible_versions": False,
            "reason": "Some copies could not be probed — runtimes incomplete"}
