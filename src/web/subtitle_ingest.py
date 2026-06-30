import os


def collision_safe_path(target, exists_fn):
    if not exists_fn(target):
        return target
    base, ext = os.path.splitext(target)
    i = 1
    while True:
        candidate = f"{base}.{i}{ext}"
        if not exists_fn(candidate):
            return candidate
        i += 1
