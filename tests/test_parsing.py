from src.parsing import parse_path

M = r"\\host\Movies\01-Ready\Resident Evil - Damnation (2012)\Resident Evil - Damnation (2012).mp4"
TV1 = r"\\host\TV Shows\01-Ready\Dilbert (1999)\Season 01\Dilbert - S01E01 - The Name.avi"
TV2 = r"\\host\TV Shows\01-Ready\The Avengers (1961)\Season 2\The Avengers (1961) - 2x09 - The Sell-Out.mkv"
SPECIAL = (r"\\host\TV Shows\01-Ready\Disney's House of Mouse (2001)\Specials"
           r"\Disney's House of Mouse (2001) - 0x01 - Mickey's Magical Christmas - Snowed in at the House of Mouse.mp4")
DOUBLE = r"\\host\TV Shows\01-Ready\Calls (US) (2021)\Season 1\Calls (US) - S01E03 - Whatever.mp4"


def test_movie_title_and_year():
    out = parse_path(M)
    assert out["item_type"] == "movie"
    assert out["movie_title"] == "Resident Evil - Damnation"
    assert out["year"] == 2012


def test_episode_sxxexx():
    out = parse_path(TV1)
    assert out["item_type"] == "episode"
    assert out["series_title"] == "Dilbert"
    assert out["year"] == 1999
    assert (out["season_number"], out["episode_number"]) == (1, 1)
    assert out["episode_title"] == "The Name"


def test_episode_flat_multiplier_with_hyphen_title():
    out = parse_path(TV2)
    assert (out["season_number"], out["episode_number"]) == (2, 9)
    assert out["episode_title"] == "The Sell-Out"
    assert out["series_title"] == "The Avengers"


def test_specials_season_zero_and_title_with_dashes():
    out = parse_path(SPECIAL)
    assert out["season_number"] == 0
    assert out["episode_number"] == 1
    # Everything after the token is the title, dashes preserved
    assert out["episode_title"] == "Mickey's Magical Christmas - Snowed in at the House of Mouse"


def test_double_parens_title():
    out = parse_path(DOUBLE)
    assert out["series_title"] == "Calls (US)"
    assert out["year"] == 2021
    assert (out["season_number"], out["episode_number"]) == (1, 3)


def test_multi_episode_span():
    p = r"\\host\TV Shows\01-Ready\Show (2020)\Season 1\Show - S01E01-E02 - Pilot.mkv"
    out = parse_path(p)
    assert out["episode_number"] == 1 and out["episode_number_end"] == 2


def test_edition_marker_detected():
    p = r"\\host\Movies\01-Ready\Blade Runner (1982)\Blade Runner (1982) Director's Cut.mkv"
    out = parse_path(p)
    assert out["edition"] == "Director's Cut"
