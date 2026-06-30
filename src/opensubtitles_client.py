"""OpenSubtitles.com REST client.

Search works with the API key alone; download needs a user-login token
(obtained via login with username/password). The download response carries the
daily quota (`remaining`, `reset_time`) which callers surface to the user.
"""
import requests

_BASE = "https://api.opensubtitles.com/api/v1"
_UA = "NASMediaOrganizer v0.1"


def _quota(j):
    return {"remaining": j.get("remaining"), "requests": j.get("requests"),
            "reset_time": j.get("reset_time"), "reset_time_utc": j.get("reset_time_utc")}


class OpenSubtitlesClient:
    def __init__(self, api_key, http=requests, base_url=_BASE, user_agent=_UA, timeout=30):
        self.api_key = api_key
        self.http = http
        self.base_url = base_url
        self.user_agent = user_agent
        self.timeout = timeout

    def _headers(self, token=None):
        h = {"Api-Key": self.api_key, "User-Agent": self.user_agent,
             "Content-Type": "application/json", "Accept": "application/json"}
        if token:
            h["Authorization"] = f"Bearer {token}"
        return h

    def login(self, username, password):
        resp = self.http.post(f"{self.base_url}/login", headers=self._headers(),
                              json={"username": username, "password": password},
                              timeout=self.timeout)
        resp.raise_for_status()
        j = resp.json()
        return {"token": j["token"], "base_url": j.get("base_url")}

    def user_info(self, token):
        """GET /infos/user — current account quota (allowed/used/remaining/reset)
        without spending a download. Needs the login token."""
        resp = self.http.get(f"{self.base_url}/infos/user",
                             headers=self._headers(token), timeout=self.timeout)
        resp.raise_for_status()
        return resp.json().get("data", {})

    def search(self, languages="en", **params):
        params["languages"] = languages
        resp = self.http.get(f"{self.base_url}/subtitles", headers=self._headers(),
                             params=params, timeout=self.timeout)
        resp.raise_for_status()
        out = []
        for item in resp.json().get("data", []):
            a = item.get("attributes", {})
            files = a.get("files") or []
            out.append({
                "file_id": files[0]["file_id"] if files else None,
                "file_name": files[0].get("file_name") if files else None,
                "language": a.get("language"),
                "release": a.get("release"),
                "download_count": a.get("download_count"),
                "hearing_impaired": a.get("hearing_impaired"),
            })
        return out

    def download(self, file_id, token):
        resp = self.http.post(f"{self.base_url}/download", headers=self._headers(token),
                              json={"file_id": file_id}, timeout=self.timeout)
        j = resp.json() if resp.content else {}
        quota = _quota(j)
        remaining = j.get("remaining")
        if resp.status_code == 406 or (remaining is not None and remaining <= 0 and "link" not in j):
            return {"ok": False, "quota_exhausted": True, "quota": quota,
                    "message": j.get("message")}
        resp.raise_for_status()
        return {"ok": True, "link": j["link"], "file_name": j.get("file_name"),
                "quota": quota}
