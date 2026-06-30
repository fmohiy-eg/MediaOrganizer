import os

_SUBTITLE_EXTS = {".srt", ".ass", ".sub", ".ssa"}
_ARTWORK_EXTS = {".jpg", ".jpeg", ".png"}


def _is_system_dir(name):
    """QNAP/NAS internal dirs to skip entirely (thumbnails, recycle, snapshots, etc.)."""
    return name.startswith("@") or name.startswith(".@") or name.lower() == ".streams"


def _components(path):
    return path.replace("\\", "/").split("/")


def _has_trickplay_component(path):
    return any(part.lower().endswith(".trickplay") for part in _components(path))


def _in_system_dir(path):
    return any(_is_system_dir(part) for part in _components(path))


def classify_path(path, valid_extensions):
    if _in_system_dir(path):
        return "ignore"
    if _has_trickplay_component(path):
        return "trickplay_dir"
    ext = os.path.splitext(path)[1].lower()
    if ext in {e.lower() for e in valid_extensions}:
        return "media"
    if ext == ".nfo":
        return "nfo"
    if ext in _SUBTITLE_EXTS:
        return "subtitle"
    if ext in _ARTWORK_EXTS:
        return "artwork"
    return "ignore"


def discover(media_paths, valid_extensions):
    for root in media_paths:
        for dirpath, dirnames, filenames in os.walk(root):
            # Prune NAS-internal dirs entirely (don't descend, don't yield).
            dirnames[:] = [d for d in dirnames if not _is_system_dir(d)]
            # Yield each .trickplay dir once, then prune it from descent.
            trick = [d for d in dirnames if d.lower().endswith(".trickplay")]
            for d in trick:
                yield ("trickplay_dir", os.path.join(dirpath, d))
            dirnames[:] = [d for d in dirnames if not d.lower().endswith(".trickplay")]
            for name in filenames:
                full = os.path.join(dirpath, name)
                kind = classify_path(full, valid_extensions)
                if kind != "ignore":
                    yield (kind, full)
