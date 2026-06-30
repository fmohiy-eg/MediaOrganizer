from src.audit.duplicates import confirm_exact_duplicates


def _row(path, fast):
    return {"filepath": path, "fast_hash": fast}


def test_fast_hash_collision_not_confirmed():
    rows = [_row("/a", "FH"), _row("/b", "FH")]   # same fast hash...
    full = {"/a": "AAA", "/b": "BBB"}             # ...different full hashes
    assert confirm_exact_duplicates(rows, lambda p: full[p]) == []


def test_true_duplicates_confirmed():
    rows = [_row("/a", "FH"), _row("/b", "FH"), _row("/c", "OTHER")]
    full = {"/a": "SAME", "/b": "SAME", "/c": "X"}
    groups = confirm_exact_duplicates(rows, lambda p: full[p])
    assert groups == [["/a", "/b"]]


def test_singletons_never_hashed():
    calls = []
    rows = [_row("/only", "UNIQUE")]
    confirm_exact_duplicates(rows, lambda p: calls.append(p))
    assert calls == []  # no full hash computed for a lone candidate
