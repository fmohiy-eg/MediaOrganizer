from src.nfo import extract_ids

MOVIE_NFO = """<?xml version="1.0"?>
<movie>
  <title>Jurassic Park</title>
  <uniqueid type="tmdb" default="true">329</uniqueid>
  <uniqueid type="imdb">tt0107290</uniqueid>
  <tmdbid>329</tmdbid>
</movie>"""

TVSHOW_NFO = """<tvshow>
  <uniqueid type="tvdb">78581</uniqueid>
  <uniqueid type="tmdb">813</uniqueid>
  <tvdbid>78581</tvdbid>
</tvshow>"""


def test_extracts_movie_tmdb_and_imdb():
    ids = extract_ids(MOVIE_NFO)
    assert ids["tmdb"] == "329"
    assert ids["imdb"] == "tt0107290"


def test_extracts_tvshow_tvdb():
    assert extract_ids(TVSHOW_NFO)["tvdb"] == "78581"


def test_legacy_url_nfo():
    assert extract_ids("https://www.themoviedb.org/movie/329-jurassic-park")["tmdb"] == "329"
    assert extract_ids("http://thetvdb.com/?tab=series&id=78581")["tvdb"] == "78581"


def test_plain_tag_without_uniqueid():
    assert extract_ids("<tmdbid>1234</tmdbid>")["tmdb"] == "1234"


def test_empty_or_no_ids():
    assert extract_ids("") == {}
    assert extract_ids("<movie><title>No IDs here</title></movie>") == {}
