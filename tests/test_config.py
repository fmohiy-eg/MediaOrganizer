import pytest
from src.config import load_config, ConfigError, DEFAULTS


def _write(tmp_path, text):
    p = tmp_path / "config.yaml"
    p.write_text(text)
    return str(p)


def test_user_values_override_defaults(tmp_path):
    cfg_path = _write(tmp_path, "media_paths:\n  - /media/Movies\nscan:\n  worker_threads: 8\n")
    cfg = load_config(cfg_path)
    assert cfg["scan"]["worker_threads"] == 8           # overridden
    assert cfg["hashing"]["partial_chunk_bytes"] == DEFAULTS["hashing"]["partial_chunk_bytes"]  # default kept
    assert cfg["media_paths"] == ["/media/Movies"]


def test_missing_file_raises(tmp_path):
    with pytest.raises(ConfigError):
        load_config(str(tmp_path / "nope.yaml"))


def test_empty_media_paths_raises(tmp_path):
    cfg_path = _write(tmp_path, "media_paths: []\n")
    with pytest.raises(ConfigError):
        load_config(cfg_path)
