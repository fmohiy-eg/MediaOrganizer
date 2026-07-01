"""Entry point: launch the web dashboard.

Usage:
    python run_dashboard.py [config.yaml] [port]

Reads the config (default: ./config.yaml), ensures the database exists, and serves
the dashboard with uvicorn. Bind host/port come from config `server.host`/`server.port`
(default 8081); an optional CLI port argument overrides the config, so you can run
several instances side by side on different ports.
"""
import subprocess
import sys
from datetime import datetime

import uvicorn

from src.config import load_config_or_exit
from src.database import init_db
from src.toolpaths import resolve_ffprobe, resolve_player, ffprobe_is_available
from web_dashboard import create_app


def _build_id():
    """A short stamp shown in the UI so a stale (un-restarted) server is obvious:
    server start time + the current git commit (best-effort)."""
    stamp = datetime.now().strftime("%Y-%m-%d %H:%M")
    try:
        sha = subprocess.run(["git", "rev-parse", "--short", "HEAD"],
                             capture_output=True, text=True, timeout=5).stdout.strip()
    except Exception:
        sha = ""
    return f"{stamp} {sha}".strip()


def resolve_bind(config, cli_host=None, cli_port=None):
    """Bind address: a CLI override wins, else config `server.host`/`server.port`,
    else 0.0.0.0:8081. Lets multiple instances run at once on different ports."""
    srv = config.get("server") or {}
    host = cli_host or srv.get("host") or "0.0.0.0"
    port = int(cli_port or srv.get("port") or 8081)
    return host, port


def main(config_path="config.yaml", host=None, port=None):
    config = load_config_or_exit(config_path)
    host, port = resolve_bind(config, host, port)
    init_db(config["database_path"])
    ffprobe_binary = resolve_ffprobe(config["ffprobe"].get("binary", ""))
    if not ffprobe_is_available(ffprobe_binary):
        print("! ffprobe not found - runtime/codec/audio details and the Probe panel "
              "won't work.\n  Install ffmpeg (see README \"Prerequisites\") or set "
              "ffprobe.binary in config.yaml. The dashboard still runs.")
    app = create_app(
        config["database_path"], config["quarantine_path"],
        os_api_key=config["api_keys"]["opensubtitles"]["api_key"],
        path_map=config.get("path_map", {}),
        ffprobe_binary=ffprobe_binary,
        duration_deviation_seconds=config["audit"]["duration_deviation_seconds"],
        tmdb_api_key=config["api_keys"]["tmdb"],
        tvdb_api_key=config["api_keys"]["tvdb"],
        media_paths=config["media_paths"],
        player_binary=resolve_player(config.get("player", {}).get("binary", "")),
        audio_flag=config.get("audio_flag", {}),
        variant_priority=config["audit"]["variant_priority"],
        instance_name=config.get("instance_name", ""),
        build_id=_build_id())
    print(f"Dashboard: http://{host}:{port}  (db={config['database_path']})")
    uvicorn.run(app, host=host, port=port)


if __name__ == "__main__":
    # Usage: python run_dashboard.py [config.yaml] [port]
    args = sys.argv[1:]
    cfg = args[0] if args else "config.yaml"
    cli_port = args[1] if len(args) > 1 else None
    main(cfg, port=cli_port)
