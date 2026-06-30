import struct
import pytest


@pytest.fixture
def write_binary(tmp_path):
    """Return a factory that writes `size` bytes (repeating pattern) to a file and returns its path."""
    def _make(name, size, fill=b"\x01"):
        p = tmp_path / name
        p.write_bytes((fill * size)[:size])
        return str(p)
    return _make


@pytest.fixture
def write_os_hash_file(tmp_path):
    """Write a file whose 8-byte little-endian longs are all `value`, for deterministic os_hash tests."""
    def _make(name, total_bytes, value=1):
        p = tmp_path / name
        longs = total_bytes // 8
        p.write_bytes(struct.pack("<%dq" % longs, *([value] * longs)))
        return str(p)
    return _make
