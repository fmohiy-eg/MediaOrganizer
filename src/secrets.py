"""Overlay API credentials from the environment / a `.env` file onto a loaded config.

Precedence per key: process environment > `.env` file > value already in config.yaml.
An empty env/.env value never clobbers a real config.yaml value. Everything is
injectable (`env`, `read_file_fn`) so the suite runs offline with no real env/FS.
"""
import os

# Env-var name -> path into the config dict.
_MAPPINGS = {
    "TMDB_API_KEY": ("api_keys", "tmdb"),
    "TVDB_API_KEY": ("api_keys", "tvdb"),
    "OPENSUBTITLES_API_KEY": ("api_keys", "opensubtitles", "api_key"),
    "OPENSUBTITLES_USERNAME": ("api_keys", "opensubtitles", "username"),
    "OPENSUBTITLES_PASSWORD": ("api_keys", "opensubtitles", "password"),
}


def parse_dotenv(text):
    """Parse simple `KEY=VALUE` lines. Ignores blanks and `#` comments; strips a
    single surrounding pair of quotes. Splits on the first `=` only."""
    out = {}
    for line in (text or "").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        key = key.strip()
        value = value.strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in ("'", '"'):
            value = value[1:-1]
        if key:
            out[key] = value
    return out


def _default_reader(path):
    if not path or not os.path.isfile(path):
        return None
    with open(path, "r", encoding="utf-8") as f:
        return f.read()


def _set_nested(config, keys, value):
    node = config
    for k in keys[:-1]:
        node = node.setdefault(k, {})
    node[keys[-1]] = value


def apply_secrets(config, env=None, dotenv_path=".env", read_file_fn=None):
    """Mutate `config` in place, overlaying secrets from env/.env. Returns `config`."""
    if env is None:
        env = os.environ
    if read_file_fn is None:
        read_file_fn = _default_reader
    dotenv = parse_dotenv(read_file_fn(dotenv_path))
    for var, keys in _MAPPINGS.items():
        value = env.get(var) or dotenv.get(var)
        if value:  # non-empty only — never clobber a real yaml value with a blank
            _set_nested(config, keys, value)
    return config
