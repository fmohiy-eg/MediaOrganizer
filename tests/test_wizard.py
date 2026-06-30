import yaml
from src.wizard import build_config_dict, run_wizard
from src.config import load_config


# --- build_config_dict (pure) ----------------------------------------------

def test_build_config_single_machine_minimal():
    cfg = build_config_dict({"media_paths": ["/m/Movies", "/m/TV Shows"]})
    assert cfg["media_paths"] == ["/m/Movies", "/m/TV Shows"]
    assert cfg["path_map"] == {}
    assert cfg["ffprobe"]["binary"] == ""
    assert cfg["player"]["binary"] == ""
    assert "audio_flag" not in cfg
    assert "api_keys" not in cfg


def test_build_config_includes_audio_flag_when_languages():
    cfg = build_config_dict({
        "media_paths": ["/m/Movies"],
        "audio_flag": {"languages": ["ara"], "label": "Arabic Audio",
                       "staging_subdir": "02-ArabicReady"},
    })
    assert cfg["audio_flag"]["languages"] == ["ara"]
    assert cfg["audio_flag"]["label"] == "Arabic Audio"


def test_build_config_omits_audio_flag_when_no_languages():
    cfg = build_config_dict({"media_paths": ["/m/Movies"],
                             "audio_flag": {"languages": []}})
    assert "audio_flag" not in cfg


def test_build_config_includes_api_keys_when_provided():
    cfg = build_config_dict({"media_paths": ["/m/Movies"],
                             "api_keys": {"tmdb": "t", "tvdb": "", "opensubtitles": ""}})
    assert cfg["api_keys"]["tmdb"] == "t"
    assert cfg["api_keys"]["opensubtitles"]["api_key"] == ""


def test_build_config_is_loadable(tmp_path):
    cfg = build_config_dict({"media_paths": ["/m/Movies", "/m/TV Shows"]})
    p = tmp_path / "config.yaml"
    p.write_text(yaml.safe_dump(cfg))
    loaded = load_config(str(p))           # must not raise
    assert loaded["media_paths"] == ["/m/Movies", "/m/TV Shows"]


# --- run_wizard (I/O orchestration, fully injected) ------------------------

def _runner(answers):
    """Build an input_fn that yields the queued answers in order."""
    it = iter(answers)
    return lambda prompt="": next(it)


def test_run_wizard_single_machine_writes_loadable_config(tmp_path):
    written = {}
    inputs = [
        "1",                       # mode: single
        "/m/Movies",               # movies folder
        "/m/TV Shows",             # tv folder
        "",                        # ffprobe: auto-detect
        "",                        # player: auto-detect
        "n",                       # store api keys in config? no
        "n",                       # enable audio flagging? no
        "",                        # database path (default)
        "",                        # quarantine path (default)
        "",                        # log folder (default)
    ]
    cfg = run_wizard(
        input_fn=_runner(inputs),
        exists_fn=lambda p: True,
        isfile_fn=lambda p: False,         # config.yaml does not exist yet
        which_fn=lambda n: None,
        write_fn=lambda path, text: written.update({"path": path, "text": text}),
        platform_name="linux",
        env={},
        config_path=str(tmp_path / "config.yaml"),
    )
    assert cfg["media_paths"] == ["/m/Movies", "/m/TV Shows"]
    assert cfg["path_map"] == {}
    # the written YAML round-trips through load_config
    (tmp_path / "config.yaml").write_text(written["text"])
    assert load_config(written["path"])["media_paths"] == ["/m/Movies", "/m/TV Shows"]


def test_run_wizard_split_builds_path_map(tmp_path):
    written = {}
    inputs = [
        "2",                                  # mode: split
        r"\\nas\Movies",                      # movies folder (SMB)
        r"\\nas\TV Shows",                    # tv folder (SMB)
        "/share/Movies",                      # movies NAS prefix
        "/share/TV Shows",                    # tv NAS prefix
        "",                                   # ffprobe auto
        "",                                   # player auto
        "n",                                  # api keys no
        "n",                                  # audio flag no
        "", "", "",                           # db/quar/log defaults
    ]
    cfg = run_wizard(
        input_fn=_runner(inputs),
        exists_fn=lambda p: True,
        isfile_fn=lambda p: False,
        which_fn=lambda n: None,
        write_fn=lambda path, text: written.update({"text": text}),
        platform_name="win32",
        env={},
        config_path=str(tmp_path / "config.yaml"),
    )
    assert cfg["path_map"] == {"/share/Movies": r"\\nas\Movies",
                               "/share/TV Shows": r"\\nas\TV Shows"}


def test_run_wizard_enables_audio_flag(tmp_path):
    inputs = [
        "1", "/m/Movies", "/m/TV Shows", "", "",
        "n",                       # api keys no
        "y",                       # enable audio flagging
        "ara, ar",                 # languages
        "Arabic Audio",            # label
        "02-ArabicReady",          # staging subdir
        "", "", "",                # db/quar/log
    ]
    cfg = run_wizard(
        input_fn=_runner(inputs), exists_fn=lambda p: True, isfile_fn=lambda p: False,
        which_fn=lambda n: None, write_fn=lambda path, text: None,
        platform_name="linux", env={}, config_path=str(tmp_path / "config.yaml"),
    )
    assert cfg["audio_flag"]["languages"] == ["ara", "ar"]
    assert cfg["audio_flag"]["label"] == "Arabic Audio"
    assert cfg["audio_flag"]["staging_subdir"] == "02-ArabicReady"


def test_run_wizard_refuses_overwrite(tmp_path):
    calls = []
    inputs = ["n"]                 # overwrite existing config.yaml? no
    cfg = run_wizard(
        input_fn=_runner(inputs), exists_fn=lambda p: True,
        isfile_fn=lambda p: True,  # config.yaml ALREADY exists
        which_fn=lambda n: None,
        write_fn=lambda path, text: calls.append(path),
        platform_name="linux", env={}, config_path=str(tmp_path / "config.yaml"),
    )
    assert cfg is None
    assert calls == []             # nothing written
