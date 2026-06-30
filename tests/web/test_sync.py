from src.web.sync import find_missing


def test_find_missing_returns_only_absent_and_reports_progress():
    paths = ["/a.mkv", "/b.mkv", "/c.mkv"]
    present = {"/a.mkv", "/c.mkv"}
    seen = []
    missing = find_missing(paths, lambda p: p in present,
                           max_workers=4, progress=lambda d, t: seen.append((d, t)))
    assert missing == ["/b.mkv"]
    assert seen[-1] == (3, 3)            # progress reaches total


def test_find_missing_empty_when_all_present():
    assert find_missing(["/a"], lambda p: True) == []


def test_find_missing_preserves_input_order():
    paths = [f"/{i}.mkv" for i in range(20)]
    present = {p for i, p in enumerate(paths) if i % 2 == 0}
    missing = find_missing(paths, lambda p: p in present, max_workers=8)
    assert missing == [p for i, p in enumerate(paths) if i % 2 == 1]
