import os
import re

_GLOBAL_NFO = {"movie.nfo", "tvshow.nfo", "season.nfo"}
_GLOBAL_ART_STEMS = {"poster", "fanart", "folder", "banner", "backdrop",
                     "landscape", "logo", "disc", "clearart", "thumb"}
_SEASON_POSTER = re.compile(r"^season(\d+|-specials)-poster$")


def is_global_asset(path):
    name = os.path.basename(path.replace("\\", "/")).lower()
    if name in _GLOBAL_NFO:
        return True
    stem, _ext = os.path.splitext(name)
    if stem in _GLOBAL_ART_STEMS:
        return True
    if _SEASON_POSTER.match(stem):
        return True
    return False
