import copy
import os
import yaml

from src.secrets import apply_secrets

DEFAULTS = {
    "media_paths": [],
    "database_path": "/config/media_audit.db",
    "log_directory": "/logs",
    "quarantine_path": "/config/.quarantine",
    "api_keys": {
        "tmdb": "",
        "tvdb": "",
        "opensubtitles": {"api_key": "", "username": "", "password": ""},
    },
    "hashing": {
        "partial_hash_threshold_bytes": 20_000_000,
        "partial_chunk_bytes": 10_000_000,
    },
    "audit": {
        "duration_deviation_seconds": 120,
        "variant_priority": ["resolution", "bitrate", "codec", "audio_channels"],
    },
    # binary "" => auto-detect (resolve_ffprobe falls back to PATH then "ffprobe").
    "ffprobe": {"timeout_seconds": 30, "retries": 3, "binary": ""},
    # Media player for the dashboard's "play" action. binary "" => auto-detect VLC,
    # else open with the OS default association.
    "player": {"binary": ""},
    "api": {"max_retries": 2, "retry_backoff_seconds": 5, "cache_ttl_days": 30},
    "scan": {
        "worker_threads": 4,
        "valid_extensions": [
            # Common modern formats
            ".mkv", ".mp4", ".avi", ".m4v", ".mov", ".ts", ".wmv", ".webm",
            # Legacy formats — indexed so duplicates/cleanup candidates surface
            ".rm", ".rmvb", ".mpg", ".mpeg", ".flv", ".vob", ".m2ts", ".divx",
        ],
    },
    "safety": {"dry_run_default": True},
    # Web dashboard bind address. Change `port` to run more than one instance at once
    # (e.g. this app next to another copy on 8080). A CLI arg overrides this.
    "server": {"host": "0.0.0.0", "port": 8081},
    # Audio-language flagging: list movies whose audio track is in `languages` and
    # offer a one-click move into `staging_subdir`. languages=[] => feature hidden.
    "audio_flag": {"languages": [], "label": "Flagged Audio", "staging_subdir": "02-Ready"},
    # Maps stored (NAS) path prefixes to locally-accessible (SMB) prefixes for the
    # dashboard running off-NAS. Empty = paths used as-is (dashboard runs on the NAS).
    "path_map": {},
}


class ConfigError(Exception):
    pass


def _deep_merge(base, override):
    result = copy.deepcopy(base)
    for key, value in (override or {}).items():
        if isinstance(value, dict) and isinstance(result.get(key), dict):
            result[key] = _deep_merge(result[key], value)
        else:
            result[key] = value
    return result


def load_config(path):
    if not os.path.isfile(path):
        raise ConfigError(f"Config file not found: {path}")
    try:
        with open(path, "r", encoding="utf-8") as f:
            user = yaml.safe_load(f) or {}
    except yaml.YAMLError as e:
        raise ConfigError(f"Invalid YAML in {path}: {e}")
    if not isinstance(user, dict):
        raise ConfigError("Config root must be a mapping")
    merged = _deep_merge(DEFAULTS, user)
    # Overlay API credentials from the environment / a .env file (env > .env > yaml).
    # Resolve .env next to the config file so it travels with a deployment.
    dotenv_path = os.path.join(os.path.dirname(os.path.abspath(path)), ".env")
    apply_secrets(merged, dotenv_path=dotenv_path)
    if not merged["media_paths"]:
        raise ConfigError("config.media_paths must contain at least one path")
    return merged


def load_config_or_exit(path):
    """load_config, but on a config problem print the friendly message and exit non-zero
    instead of dumping a traceback. Used by the runner scripts so a missing/typo'd config
    (the most common first-run mistake) fails cleanly."""
    import sys
    try:
        return load_config(path)
    except ConfigError as e:
        print(f"Config error: {e}\nCreate one with: python setup_wizard.py")
        sys.exit(1)
