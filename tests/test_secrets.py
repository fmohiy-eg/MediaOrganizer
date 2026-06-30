from src.secrets import parse_dotenv, apply_secrets


def _base_config():
    return {
        "media_paths": ["/media/Movies"],
        "api_keys": {
            "tmdb": "",
            "tvdb": "",
            "opensubtitles": {"api_key": "", "username": "", "password": ""},
        },
    }


# --- parse_dotenv -----------------------------------------------------------

def test_parse_dotenv_basic():
    text = "TMDB_API_KEY=abc123\nTVDB_API_KEY=def456\n"
    assert parse_dotenv(text) == {"TMDB_API_KEY": "abc123", "TVDB_API_KEY": "def456"}


def test_parse_dotenv_ignores_comments_blanks_and_strips_quotes():
    text = "\n# a comment\nTMDB_API_KEY = \"abc123\"  \n\n  TVDB_API_KEY='d e f'\n"
    parsed = parse_dotenv(text)
    assert parsed["TMDB_API_KEY"] == "abc123"
    assert parsed["TVDB_API_KEY"] == "d e f"


def test_parse_dotenv_value_with_equals():
    assert parse_dotenv("X=a=b=c")["X"] == "a=b=c"


# --- apply_secrets precedence ----------------------------------------------

def test_env_beats_dotenv_beats_yaml():
    cfg = _base_config()
    cfg["api_keys"]["tmdb"] = "from_yaml"
    apply_secrets(
        cfg,
        env={"TMDB_API_KEY": "from_env"},
        read_file_fn=lambda p: "TMDB_API_KEY=from_dotenv",
    )
    assert cfg["api_keys"]["tmdb"] == "from_env"


def test_dotenv_beats_yaml_when_no_env():
    cfg = _base_config()
    cfg["api_keys"]["tvdb"] = "from_yaml"
    apply_secrets(cfg, env={}, read_file_fn=lambda p: "TVDB_API_KEY=from_dotenv")
    assert cfg["api_keys"]["tvdb"] == "from_dotenv"


def test_yaml_kept_when_no_env_or_dotenv():
    cfg = _base_config()
    cfg["api_keys"]["tmdb"] = "from_yaml"
    apply_secrets(cfg, env={}, read_file_fn=lambda p: None)
    assert cfg["api_keys"]["tmdb"] == "from_yaml"


def test_empty_env_value_does_not_clobber_yaml():
    cfg = _base_config()
    cfg["api_keys"]["tmdb"] = "from_yaml"
    apply_secrets(cfg, env={"TMDB_API_KEY": ""}, read_file_fn=lambda p: None)
    assert cfg["api_keys"]["tmdb"] == "from_yaml"


def test_nested_opensubtitles_mapping():
    cfg = _base_config()
    apply_secrets(
        cfg,
        env={
            "OPENSUBTITLES_API_KEY": "os_key",
            "OPENSUBTITLES_USERNAME": "user",
            "OPENSUBTITLES_PASSWORD": "pass",
        },
        read_file_fn=lambda p: None,
    )
    os_cfg = cfg["api_keys"]["opensubtitles"]
    assert os_cfg["api_key"] == "os_key"
    assert os_cfg["username"] == "user"
    assert os_cfg["password"] == "pass"


def test_missing_dotenv_is_tolerated():
    cfg = _base_config()
    cfg["api_keys"]["tmdb"] = "from_yaml"
    # read_file_fn returning None simulates a missing .env; must not raise
    apply_secrets(cfg, env={}, read_file_fn=lambda p: None)
    assert cfg["api_keys"]["tmdb"] == "from_yaml"


def test_apply_secrets_returns_same_config():
    cfg = _base_config()
    out = apply_secrets(cfg, env={}, read_file_fn=lambda p: None)
    assert out is cfg
