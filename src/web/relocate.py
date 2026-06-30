"""Build Jellyfin-format target paths for relocating a misidentified file.

Movies:   <movies_root>/<Title (Year)>/<Title (Year)>.ext
Episodes: <tv_root>/<Series (Year)>/Season NN/<Series (Year)> - SxxExx - <Title>.ext
          (Season 0 -> "Specials" folder; S00Exx in the filename)
"""
import os
import posixpath
import re

_ILLEGAL = re.compile(r'[<>:"/\\|?*]')   # Windows-illegal filename chars


def sanitize(name):
    """Strip filesystem-illegal characters and collapse whitespace."""
    cleaned = _ILLEGAL.sub("", name or "").strip().rstrip(".")
    return re.sub(r"\s+", " ", cleaned).strip()


def _titled(title, year):
    base = sanitize(title)
    return f"{base} ({year})" if year else base


def _join(root, *parts):
    return "/".join([root.rstrip("/")] + [p.strip("/") for p in parts])


def movie_target(movies_root, title, year, ext):
    folder = _titled(title, year)
    return _join(movies_root, folder, folder + ext)


def episode_target(tv_root, series, year, season, episode, ep_title, ext):
    series_folder = _titled(series, year)
    season_folder = "Specials" if season == 0 else f"Season {season:02d}"
    code = f"S{int(season):02d}E{int(episode):02d}"
    stem = f"{series_folder} - {code}"
    if ep_title:
        stem = f"{stem} - {sanitize(ep_title)}"
    return _join(tv_root, series_folder, season_folder, stem + ext)


def flagged_target(movies_root, filepath, subdir):
    """Reparent a movie's video file under <movies_root>/<subdir>/, keeping its
    parent-folder name and original filename. If the file sits directly in the
    movies root, use the filename stem as the folder so we never nest under the
    root's own name."""
    norm = filepath.replace("\\", "/")
    fname = posixpath.basename(norm)
    parent = posixpath.basename(posixpath.dirname(norm))
    root_name = posixpath.basename(movies_root.replace("\\", "/").rstrip("/"))
    folder = parent if parent and parent != root_name else posixpath.splitext(fname)[0]
    return _join(movies_root, subdir, folder, fname)


def relocate_file(src_local, dest_local, exists_fn, makedirs_fn, move_fn):
    """Move src->dest on disk (local/SMB paths). Refuses to overwrite an existing dest."""
    if not exists_fn(src_local):
        raise FileNotFoundError(src_local)
    if exists_fn(dest_local):
        raise FileExistsError(dest_local)
    makedirs_fn(os.path.dirname(dest_local), exist_ok=True)
    move_fn(src_local, dest_local)


def pick_roots(media_paths):
    """Choose the movies and TV roots from configured media_paths by name."""
    movies = next((p for p in media_paths if "movie" in p.lower()), None)
    tv = next((p for p in media_paths
               if "tv" in p.lower() or "show" in p.lower()), None)
    return movies, tv


def build_target(filepath, kind, details, movies_root, tv_root):
    """kind 'movie' or 'episode'; details holds title/year (+ season/episode/ep_title)."""
    ext = os.path.splitext(filepath)[1]
    if kind == "movie":
        return movie_target(movies_root, details["title"], details.get("year"), ext)
    return episode_target(tv_root, details["title"], details.get("year"),
                          details["season"], details["episode"],
                          details.get("ep_title"), ext)
