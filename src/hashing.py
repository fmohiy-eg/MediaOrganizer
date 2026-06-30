import hashlib
import os
import struct

_OS_CHUNK = 64 * 1024
_MASK = 0xFFFFFFFFFFFFFFFF


def compute_fast_hash(filepath, threshold, chunk_size):
    size = os.path.getsize(filepath)
    if size <= threshold:
        with open(filepath, "rb") as f:
            return hashlib.sha256(f.read()).hexdigest()
    with open(filepath, "rb") as f:
        head = f.read(chunk_size)
        f.seek(-chunk_size, os.SEEK_END)
        tail = f.read(chunk_size)
    return hashlib.sha256(head + tail).hexdigest()


def compute_full_hash(filepath):
    h = hashlib.sha256()
    with open(filepath, "rb") as f:
        for block in iter(lambda: f.read(1024 * 1024), b""):
            h.update(block)
    return h.hexdigest()


def compute_os_hash(filepath):
    size = os.path.getsize(filepath)
    if size < _OS_CHUNK:
        raise ValueError(f"File too small for os_hash (<64KB): {filepath}")
    h = size
    fmt = "<%dq" % (_OS_CHUNK // 8)
    with open(filepath, "rb") as f:
        for val in struct.unpack(fmt, f.read(_OS_CHUNK)):
            h = (h + val) & _MASK
        f.seek(size - _OS_CHUNK, os.SEEK_SET)
        for val in struct.unpack(fmt, f.read(_OS_CHUNK)):
            h = (h + val) & _MASK
    return f"{h:016x}"
