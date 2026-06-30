import hashlib
import os
import struct
import pytest
from src.hashing import compute_fast_hash, compute_full_hash, compute_os_hash


def test_small_file_fast_hash_equals_full_sha256(write_binary):
    path = write_binary("small.bin", 1000)
    expected = hashlib.sha256(b"\x01" * 1000).hexdigest()
    assert compute_fast_hash(path, threshold=20_000_000, chunk_size=10) == expected


def test_large_file_fast_hash_uses_head_and_tail(write_binary):
    # threshold tiny so the file counts as "large"; chunk_size=4
    path = write_binary("big.bin", 100, fill=b"\x01")
    with open(path, "rb") as f:
        head = f.read(4)
        f.seek(-4, os.SEEK_END)
        tail = f.read(4)
    expected = hashlib.sha256(head + tail).hexdigest()
    assert compute_fast_hash(path, threshold=10, chunk_size=4) == expected


def test_full_hash_matches_hashlib(write_binary):
    path = write_binary("f.bin", 5000)
    assert compute_full_hash(path) == hashlib.sha256(b"\x01" * 5000).hexdigest()


def test_os_hash_known_value(write_os_hash_file):
    # 128KB of 8-byte longs all = 1. Each 64KB region has 8192 longs.
    # h = filesize + sum(head longs) + sum(tail longs)
    size = 128 * 1024
    path = write_os_hash_file("os.bin", size, value=1)
    longs_per_chunk = (64 * 1024) // 8
    expected_int = (size + longs_per_chunk + longs_per_chunk) & 0xFFFFFFFFFFFFFFFF
    assert compute_os_hash(path) == f"{expected_int:016x}"


def test_os_hash_rejects_tiny_file(write_binary):
    path = write_binary("tiny.bin", 100)
    with pytest.raises(ValueError):
        compute_os_hash(path)
