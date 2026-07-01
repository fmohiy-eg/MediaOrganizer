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


def test_load_config_or_exit_exits_cleanly_on_bad_config(tmp_path):
    from src.config import load_config_or_exit
    with pytest.raises(SystemExit) as e:                       # not a raw traceback
        load_config_or_exit(str(tmp_path / "nope.yaml"))
    assert e.value.code == 1


def test_load_config_or_exit_returns_on_good_config(tmp_path):
    from src.config import load_config_or_exit
    cfg_path = _write(tmp_path, "media_paths:\n  - /media/Movies\n")
    assert load_config_or_exit(cfg_path)["media_paths"] == ["/media/Movies"]


def test_env_var_overlays_blank_yaml_api_key(tmp_path, monkeypatch):
    monkeypatch.setenv("TMDB_API_KEY", "from_env")
    cfg_path = _write(tmp_path, "media_paths:\n  - /media/Movies\n")  # blank tmdb key
    cfg = load_config(cfg_path)
    assert cfg["api_keys"]["tmdb"] == "from_env"


def test_dotenv_next_to_config_overlays_key(tmp_path, monkeypatch):
    monkeypatch.delenv("TVDB_API_KEY", raising=False)
    (tmp_path / ".env").write_text("TVDB_API_KEY=from_dotenv\n")
    cfg_path = _write(tmp_path, "media_paths:\n  - /media/Movies\n")
    cfg = load_config(cfg_path)
    assert cfg["api_keys"]["tvdb"] == "from_dotenv"
