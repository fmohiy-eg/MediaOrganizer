"""Organize a folder of loose TV files into the Jellyfin-format library.

Pure logic (no I/O): read embedded ffprobe tags to derive show/season/episode,
identify the series (injected `identify_fn`, normally TVDB), build Jellyfin target
paths, and classify sidecars (subtitles move+rename; other sidecar/info files are
flagged for removal). All external effects — directory walking, ffprobe, TVDB —
are injected so the suite runs offline.
"""
import posixpath
import re

from src.web.relocate import episode_target

VIDEO_EXTS = {".mkv", ".mp4", ".avi", ".m4v", ".mov", ".ts", ".wmv", ".webm",
              ".mpg", ".mpeg", ".flv", ".vob", ".m2ts", ".divx", ".rm", ".rmvb"}
SUBTITLE_EXTS = {".srt", ".ass", ".ssa", ".sub", ".vtt", ".smi", ".idx"}

# ffprobe tag keys (lower-cased) we look at, most-specific first.
_SHOW_KEYS = ("show", "tvshow", "series", "show_name")
_SEASON_KEYS = ("season_number", "season")
_EPISODE_KEYS = ("episode_sort", "episode_id", "episode_number", "episode")
_TITLE_KEYS = ("title", "episode_title", "subtitle")

# Free-text "title" tags that pack show + code + episode title into one string,
# e.g. "The West Wing S01E10 In Excelsis Deo" or "Some Show 2x05 The One".
_TITLE_SE = re.compile(r"^(?P<show>.*?)[\s._-]+S(?P<s>\d{1,2})E(?P<e>\d{1,4})\b[\s._-]*(?P<title>.*)$", re.I)
_TITLE_X = re.compile(r"^(?P<show>.*?)[\s._-]+(?P<s>\d{1,2})x(?P<e>\d{1,4})\b[\s._-]*(?P<title>.*)$", re.I)


def _parse_composite_title(title):
    """Pull {show, season, episode, episode_title} from a single free-text title
    tag of the form '<Show> SxxExx [Title]' / '<Show> NxNN [Title]'. None if no code."""
    if not title:
        return None
    s = str(title).strip()
    for rx in (_TITLE_SE, _TITLE_X):
        m = rx.match(s)
        if m and m.group("show").strip():
            return {"show": m.group("show").strip(), "season": int(m.group("s")),
                    "episode": int(m.group("e")),
                    "episode_title": (m.group("title") or "").strip() or None}
    return None


def _ext(path):
    return posixpath.splitext(path.replace("\\", "/"))[1].lower()


def _first(tags, keys):
    for k in keys:
        v = tags.get(k)
        if v not in (None, ""):
            return v
    return None


def _int(val):
    """Lenient int: '2' -> 2, 'Season 2' -> 2, else None."""
    if val is None:
        return None
    if isinstance(val, int):
        return val
    s = str(val).strip()
    try:
        return int(s)
    except ValueError:
        m = re.search(r"\d+", s)
        return int(m.group()) if m else None


def _episode_num(val):
    """Episode number, tolerating 'S02E05' / 'E05' / '5' / '205'."""
    if val is None:
        return None
    s = str(val).strip()
    try:
        return int(s)
    except ValueError:
        m = re.search(r"[eE](\d{1,4})", s)
        if m:
            return int(m.group(1))
        return _int(s)


def extract_episode_tags(probe_json):
    """Derive {show, season, episode, episode_title} from ffprobe format+stream
    tags (case-insensitive; format tags win over stream tags). Returns None unless
    show, season, and episode can all be determined."""
    if not probe_json:
        return None
    tags = {}
    # stream tags first so format tags overwrite them (format wins)
    for s in (probe_json.get("streams") or []):
        for k, v in (s.get("tags") or {}).items():
            tags[k.lower()] = v
    for k, v in ((probe_json.get("format") or {}).get("tags") or {}).items():
        tags[k.lower()] = v

    show = _first(tags, _SHOW_KEYS)
    season = _int(_first(tags, _SEASON_KEYS))
    episode = _episode_num(_first(tags, _EPISODE_KEYS))
    title = _first(tags, _TITLE_KEYS)
    if show and season is not None and episode is not None:
        return {"show": str(show).strip(), "season": season, "episode": episode,
                "episode_title": str(title).strip() if title else None}
    # Fallback: many taggers (e.g. HandBrake) pack "<Show> SxxExx <Title>" into the
    # single 'title' tag with no structured show/season/episode fields.
    return _parse_composite_title(title)


def episode_dest(tv_root, item):
    """Jellyfin episode path for a matched plan item."""
    return episode_target(tv_root, item["series"], item.get("year"),
                          item["season"], item["episode"], item.get("ep_title"),
                          item["ext"])


def subtitle_dest(video_dest, remainder):
    """Subtitle destination beside the video, preserving the original suffix
    (e.g. '.en.srt'). `remainder` is the sidecar's name minus the video base name."""
    return posixpath.splitext(video_dest.replace("\\", "/"))[0] + remainder


def classify_sidecars(video_src, all_files, video_dest):
    """Split the video's same-base-name siblings into subtitles to move+rename and
    other sidecar/info files to remove. Other *video* files are left untouched."""
    norm = video_src.replace("\\", "/")
    vdir = posixpath.dirname(norm)
    base = posixpath.splitext(posixpath.basename(norm))[0]
    subs, removes = [], []
    for f in all_files:
        fn = f.replace("\\", "/")
        if fn == norm or posixpath.dirname(fn) != vdir:
            continue
        name = posixpath.basename(fn)
        # Require a '.' boundary after the base so 'CD10' doesn't match 'CD100'.
        if not name.startswith(base + "."):
            continue
        remainder = name[len(base):]            # e.g. '.en.srt', '.nfo'
        if _ext(fn) in SUBTITLE_EXTS:
            subs.append({"src": f, "dest": subtitle_dest(video_dest, remainder)})
        elif _ext(fn) in VIDEO_EXTS:
            continue                            # a second video format — leave it alone
        else:
            removes.append(f)
    return subs, removes


def plan_folder(folder, walk_fn, probe_json_fn, identify_fn, tv_root):
    """Walk a folder, probe each video for embedded episode tags, identify the
    series, and return one plan row per video. `identify_fn(show, season, episode)`
    returns {series, year, metadata_id, ep_title} or None."""
    files = list(walk_fn(folder))
    plan = []
    for src in sorted(f for f in files if _ext(f) in VIDEO_EXTS):
        ext = _ext(src)
        row = {"src": src, "filename": posixpath.basename(src.replace("\\", "/"))}
        tags = extract_episode_tags(probe_json_fn(src))
        if not tags:
            plan.append({**row, "status": "no_tags"})
            continue
        ident = identify_fn(tags["show"], tags["season"], tags["episode"])
        if not ident or not ident.get("series"):
            plan.append({**row, "status": "unmatched", "show": tags["show"],
                         "season": tags["season"], "episode": tags["episode"]})
            continue
        item = {**row, "status": "matched", "series": ident["series"],
                "year": ident.get("year"), "season": tags["season"],
                "episode": tags["episode"], "ext": ext,
                "ep_title": ident.get("ep_title") or tags.get("episode_title"),
                "metadata_id": ident.get("metadata_id")}
        item["dest"] = episode_dest(tv_root, item)
        item["subtitles"], item["remove"] = classify_sidecars(src, files, item["dest"])
        plan.append(item)
    return plan
