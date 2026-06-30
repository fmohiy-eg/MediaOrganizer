"""Extract metadata IDs that Jellyfin/Kodi already resolved into .nfo sidecars.

Handles the common Kodi/Jellyfin shapes (robust to slightly malformed XML):
  <uniqueid type="tmdb">329</uniqueid>   <tmdbid>329</tmdbid>
  <uniqueid type="tvdb">78581</uniqueid> <tvdbid>78581</tvdbid>
  <imdbid>tt0107290</imdbid>
and legacy single-URL .nfo files (themoviedb.org/movie/329, thetvdb.com/...&id=78581).
"""
import re

_PATTERNS = {
    "tmdb": [
        re.compile(r'<uniqueid[^>]*type="tmdb"[^>]*>\s*(\d+)\s*</uniqueid>', re.I),
        re.compile(r"<tmdbid>\s*(\d+)\s*</tmdbid>", re.I),
        re.compile(r"themoviedb\.org/(?:movie|tv)/(\d+)", re.I),
    ],
    "tvdb": [
        re.compile(r'<uniqueid[^>]*type="tvdb"[^>]*>\s*(\d+)\s*</uniqueid>', re.I),
        re.compile(r"<tvdbid>\s*(\d+)\s*</tvdbid>", re.I),
        re.compile(r"thetvdb\.com/[^\s<]*?(?:id=|/series/)(\d+)", re.I),
    ],
    "imdb": [
        re.compile(r'<uniqueid[^>]*type="imdb"[^>]*>\s*(tt\d+)\s*</uniqueid>', re.I),
        re.compile(r"<imdbid>\s*(tt\d+)\s*</imdbid>", re.I),
        re.compile(r"imdb\.com/title/(tt\d+)", re.I),
    ],
}


def extract_ids(text):
    """Return {'tmdb': '329', 'tvdb': '78581', 'imdb': 'tt...'} for whatever is present."""
    out = {}
    if not text:
        return out
    for source, patterns in _PATTERNS.items():
        for pat in patterns:
            m = pat.search(text)
            if m:
                out[source] = m.group(1)
                break
    return out
