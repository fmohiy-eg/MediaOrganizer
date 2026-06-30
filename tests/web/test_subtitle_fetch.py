import io
import os
import zipfile
from src.web.subtitle_fetch import (extract_subtitle_text, target_subtitle_path,
                                     ingest_subtitle, to_local_path, to_nas_path,
                                     fetch_and_ingest)

SRT = "1\n00:00:01,000 --> 00:00:02,000\nHello\n"


def test_extract_raw_utf8():
    assert "Hello" in extract_subtitle_text(SRT.encode("utf-8"))


def test_extract_latin1_reencodes():
    text = extract_subtitle_text(("Café".encode("latin-1")))
    assert "Café" in text  # decoded correctly, now a python str (UTF-8 on write)


def test_extract_from_zip():
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        z.writestr("readme.txt", "ignore me")
        z.writestr("Movie.srt", SRT)
    assert "Hello" in extract_subtitle_text(buf.getvalue())


def test_target_path_default_and_collision():
    vid = "/d/Movie (2012).mkv"
    assert target_subtitle_path(vid, "eng", lambda p: False) == "/d/Movie (2012).eng.srt"
    taken = {"/d/Movie (2012).eng.srt"}
    assert target_subtitle_path(vid, "eng", lambda p: p in taken) == "/d/Movie (2012).eng.1.srt"


def test_ingest_writes_utf8_and_returns_target():
    written = {}
    out = ingest_subtitle(SRT.encode("utf-8"), "/d/Movie (2012).mkv", lang="eng",
                          exists_fn=lambda p: False,
                          write_fn=lambda path, data: written.update({path: data}))
    assert out["target"] == "/d/Movie (2012).eng.srt"
    assert b"Hello" in written["/d/Movie (2012).eng.srt"]


class _FakeClient:
    def __init__(self, results, dl):
        self._results = results; self._dl = dl; self.searched = None
    def search(self, **params): self.searched = params; return self._results
    def download(self, file_id, token): return self._dl


class _DLResp:
    def __init__(self, content): self.content = content


def test_fetch_and_ingest_happy_path():
    client = _FakeClient(
        results=[{"file_id": 1, "download_count": 5, "release": "A"},
                 {"file_id": 2, "download_count": 99, "release": "B"}],
        dl={"ok": True, "link": "http://x/s.srt", "quota": {"remaining": 94}})
    written = {}
    out = fetch_and_ingest(client, "TKN", "/d/Movie (2012).mkv",
                           {"tmdb_id": 329}, http_get=lambda url, timeout=None: _DLResp(SRT.encode()),
                           exists_fn=lambda p: False,
                           write_fn=lambda p, d: written.update({p: d}))
    assert out["ok"] and out["target"] == "/d/Movie (2012).eng.srt"
    assert out["release"] == "B"  # most-downloaded chosen
    assert out["quota"]["remaining"] == 94


def test_fetch_and_ingest_quota_exhausted():
    client = _FakeClient(results=[{"file_id": 1, "download_count": 5}],
                         dl={"ok": False, "quota_exhausted": True,
                             "quota": {"remaining": 0, "reset_time": "9 hours"}})
    out = fetch_and_ingest(client, "TKN", "/d/M.mkv", {"tmdb_id": 1},
                           http_get=lambda url, timeout=None: _DLResp(b""))
    assert out["ok"] is False and out["reason"] == "quota_exhausted"
    assert out["quota"]["reset_time"] == "9 hours"


def test_fetch_no_results():
    client = _FakeClient(results=[], dl={})
    out = fetch_and_ingest(client, "TKN", "/d/M.mkv", {"tmdb_id": 1},
                           http_get=lambda url, timeout=None: _DLResp(b""))
    assert out["ok"] is False and out["reason"] == "no_subtitles_found"


def test_to_local_path_translates_nas_to_smb():
    pm = {"/share/TV Shows": r"\\nas\TV Shows", "/share/Movies": r"\\nas\Movies"}
    assert to_local_path("/share/Movies/01-Ready/X/X.mkv", pm) == r"\\nas\Movies\01-Ready\X\X.mkv"
    # unmapped path returned unchanged
    assert to_local_path("/other/x.mkv", pm) == "/other/x.mkv"


def test_to_nas_path_translates_smb_to_nas():
    pm = {"/share/TV Shows": r"\\nas\TV Shows", "/share/Movies": r"\\nas\Movies"}
    assert to_nas_path(r"\\nas\Movies\01-Ready\X\X.mkv", pm) == "/share/Movies/01-Ready/X/X.mkv"
    # unmapped path returned unchanged
    assert to_nas_path(r"\\other\x.mkv", pm) == r"\\other\x.mkv"
    # already-NAS path returned unchanged (no local prefix matches)
    assert to_nas_path("/share/Movies/01-Ready/X/X.mkv", pm) == "/share/Movies/01-Ready/X/X.mkv"


def test_to_nas_path_is_inverse_of_to_local_path():
    pm = {"/share/TV Shows": r"\\nas\TV Shows", "/share/Movies": r"\\nas\Movies"}
    nas = "/share/TV Shows/01-Ready/02-ArabicReady/Heat (1995)/Heat (1995).mkv"
    assert to_nas_path(to_local_path(nas, pm), pm) == nas
