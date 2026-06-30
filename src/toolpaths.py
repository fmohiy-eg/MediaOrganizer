"""Resolve external tool binaries (ffprobe, VLC) across platforms.

A configured path (from config.yaml `ffprobe.binary` / `player.binary`) always wins
when it resolves; otherwise we look the tool up on PATH, then fall back to
platform-specific default install locations. All probing is injectable so tests run
without the real tools installed.
"""
import os
import shutil
import sys

_PLAYER_DEFAULTS = {
    "win32": [
        r"C:\Program Files\VideoLAN\VLC\vlc.exe",
        r"C:\Program Files (x86)\VideoLAN\VLC\vlc.exe",
    ],
    "darwin": ["/Applications/VLC.app/Contents/MacOS/VLC"],
    "linux": ["/usr/bin/vlc", "/snap/bin/vlc"],
}


def _resolve_configured(configured, which_fn, isfile_fn):
    """A configured value that is either an existing file or a PATH-resolvable name."""
    if not configured:
        return None
    if isfile_fn(configured):
        return configured
    return which_fn(configured) or None


def resolve_ffprobe(configured, which_fn=shutil.which, isfile_fn=os.path.isfile):
    """configured (if it resolves) -> which('ffprobe') -> literal 'ffprobe'."""
    found = _resolve_configured(configured, which_fn, isfile_fn)
    if found:
        return found
    return which_fn("ffprobe") or "ffprobe"


def ffprobe_is_available(binary, which_fn=shutil.which, isfile_fn=os.path.isfile):
    """True if `binary` is an existing file or a PATH-resolvable command. Lets callers
    tell a real install apart from resolve_ffprobe's last-resort 'ffprobe' literal."""
    if not binary:
        return False
    return bool(isfile_fn(binary) or which_fn(binary))


def resolve_player(configured, platform_name=sys.platform,
                   which_fn=shutil.which, isfile_fn=os.path.isfile):
    """configured -> which('vlc') -> platform default list -> None (use OS default)."""
    found = _resolve_configured(configured, which_fn, isfile_fn)
    if found:
        return found
    on_path = which_fn("vlc")
    if on_path:
        return on_path
    for cand in _PLAYER_DEFAULTS.get(platform_name, []):
        if isfile_fn(cand):
            return cand
    return None
