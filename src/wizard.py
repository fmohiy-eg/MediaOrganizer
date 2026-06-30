"""Interactive first-run setup wizard. Writes a config.yaml by asking a handful of
questions and auto-detecting tools. All I/O is injected (input_fn, exists_fn,
which_fn, write_fn, platform_name, env) so the flow is testable offline.

`build_config_dict(answers)` is a pure function turning collected answers into a
config dict; `run_wizard(...)` does only prompting/validation/writing.
"""
import os
import shutil
import sys

import yaml

from src.toolpaths import resolve_ffprobe, resolve_player


def build_config_dict(answers):
    """Pure: collected answers -> a config dict ready to dump to YAML."""
    cfg = {
        "media_paths": answers["media_paths"],
        "database_path": answers.get("database_path") or "./media_audit.db",
        "quarantine_path": answers.get("quarantine_path") or "./quarantine",
        "log_directory": answers.get("log_directory") or "./logs",
        "path_map": answers.get("path_map") or {},
        "ffprobe": {"binary": answers.get("ffprobe_binary", "") or ""},
        "player": {"binary": answers.get("player_binary", "") or ""},
    }
    af = answers.get("audio_flag")
    if af and af.get("languages"):
        cfg["audio_flag"] = {
            "languages": af["languages"],
            "label": af.get("label") or "Flagged Audio",
            "staging_subdir": af.get("staging_subdir") or "02-Ready",
        }
    keys = answers.get("api_keys") or {}
    if any(keys.values()):
        cfg["api_keys"] = {
            "tmdb": keys.get("tmdb", "") or "",
            "tvdb": keys.get("tvdb", "") or "",
            "opensubtitles": {"api_key": keys.get("opensubtitles", "") or "",
                              "username": "", "password": ""},
        }
    return cfg


def _yes(value):
    return str(value).strip().lower() in ("y", "yes")


def run_wizard(input_fn=input, exists_fn=os.path.isdir, isfile_fn=os.path.isfile,
               which_fn=shutil.which, write_fn=None, platform_name=sys.platform,
               env=None, config_path="config.yaml"):
    """Prompt the user, build and write config.yaml. Returns the config dict, or
    None if the user declined to overwrite an existing config."""
    if env is None:
        env = os.environ
    if write_fn is None:
        def write_fn(path, text):
            with open(path, "w", encoding="utf-8") as f:
                f.write(text)

    def out(msg):
        # Narration is best-effort; tests don't assert on it.
        print(msg)

    if isfile_fn(config_path):
        if not _yes(input_fn(f"{config_path} already exists — overwrite? [y/N]: ")):
            out("Aborted; existing config left untouched.")
            return None

    mode = input_fn("Deployment mode - [1] single machine (default), [2] NAS+PC split: ")
    split = str(mode).strip() == "2"

    movies = input_fn("Movies library folder: ").strip()
    tv = input_fn("TV Shows library folder: ").strip()
    for label, path in (("Movies", movies), ("TV Shows", tv)):
        if path and not exists_fn(path):
            out(f"  ! {label} folder not found (continuing anyway): {path}")
    media_paths = [p for p in (movies, tv) if p]

    path_map = {}
    if split:
        out("NAS+PC split: enter the NAS-side path prefix the catalog stores for each share.")
        movies_nas = input_fn("  Movies NAS prefix (e.g. /share/Movies): ").strip()
        tv_nas = input_fn("  TV Shows NAS prefix (e.g. /share/TV Shows): ").strip()
        if movies_nas and movies:
            path_map[movies_nas] = movies
        if tv_nas and tv:
            path_map[tv_nas] = tv

    detected_ff = resolve_ffprobe("", which_fn=which_fn, isfile_fn=lambda p: False)
    ffprobe_binary = input_fn(
        f"Path to ffprobe [auto-detect: {detected_ff}] (enter to auto-detect): ").strip()

    detected_player = resolve_player("", platform_name=platform_name,
                                     which_fn=which_fn, isfile_fn=lambda p: False)
    player_binary = input_fn(
        f"Path to media player [auto-detect: {detected_player or 'OS default'}] "
        "(enter to auto-detect): ").strip()

    api_keys = None
    if _yes(input_fn("Store API keys in config.yaml now? (.env is recommended instead) [y/N]: ")):
        api_keys = {
            "tmdb": input_fn("  TMDB API key: ").strip(),
            "tvdb": input_fn("  TVDB API key: ").strip(),
            "opensubtitles": input_fn("  OpenSubtitles API key: ").strip(),
        }

    audio_flag = None
    if _yes(input_fn("Enable audio-language flagging (flag movies by audio language)? [y/N]: ")):
        langs = [s.strip() for s in input_fn("  Language code(s), comma-separated (e.g. ara, ar): ").split(",")]
        langs = [s for s in langs if s]
        label = input_fn("  Tab label [Flagged Audio]: ").strip()
        subdir = input_fn("  Staging subfolder [02-Ready]: ").strip()
        audio_flag = {"languages": langs, "label": label, "staging_subdir": subdir}

    database_path = input_fn("Database file path [./media_audit.db]: ").strip()
    quarantine_path = input_fn("Quarantine folder [./quarantine]: ").strip()
    log_directory = input_fn("Log folder [./logs]: ").strip()

    cfg = build_config_dict({
        "media_paths": media_paths,
        "path_map": path_map,
        "ffprobe_binary": ffprobe_binary,
        "player_binary": player_binary,
        "api_keys": api_keys,
        "audio_flag": audio_flag,
        "database_path": database_path,
        "quarantine_path": quarantine_path,
        "log_directory": log_directory,
    })
    write_fn(config_path, yaml.safe_dump(cfg, sort_keys=False, allow_unicode=True))
    out(f"Wrote {config_path}. Put API keys in a .env file next to it (see .env.example).")
    return cfg
