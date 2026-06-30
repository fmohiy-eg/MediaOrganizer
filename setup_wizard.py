"""First-run setup: interactively create config.yaml.

Usage:
    python setup_wizard.py [config.yaml]

Asks a few questions (deployment mode, library folders, tools, optional API keys
and audio-language flagging) and writes a ready-to-use config. Put your API keys in
a .env file next to config.yaml (copy .env.example) — they override config.yaml.
"""
import sys

from src.wizard import run_wizard


def main(config_path="config.yaml"):
    cfg = run_wizard(config_path=config_path)
    if cfg is None:
        return
    print("\nNext steps:")
    print("  1. (optional) cp .env.example .env  and fill in your API keys")
    print("  2. python scan_live.py config.yaml      # build the catalog")
    print("  3. python run_dashboard.py config.yaml  # open the dashboard")


if __name__ == "__main__":
    main(sys.argv[1] if len(sys.argv) > 1 else "config.yaml")
