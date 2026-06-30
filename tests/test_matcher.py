from src.matcher import decide_match, match_one


def test_single_candidate_matched():
    out = decide_match([{"metadata_id": "tmdb:1", "title": "X", "year": 2012}], {"year": 2012})
    assert out == {"status": "matched", "metadata_id": "tmdb:1"}


def test_no_candidates_unmatched():
    assert decide_match([], {"year": 2012})["status"] == "unmatched"


def test_year_disambiguates():
    cands = [{"metadata_id": "tmdb:1", "title": "X", "year": 1999},
             {"metadata_id": "tmdb:2", "title": "X", "year": 2012}]
    out = decide_match(cands, {"year": 2012})
    assert out == {"status": "matched", "metadata_id": "tmdb:2"}


def test_ambiguous_when_year_cannot_disambiguate():
    cands = [{"metadata_id": "tmdb:1", "title": "X", "year": 2012},
             {"metadata_id": "tmdb:2", "title": "X", "year": 2012}]
    assert decide_match(cands, {"year": 2012})["status"] == "ambiguous"


def test_unique_exact_title_resolves_ambiguity_no_year():
    cands = [{"metadata_id": "tvdb:1", "title": "Barry", "year": 2018},
             {"metadata_id": "tvdb:2", "title": "The Drew Barrymore Show", "year": 2020}]
    out = decide_match(cands, {"series_title": "Barry", "year": None})
    assert out == {"status": "matched", "metadata_id": "tvdb:1"}


def test_exact_title_within_same_year_candidates():
    cands = [{"metadata_id": "tvdb:1", "title": "Extreme Makeover: Home Edition", "year": 2004},
             {"metadata_id": "tvdb:2", "title": "Extreme Makeover: Home Edition: How'd They Do That?", "year": 2004}]
    out = decide_match(cands, {"series_title": "Extreme Makeover Home Edition", "year": 2004})
    assert out["status"] == "matched" and out["metadata_id"] == "tvdb:1"


def test_no_exact_title_stays_ambiguous():
    cands = [{"metadata_id": "tmdb:1", "title": "Open Season 3", "year": 2010},
             {"metadata_id": "tmdb:2", "title": "Actors Short Films Season 3", "year": 2023}]
    assert decide_match(cands, {"movie_title": "Season 3", "year": None})["status"] == "ambiguous"


def test_two_exact_titles_stay_ambiguous():
    cands = [{"metadata_id": "a", "title": "X", "year": 2001},
             {"metadata_id": "b", "title": "X", "year": 2002}]
    assert decide_match(cands, {"movie_title": "X", "year": None})["status"] == "ambiguous"


class _Provider:
    def __init__(self, result): self._r = result
    def search(self, parsed): return self._r


def test_match_one_uses_provider():
    p = _Provider([{"metadata_id": "tvdb:9", "title": "Y", "year": 1999}])
    assert match_one({"year": 1999}, p)["metadata_id"] == "tvdb:9"


def test_match_one_provider_error_is_unmatched():
    class Boom:
        def search(self, parsed): raise RuntimeError("network")
    assert match_one({"year": 1999}, Boom())["status"] == "unmatched"
