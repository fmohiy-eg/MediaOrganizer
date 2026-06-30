import re


def normalize_title(s):
    if not s:
        return ""
    s = re.sub(r"[^0-9a-zA-Z]+", " ", s.lower())
    return " ".join(s.split())


def is_contaminated(matched_series_title, folder_series_title):
    a = normalize_title(matched_series_title)
    b = normalize_title(folder_series_title)
    if not a or not b:
        return False
    return a != b
