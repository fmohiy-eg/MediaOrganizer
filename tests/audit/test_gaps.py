from src.audit.gaps import analyze_gaps

EMAP = [
    {"season": 1, "episode": 1, "air_date": "2020-01-01"},
    {"season": 1, "episode": 2, "air_date": "2020-01-08"},
    {"season": 1, "episode": 3, "air_date": "2999-01-01"},  # future
    {"season": 1, "episode": 4, "air_date": None},          # unknown
]


def test_aired_and_absent_is_missing():
    out = analyze_gaps(EMAP, present={(1, 1)}, today="2026-06-22")
    assert (1, 2) in [(m["season"], m["episode"]) for m in out["missing"]]
    assert (1, 1) not in [(m["season"], m["episode"]) for m in out["missing"]]


def test_future_is_upcoming_not_missing():
    out = analyze_gaps(EMAP, present=set(), today="2026-06-22")
    ups = [(m["season"], m["episode"]) for m in out["upcoming"]]
    miss = [(m["season"], m["episode"]) for m in out["missing"]]
    assert (1, 3) in ups and (1, 3) not in miss


def test_unknown_airdate_ignored():
    out = analyze_gaps(EMAP, present=set(), today="2026-06-22")
    all_eps = [(m["season"], m["episode"]) for m in out["missing"] + out["upcoming"]]
    assert (1, 4) not in all_eps


def test_present_future_episode_not_listed():
    out = analyze_gaps(EMAP, present={(1, 3)}, today="2026-06-22")
    assert (1, 3) not in [(m["season"], m["episode"]) for m in out["upcoming"]]
