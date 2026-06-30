import pytest
from src.database import init_db, get_connection
from src.repository import upsert_media_file, add_sidecar
from src.quarantine.cascade import build_deletion_plan


def _conn(tmp_path):
    db = str(tmp_path / "m.db"); init_db(db); return get_connection(db)


def _rec(path):
    return dict(filepath=path, filename="v.mkv", extension=".mkv",
                parent_directory="/d", file_size_bytes=10, fast_hash="fh", os_hash="oh")


def test_plan_splits_cascade_and_preserved(tmp_path):
    conn = _conn(tmp_path)
    rid = upsert_media_file(conn, _rec("/d/Show - S01E01 - Pilot.mkv"))
    add_sidecar(conn, rid, "/d/Show - S01E01 - Pilot.nfo", "nfo")
    add_sidecar(conn, rid, "/d/Show - S01E01 - Pilot-thumb.jpg", "artwork")
    add_sidecar(conn, rid, "/d/Show - S01E01 - Pilot.trickplay", "trickplay_dir")
    add_sidecar(conn, rid, "/d/poster.jpg", "artwork")     # global, preserve
    add_sidecar(conn, rid, "/d/tvshow.nfo", "nfo")         # global, preserve
    plan = build_deletion_plan(conn, "/d/Show - S01E01 - Pilot.mkv")
    assert plan["video"] == "/d/Show - S01E01 - Pilot.mkv"
    assert set(plan["cascade"]) == {
        "/d/Show - S01E01 - Pilot.nfo",
        "/d/Show - S01E01 - Pilot-thumb.jpg",
        "/d/Show - S01E01 - Pilot.trickplay"}
    assert set(plan["preserved"]) == {"/d/poster.jpg", "/d/tvshow.nfo"}


def test_format_variant_preserves_shared_sidecars(tmp_path):
    # Same movie in 3 formats sharing one .nfo / .eng.srt / .trickplay.
    conn = _conn(tmp_path)
    d = "/m/Batman (2016)"
    mkv = upsert_media_file(conn, dict(_rec(d + "/Batman (2016).mkv"),
                                       parent_directory=d, extension=".mkv"))
    avi = upsert_media_file(conn, dict(_rec(d + "/Batman (2016).avi"),
                                       parent_directory=d, extension=".avi"))
    # sidecars (linked here to the avi) are named after the movie, shared by all copies
    for path, kind in [(d + "/Batman (2016).nfo", "nfo"),
                       (d + "/Batman (2016).eng.srt", "subtitle"),
                       (d + "/Batman (2016).trickplay", "trickplay_dir"),
                       (d + "/www.YTS.MX.jpg", "artwork")]:
        add_sidecar(conn, avi, path, kind)

    plan = build_deletion_plan(conn, d + "/Batman (2016).avi")
    # Only the .avi moves; the shared sidecars (still used by the .mkv) are preserved.
    assert plan["cascade"] == []
    assert set(plan["preserved"]) == {
        d + "/Batman (2016).nfo", d + "/Batman (2016).eng.srt",
        d + "/Batman (2016).trickplay", d + "/www.YTS.MX.jpg"}


def test_lone_video_cascades_its_own_sidecars(tmp_path):
    # No sibling copy -> the video's own sidecars DO cascade.
    conn = _conn(tmp_path)
    d = "/m/Solo (2018)"
    vid = upsert_media_file(conn, dict(_rec(d + "/Solo (2018).mkv"), parent_directory=d))
    add_sidecar(conn, vid, d + "/Solo (2018).nfo", "nfo")
    add_sidecar(conn, vid, d + "/Solo (2018).eng.srt", "subtitle")
    plan = build_deletion_plan(conn, d + "/Solo (2018).mkv")
    assert set(plan["cascade"]) == {d + "/Solo (2018).nfo", d + "/Solo (2018).eng.srt"}


def test_missing_file_raises(tmp_path):
    conn = _conn(tmp_path)
    with pytest.raises(ValueError):
        build_deletion_plan(conn, "/nope.mkv")
