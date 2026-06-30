from src.audit.release_protection import is_protected


def _row(duration_ms=None, edition=None):
    return {"duration_ms": duration_ms, "edition": edition}


def test_edition_marker_protects():
    assert is_protected(_row(edition="Director's Cut"), 120, 120) is True


def test_duration_deviation_protects():
    # 130 min file vs 120 min theatrical = 600s deviation > 120s threshold
    assert is_protected(_row(duration_ms=130 * 60 * 1000), 120, 120) is True


def test_close_runtime_not_protected():
    # 121 min vs 120 min = 60s deviation < 120s threshold
    assert is_protected(_row(duration_ms=121 * 60 * 1000), 120, 120) is False


def test_unknown_data_not_protected():
    assert is_protected(_row(), None, 120) is False
