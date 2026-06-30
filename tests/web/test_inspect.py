from src.web.inspect import format_duration, assess_versions, title_mismatch


def test_title_mismatch():
    assert title_mismatch("Inception", "Inception (2010) 1080p") is False   # filename in container
    assert title_mismatch("Inception 2010", "Inception") is False           # container in filename
    assert title_mismatch("Batman", "The Matrix") is True                   # clearly different
    assert title_mismatch("Heat", "") is False                              # nothing to compare
    assert title_mismatch("", "The Matrix") is False


def test_format_duration():
    assert format_duration(None) is None
    assert format_duration(125000) == "2:05"
    assert format_duration(3 * 3600 * 1000 + 5 * 60 * 1000) == "3:05:00"


def test_edition_marker_flags_versions():
    items = [{"duration_ms": 9000000, "edition": None},
             {"duration_ms": 9000000, "edition": "Director's Cut"}]
    out = assess_versions(items)
    assert out["possible_versions"] is True and "Director's Cut" in out["reason"]


def test_runtime_spread_flags_versions():
    items = [{"duration_ms": 120 * 60 * 1000, "edition": None},   # 120 min
             {"duration_ms": 135 * 60 * 1000, "edition": None}]   # 135 min -> 15 min apart
    assert assess_versions(items, deviation_seconds=120)["possible_versions"] is True


def test_matching_runtimes_are_true_duplicates():
    items = [{"duration_ms": 120 * 60 * 1000, "edition": None},
             {"duration_ms": 120 * 60 * 1000 + 30000, "edition": None}]  # 30s apart
    assert assess_versions(items, deviation_seconds=120)["possible_versions"] is False


def test_all_probes_failed_is_not_called_duplicate():
    items = [{"duration_ms": None, "edition": None},
             {"duration_ms": None, "edition": None}]
    out = assess_versions(items)
    assert out["possible_versions"] is False and "probe failed" in out["reason"].lower()


def test_incomplete_probe_is_cautious():
    items = [{"duration_ms": 7200000, "edition": None},
             {"duration_ms": None, "edition": None}]
    out = assess_versions(items)
    assert out["possible_versions"] is False and "incomplete" in out["reason"].lower()
