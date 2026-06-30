import requests

_TMDB_SEARCH_MOVIE = "https://api.themoviedb.org/3/search/movie"
_TVDB_BASE = "https://api4.thetvdb.com/v4"
_TVDB_LOGIN = _TVDB_BASE + "/login"
_TVDB_SEARCH = _TVDB_BASE + "/search"


def _year_from_date(date_str):
    if date_str and len(date_str) >= 4 and date_str[:4].isdigit():
        return int(date_str[:4])
    return None


class TmdbClient:
    """TMDB movie search. `api_key` is a v4 Bearer token (sent as an Authorization header)."""

    def __init__(self, api_key, http_get=requests.get, timeout=15):
        self.api_key = api_key
        self.http_get = http_get
        self.timeout = timeout

    def search(self, parsed):
        title = parsed.get("movie_title") or parsed.get("series_title") or ""
        resp = self.http_get(
            _TMDB_SEARCH_MOVIE,
            headers={"Authorization": f"Bearer {self.api_key}"},
            params={"query": title},
            timeout=self.timeout)
        resp.raise_for_status()
        out = []
        for r in resp.json().get("results", []):
            out.append({"metadata_id": f"tmdb:{r['id']}", "title": r.get("title"),
                        "year": _year_from_date(r.get("release_date"))})
        return out


class TvdbClient:
    """TVDB series search. Exchanges the API key for a session token via /login, then searches."""

    def __init__(self, api_key, http_get=requests.get, http_post=requests.post, timeout=15):
        self.api_key = api_key
        self.http_get = http_get
        self.http_post = http_post
        self.timeout = timeout
        self._token = None

    def _login(self):
        resp = self.http_post(_TVDB_LOGIN, json={"apikey": self.api_key}, timeout=self.timeout)
        resp.raise_for_status()
        self._token = resp.json()["data"]["token"]
        return self._token

    def search(self, parsed):
        if not self._token:
            self._login()
        title = parsed.get("series_title") or ""
        resp = self.http_get(
            _TVDB_SEARCH,
            headers={"Authorization": f"Bearer {self._token}"},
            params={"query": title, "type": "series"},
            timeout=self.timeout)
        resp.raise_for_status()
        out = []
        for r in resp.json().get("data", []):
            yr = r.get("year")
            out.append({"metadata_id": f"tvdb:{r.get('tvdb_id') or r.get('id')}",
                        "title": r.get("name"),
                        "year": int(yr) if yr else None})
        return out

    def get_episodes(self, series_id):
        """All episodes for a TVDB series id, paginated. Returns
        [{'season', 'episode', 'air_date', 'name'}], season/episode as ints."""
        if not self._token:
            self._login()
        episodes = []
        page = 0
        while True:
            resp = self.http_get(
                f"{_TVDB_BASE}/series/{series_id}/episodes/default",
                headers={"Authorization": f"Bearer {self._token}"},
                params={"page": page}, timeout=self.timeout)
            resp.raise_for_status()
            body = resp.json()
            data = body.get("data") or {}
            for e in data.get("episodes", []):
                episodes.append({"season": e.get("seasonNumber"),
                                 "episode": e.get("number"),
                                 "air_date": e.get("aired"),
                                 "name": e.get("name")})
            if not (body.get("links") or {}).get("next"):
                break
            page += 1
        return episodes
