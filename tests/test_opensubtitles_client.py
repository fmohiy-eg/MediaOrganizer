from src.opensubtitles_client import OpenSubtitlesClient


class _Resp:
    def __init__(self, payload, status=200):
        self._p = payload
        self.status_code = status
        self.content = b"x"

    def json(self): return self._p

    def raise_for_status(self):
        if self.status_code >= 400:
            raise RuntimeError(f"HTTP {self.status_code}")


class _Http:
    def __init__(self, get=None, post=None):
        self._get = get
        self._post = post
        self.calls = []

    def get(self, url, headers=None, params=None, timeout=None):
        self.calls.append(("GET", url, headers, params))
        return self._get(url, params)

    def post(self, url, headers=None, json=None, timeout=None):
        self.calls.append(("POST", url, headers, json))
        return self._post(url, json)


def test_user_info_returns_quota_data_with_bearer_token():
    http = _Http(get=lambda url, params: _Resp({"data": {
        "allowed_downloads": 100, "downloads_count": 7, "remaining_downloads": 93,
        "reset_time": "11 hours"}}))
    client = OpenSubtitlesClient("KEY", http=http)
    info = client.user_info("TKN")
    assert info["remaining_downloads"] == 93 and info["downloads_count"] == 7
    method, url, headers, _ = http.calls[-1]
    assert url.endswith("/infos/user") and headers["Authorization"] == "Bearer TKN"


def test_login_returns_token():
    http = _Http(post=lambda url, j: _Resp({"token": "TKN", "base_url": "api.opensubtitles.com"}))
    c = OpenSubtitlesClient("KEY", http=http)
    out = c.login("user", "pass")
    assert out["token"] == "TKN"
    # api key + credentials were sent
    assert http.calls[0][2]["Api-Key"] == "KEY"
    assert http.calls[0][3] == {"username": "user", "password": "pass"}


def test_search_normalizes_results():
    payload = {"total_count": 2, "data": [
        {"attributes": {"language": "en", "download_count": 167, "release": "BluRay",
                        "files": [{"file_id": 999, "file_name": "x.srt"}]}}]}
    http = _Http(get=lambda url, params: _Resp(payload))
    c = OpenSubtitlesClient("KEY", http=http)
    res = c.search(tmdb_id=329, languages="en")
    assert res[0]["file_id"] == 999 and res[0]["language"] == "en"
    assert http.calls[0][3]["languages"] == "en" and http.calls[0][3]["tmdb_id"] == 329


def test_download_returns_link_and_quota():
    payload = {"link": "https://dl/x.srt", "file_name": "x.srt",
               "remaining": 95, "requests": 5, "reset_time": "23 hours"}
    http = _Http(post=lambda url, j: _Resp(payload))
    c = OpenSubtitlesClient("KEY", http=http)
    out = c.download(999, token="TKN")
    assert out["ok"] is True
    assert out["link"] == "https://dl/x.srt"
    assert out["quota"]["remaining"] == 95
    # bearer token was attached
    assert http.calls[0][2]["Authorization"] == "Bearer TKN"


def test_download_quota_exhausted():
    payload = {"remaining": 0, "reset_time": "10 hours",
               "message": "You have downloaded your allowed subtitles."}
    http = _Http(post=lambda url, j: _Resp(payload, status=406))
    c = OpenSubtitlesClient("KEY", http=http)
    out = c.download(999, token="TKN")
    assert out["ok"] is False and out["quota_exhausted"] is True
    assert out["quota"]["remaining"] == 0 and "reset_time" in out["quota"]
