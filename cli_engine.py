"""Entry point: the interactive CLI data engine.

Usage:
    python cli_engine.py [config.yaml]

Drives a keyboard-interactive menu (tasks 1-7) over the tested module layer.
"""
import json
import os
import sys
import datetime

from src.config import load_config, ConfigError
from src.database import init_db, get_connection
from src.indexer import scan_and_index
from src.prune import prune_stale
from src.parsing import parse_path
from src.matcher import match_one
from src.metadata_client import TmdbClient, TvdbClient
from src.metadata_repository import set_match
from src.repository import all_media_paths, get_media_row
from src.web.services import library_kpis

MENU = """
==================================================
        NAS Media Organizer & Audit Engine
==================================================
 [1] Scan File System & Index Media (Update DB)
 [2] Match Metadata via Online APIs (TMDB/TVDB)
 [3] Run Library Integrity & Gap Audit (Generate Reports)
 [4] Prune Stale Database Entries (Fast Sync)
 [5] Validate Configuration & API Connectivity
 [6] Export Offline Reports (Markdown/JSON)
 [7] Exit
==================================================
"""


def get_valid_choice(input_fn=input):
    while True:
        try:
            choice = int(input_fn("Select a task to run (1-7): "))
            if 1 <= choice <= 7:
                return choice
            print("Invalid selection. Enter a number between 1 and 7.")
        except ValueError:
            print("Invalid input. Enter a numeric value.")


def task_scan(config):
    conn = get_connection(config["database_path"])
    stats = scan_and_index(conn, config)
    return (f"Indexed {stats['media_indexed']} media, "
            f"tracked {stats['sidecars_tracked']} sidecars, "
            f"skipped {stats['skipped']} unchanged.")


def task_match(config):
    conn = get_connection(config["database_path"])
    keys = config["api_keys"]
    tmdb = TmdbClient(keys.get("tmdb", ""))
    tvdb = TvdbClient(keys.get("tvdb", ""))
    matched = ambiguous = unmatched = 0
    for path in all_media_paths(conn):
        parsed = parse_path(path)
        provider = tvdb if parsed["item_type"] == "episode" else tmdb
        result = match_one(parsed, provider)
        set_match(conn, path, result["metadata_id"], result["status"])
        matched += result["status"] == "matched"
        ambiguous += result["status"] == "ambiguous"
        unmatched += result["status"] == "unmatched"
    return f"Matched {matched}, ambiguous {ambiguous}, unmatched {unmatched}."


def task_audit(config):
    # Use the same duplicate definition as the dashboard (same folder + same base
    # name), not metadata_id grouping — every episode of a show shares the series id.
    from src.web.services import variant_conflicts
    conn = get_connection(config["database_path"])
    groups = variant_conflicts(conn)
    needs_sub = conn.execute(
        "SELECT COUNT(*) c FROM media_files "
        "WHERE has_english_audio IN ('no','unknown')").fetchone()["c"]
    return (f"{len(groups)} variant conflict group(s); "
            f"{needs_sub} item(s) flagged for subtitle review.")


def task_prune(config):
    conn = get_connection(config["database_path"])
    removed = prune_stale(conn)
    return f"Pruned {removed} stale database row(s)."


def task_validate(config):
    problems = []
    for p in config["media_paths"]:
        if not os.path.isdir(p):
            problems.append(f"media path not reachable: {p}")
    qp = config["quarantine_path"]
    parent = os.path.dirname(qp) or "."
    if not os.path.isdir(parent):
        problems.append(f"quarantine parent missing: {parent}")
    keys = config["api_keys"]
    for name in ("tmdb", "tvdb"):
        if not keys.get(name):
            problems.append(f"missing API key: {name}")
    if problems:
        return "Validation issues:\n  - " + "\n  - ".join(problems)
    return "Configuration valid; all paths reachable; API keys present."


def task_export(config):
    conn = get_connection(config["database_path"])
    kpis = library_kpis(conn)
    log_dir = config["log_directory"]
    os.makedirs(log_dir, exist_ok=True)
    md = os.path.join(log_dir, "library_report.md")
    js = os.path.join(log_dir, "library_report.json")
    with open(md, "w", encoding="utf-8") as f:
        f.write("# Library Report\n\n")
        f.write(f"- Total items: {kpis['total_items']}\n")
        f.write(f"- Storage used: {kpis['total_bytes'] / 1e9:.2f} GB\n")
        f.write(f"- Active issues: {kpis['issue_count']}\n")
    with open(js, "w", encoding="utf-8") as f:
        json.dump(kpis, f, indent=2)
    return f"Exported reports to {md} and {js}."


_TASKS = {1: task_scan, 2: task_match, 3: task_audit,
          4: task_prune, 5: task_validate, 6: task_export}


def run_task(choice, config):
    """Run a single non-interactive task; returns a summary string."""
    return _TASKS[choice](config)


def main(config_path="config.yaml"):
    try:
        config = load_config(config_path)
    except ConfigError as e:
        print(f"Config error: {e}")
        return
    init_db(config["database_path"])
    while True:
        print(MENU)
        choice = get_valid_choice()
        if choice == 7:
            print("Goodbye.")
            break
        try:
            print(run_task(choice, config))
        except Exception as e:  # keep the menu alive on task failure
            print(f"Task failed: {e}")


if __name__ == "__main__":
    main(sys.argv[1] if len(sys.argv) > 1 else "config.yaml")
