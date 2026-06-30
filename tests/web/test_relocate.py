import pytest
from src.web.relocate import (sanitize, movie_target, episode_target,
                              pick_roots, build_target, relocate_file, arabic_target)


def test_arabic_target_reparents_under_subdir():
    src = "/share/Movies/01-Ready/Heat (1995)/Heat (1995).mkv"
    assert arabic_target("/share/Movies/01-Ready", src) == \
        "/share/Movies/01-Ready/02-ArabicReady/Heat (1995)/Heat (1995).mkv"


def test_arabic_target_file_directly_in_root_uses_filename_stem():
    src = "/share/Movies/01-Ready/loose.mkv"
    assert arabic_target("/share/Movies/01-Ready", src) == \
        "/share/Movies/01-Ready/02-ArabicReady/loose/loose.mkv"


def test_sanitize_strips_illegal_chars():
    assert sanitize('Batman: Dawn/of "Justice"?') == "Batman Dawnof Justice"
    assert sanitize("Trailing dots...") == "Trailing dots"


def test_movie_target():
    p = movie_target("/share/Movies/01-Ready", "Inception", 2010, ".avi")
    assert p == "/share/Movies/01-Ready/Inception (2010)/Inception (2010).avi"


def test_episode_target():
    p = episode_target("/share/TV Shows/01-Ready", "Dilbert", 1999, 1, 5, "Testing", ".mkv")
    assert p == "/share/TV Shows/01-Ready/Dilbert (1999)/Season 01/Dilbert (1999) - S01E05 - Testing.mkv"


def test_episode_specials_go_to_specials_folder():
    p = episode_target("/tv", "Show", 2020, 0, 3, "Behind the Scenes", ".mp4")
    assert p == "/tv/Show (2020)/Specials/Show (2020) - S00E03 - Behind the Scenes.mp4"


def test_episode_without_title():
    p = episode_target("/tv", "Show", 2020, 2, 4, None, ".mkv")
    assert p == "/tv/Show (2020)/Season 02/Show (2020) - S02E04.mkv"


def test_pick_roots():
    movies, tv = pick_roots(["/share/TV Shows/01-Ready", "/share/Movies/01-Ready"])
    assert movies == "/share/Movies/01-Ready" and tv == "/share/TV Shows/01-Ready"


def test_relocate_file_moves_and_creates_dir():
    calls = {}
    relocate_file("/a/old.avi", "/b/new/new.avi",
                  exists_fn=lambda p: p == "/a/old.avi",
                  makedirs_fn=lambda d, exist_ok: calls.update({"mkdir": d}),
                  move_fn=lambda s, d: calls.update({"move": (s, d)}))
    assert calls["mkdir"] == "/b/new"
    assert calls["move"] == ("/a/old.avi", "/b/new/new.avi")


def test_relocate_refuses_to_overwrite():
    with pytest.raises(FileExistsError):
        relocate_file("/a/old.avi", "/b/exists.avi", exists_fn=lambda p: True,
                      makedirs_fn=lambda d, exist_ok: None, move_fn=lambda s, d: None)


def test_build_target_dispatches():
    mv = build_target("/x/old.avi", "movie", {"title": "Heat", "year": 1995},
                      "/m", "/tv")
    assert mv == "/m/Heat (1995)/Heat (1995).avi"
    ep = build_target("/x/old.mkv", "episode",
                      {"title": "Show", "year": 2020, "season": 1, "episode": 2, "ep_title": "Pilot"},
                      "/m", "/tv")
    assert ep == "/tv/Show (2020)/Season 01/Show (2020) - S01E02 - Pilot.mkv"
