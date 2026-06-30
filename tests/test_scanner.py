import os
from src.scanner import classify_path, discover

EXTS = [".mkv", ".mp4", ".avi"]


def test_classify_media_case_insensitive():
    assert classify_path("/m/A.MKV", EXTS) == "media"
    assert classify_path("/m/b.mp4", EXTS) == "media"


def test_classify_sidecars():
    assert classify_path("/m/a.nfo", EXTS) == "nfo"
    assert classify_path("/m/a.eng.srt", EXTS) == "subtitle"
    assert classify_path("/m/poster.jpg", EXTS) == "artwork"


def test_classify_trickplay_anywhere_in_path():
    assert classify_path("/m/Movie.trickplay/1.jpg", EXTS) == "trickplay_dir"


def test_classify_unknown_is_ignore():
    assert classify_path("/m/notes.txt", EXTS) == "ignore"


def test_classify_system_dir_files_ignored():
    assert classify_path(r"/m/X (2025)/.@__thumb/adefaultX.mkv", EXTS) == "ignore"
    assert classify_path(r"/m/@Recycle/old.mkv", EXTS) == "ignore"


def test_discover_prunes_qnap_system_dirs(tmp_path):
    (tmp_path / "Movie.mkv").write_bytes(b"x")
    thumb = tmp_path / ".@__thumb"; thumb.mkdir()
    (thumb / "adefaultMovie.mkv").write_bytes(b"x")
    rec = tmp_path / "@Recycle"; rec.mkdir()
    (rec / "old.mkv").write_bytes(b"x")
    found = [p for k, p in discover([str(tmp_path)], EXTS) if k == "media"]
    assert len(found) == 1 and found[0].endswith("Movie.mkv")


def test_discover_walks_and_skips_trickplay_descent(tmp_path):
    (tmp_path / "Movie.mkv").write_bytes(b"x")
    (tmp_path / "Movie.nfo").write_bytes(b"x")
    tp = tmp_path / "Movie.trickplay"
    tp.mkdir()
    (tp / "1.jpg").write_bytes(b"x")
    (tp / "2.jpg").write_bytes(b"x")
    found = list(discover([str(tmp_path)], EXTS))
    kinds = sorted(k for k, _ in found)
    # one media, one nfo, one trickplay_dir (not its inner jpgs)
    assert kinds == ["media", "nfo", "trickplay_dir"]
