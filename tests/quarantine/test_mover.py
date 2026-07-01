import os
from src.quarantine.mover import plan_moves, execute_plan


def test_plan_moves_includes_video_and_cascade_not_preserved():
    plan = {"video": "/d/v.mkv", "cascade": ["/d/v.nfo"], "preserved": ["/d/poster.jpg"]}
    pairs = plan_moves(plan, "/q")
    sources = [s for s, _ in pairs]
    assert "/d/v.mkv" in sources and "/d/v.nfo" in sources
    assert "/d/poster.jpg" not in sources


def test_dry_run_moves_nothing(tmp_path):
    src = tmp_path / "v.mkv"; src.write_bytes(b"x")
    q = tmp_path / "q"
    plan = {"video": str(src), "cascade": [], "preserved": []}
    execute_plan(plan, str(q), dry_run=True)
    assert src.exists() and not q.exists()


def test_real_move_relocates_into_quarantine(tmp_path):
    src = tmp_path / "v.mkv"; src.write_bytes(b"x")
    q = tmp_path / "q"
    plan = {"video": str(src), "cascade": [], "preserved": []}
    pairs = execute_plan(plan, str(q), dry_run=False)
    assert not src.exists()
    assert os.path.exists(pairs[0][1])  # destination exists


def test_execute_plan_uses_to_local_and_requires_video(tmp_path):
    import pytest
    # The catalog stores a NAS-style path; the file actually lives at a mapped local path.
    real = tmp_path / "real" / "v.mkv"; real.parent.mkdir(); real.write_bytes(b"x")
    q = tmp_path / "q"
    plan = {"video": "/share/Movies/v.mkv", "cascade": [], "preserved": []}
    to_local = lambda p: str(real) if p == "/share/Movies/v.mkv" else p
    pairs = execute_plan(plan, str(q), dry_run=False, to_local=to_local)
    assert not real.exists()                      # moved from the mapped location
    assert os.path.exists(pairs[0][1])            # now in quarantine

    # If the (mapped) video isn't reachable, it MUST raise — caller keeps the DB row.
    plan2 = {"video": "/share/Movies/missing.mkv", "cascade": [], "preserved": []}
    with pytest.raises(FileNotFoundError):
        execute_plan(plan2, str(q), dry_run=False, to_local=lambda p: "/nope/missing.mkv")


def test_quarantine_never_overwrites_an_already_parked_file(tmp_path):
    # Deleting two different files that map to the same quarantine dest (e.g. a file
    # re-added after a prior delete) must NOT clobber the earlier quarantined copy.
    q = tmp_path / "q"
    first = tmp_path / "v.mkv"; first.write_bytes(b"AAAA")
    plan1 = {"video": str(first), "cascade": [], "preserved": []}
    dest1 = execute_plan(plan1, str(q), dry_run=False)[0][1]

    second = tmp_path / "v.mkv"; second.write_bytes(b"BBBB")   # same name -> same dest
    plan2 = {"video": str(second), "cascade": [], "preserved": []}
    dest2 = execute_plan(plan2, str(q), dry_run=False)[0][1]

    assert dest1 != dest2                       # second got a non-colliding name
    assert os.path.exists(dest1) and os.path.exists(dest2)
    with open(dest1, "rb") as f:
        assert f.read() == b"AAAA"              # original copy intact, not overwritten


def test_execute_plan_skips_missing_sidecar_but_moves_video(tmp_path):
    real = tmp_path / "v.mkv"; real.write_bytes(b"x")
    q = tmp_path / "q"
    plan = {"video": str(real), "cascade": ["/d/gone.nfo"], "preserved": []}
    moved = execute_plan(plan, str(q), dry_run=False)
    assert not real.exists()                      # video moved
    assert [s for s, _ in moved] == [str(real)]   # missing sidecar skipped, not fatal
