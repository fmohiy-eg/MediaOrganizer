import os
import re

_SXXEXX = re.compile(r"[Ss](\d{1,2})[Ee](\d{1,3})(?:-?[Ee](\d{1,3}))?")
_FLAT = re.compile(r"(?<![\dxX])(\d{1,2})[xX](\d{1,3})(?:-(\d{1,3}))?")
_YEAR_PAREN = re.compile(r"\((\d{4})\)")
_EDITIONS = ["Director's Cut", "Extended", "Remastered", "Unrated", "Theatrical"]


def _norm(path):
    return path.replace("\\", "/")


def _strip_year_folder(folder):
    """'Calls (US) (2021)' -> ('Calls (US)', 2021); 'Dilbert (1999)' -> ('Dilbert', 1999)."""
    years = _YEAR_PAREN.findall(folder)
    year = int(years[-1]) if years else None
    title = folder
    if years:
        idx = folder.rfind(f"({years[-1]})")
        title = folder[:idx].strip()
    return title, year


def _find_edition(name):
    for ed in _EDITIONS:
        if ed.lower() in name.lower():
            return ed
    return None


def parse_path(filepath):
    parts = [p for p in _norm(filepath).split("/") if p]
    filename = parts[-1] if parts else ""
    stem = os.path.splitext(filename)[0]
    parent = parts[-2] if len(parts) >= 2 else ""
    grandparent = parts[-3] if len(parts) >= 3 else ""

    result = {
        "item_type": "unknown", "series_title": None, "year": None,
        "season_number": None, "episode_number": None, "episode_number_end": None,
        "episode_title": None, "movie_title": None, "edition": _find_edition(stem),
    }

    # Determine season folder context.
    season_from_folder = None
    series_folder = None
    if parent.lower().startswith("season"):
        m = re.search(r"(\d{1,2})", parent)
        season_from_folder = int(m.group(1)) if m else None
        series_folder = grandparent
    elif parent.lower() == "specials":
        season_from_folder = 0
        series_folder = grandparent

    # Try episode tokens in the filename.
    m = _SXXEXX.search(stem)
    flat = _FLAT.search(stem) if not m else None
    token_match = m or flat
    if token_match:
        result["item_type"] = "episode"
        if m:
            season = int(m.group(1)); ep = int(m.group(2)); ep_end = m.group(3)
        else:
            season = int(flat.group(1)); ep = int(flat.group(2)); ep_end = flat.group(3)
        result["season_number"] = season_from_folder if season_from_folder is not None else season
        result["episode_number"] = ep
        result["episode_number_end"] = int(ep_end) if ep_end else None
        # Title = everything after the matched token, trimmed of a leading separator.
        after = stem[token_match.end():]
        after = re.sub(r"^\s*-\s*", "", after).strip()
        result["episode_title"] = after or None
        src_folder = series_folder if series_folder else parent
        title, year = _strip_year_folder(src_folder)
        result["series_title"] = title or None
        result["year"] = year
        return result

    # Otherwise treat as a movie; identity from the containing folder.
    result["item_type"] = "movie"
    title, year = _strip_year_folder(parent)
    result["movie_title"] = title or None
    result["year"] = year
    return result
