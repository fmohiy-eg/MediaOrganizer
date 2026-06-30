def is_protected(row, theatrical_minutes, deviation_seconds):
    if row.get("edition"):
        return True
    duration_ms = row.get("duration_ms")
    if duration_ms is None or theatrical_minutes is None:
        return False
    file_seconds = duration_ms / 1000.0
    theatrical_seconds = theatrical_minutes * 60
    return abs(file_seconds - theatrical_seconds) >= deviation_seconds
