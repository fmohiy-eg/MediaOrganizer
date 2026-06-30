from src.audit.contamination import normalize_title, is_contaminated


def test_normalize_ignores_case_and_punctuation():
    assert normalize_title("The Tom & Jerry Show!") == normalize_title("the tom  jerry show")


def test_same_series_not_contaminated():
    assert is_contaminated("Dilbert", "Dilbert") is False


def test_different_series_contaminated():
    assert is_contaminated("The Office", "Parks and Recreation") is True


def test_missing_data_not_flagged():
    assert is_contaminated("", "Dilbert") is False
    assert is_contaminated("Dilbert", None) is False
