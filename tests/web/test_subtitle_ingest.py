from src.web.subtitle_ingest import collision_safe_path


def test_no_collision_returns_target():
    assert collision_safe_path("/d/Movie.eng.srt", lambda p: False) == "/d/Movie.eng.srt"


def test_first_collision_gets_1():
    taken = {"/d/Movie.eng.srt"}
    assert collision_safe_path("/d/Movie.eng.srt", lambda p: p in taken) == "/d/Movie.eng.1.srt"


def test_sequential_until_free():
    taken = {"/d/Movie.eng.srt", "/d/Movie.eng.1.srt", "/d/Movie.eng.2.srt"}
    assert collision_safe_path("/d/Movie.eng.srt", lambda p: p in taken) == "/d/Movie.eng.3.srt"
