from src.metadata_client import TmdbClient, TvdbClient


class _Resp:
    def __init__(self, payload): self._p = payload
    def raise_for_status(self): pass
    def json(self): return self._p


def test_tmdb_search_uses_bearer_and_normalizes():
    seen = {}
    payload = {"results": [
        {"id": 603, "title": "The Matrix", "release_date": "1999-03-31"},
        {"id": 604, "title": "The Matrix Reloaded", "release_date": "2003-05-15"}]}

    def fake_get(url, params=None, headers=None, timeout=None):
        seen["headers"] = headers
        return _Resp(payload)

    client = TmdbClient("TOK", http_get=fake_get)
    cands = client.search({"movie_title": "The Matrix", "year": 1999})
    assert seen["headers"]["Authorization"] == "Bearer TOK"
    assert cands[0] == {"metadata_id": "tmdb:603", "title": "The Matrix", "year": 1999}
    assert cands[1]["year"] == 2003


def test_tvdb_logs_in_then_searches():
    calls = {"login": 0}

    def fake_post(url, json=None, timeout=None):
        calls["login"] += 1
        assert json == {"apikey": "KEY"}
        return _Resp({"data": {"token": "SESSION"}})

    def fake_get(url, params=None, headers=None, timeout=None):
        assert headers["Authorization"] == "Bearer SESSION"
        return _Resp({"data": [{"tvdb_id": "78581", "name": "Dilbert", "year": "1999"}]})

    client = TvdbClient("KEY", http_get=fake_get, http_post=fake_post)
    cands = client.search({"series_title": "Dilbert"})
    assert cands[0] == {"metadata_id": "tvdb:78581", "title": "Dilbert", "year": 1999}
    # second search reuses the token (no second login)
    client.search({"series_title": "Dilbert"})
    assert calls["login"] == 1


def test_tvdb_get_episodes_paginates():
    pages = {
        0: {"data": {"episodes": [
                {"seasonNumber": 1, "number": 1, "aired": "1999-01-25", "name": "The Name"},
                {"seasonNumber": 1, "number": 2, "aired": "1999-02-01", "name": "The Competition"}]},
            "links": {"next": "page1"}},
        1: {"data": {"episodes": [
                {"seasonNumber": 1, "number": 3, "aired": "1999-02-08", "name": "The Prototype"}]},
            "links": {"next": None}},
    }

    def fake_post(url, json=None, timeout=None):
        return _Resp({"data": {"token": "T"}})

    def fake_get(url, params=None, headers=None, timeout=None):
        return _Resp(pages[params["page"]])

    eps = TvdbClient("KEY", http_get=fake_get, http_post=fake_post).get_episodes(78581)
    assert len(eps) == 3
    assert eps[0] == {"season": 1, "episode": 1, "air_date": "1999-01-25", "name": "The Name"}
    assert eps[-1]["episode"] == 3
