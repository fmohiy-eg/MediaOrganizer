from src.audit.contamination import normalize_title


def decide_match(candidates, parsed):
    if not candidates:
        return {"status": "unmatched", "metadata_id": None}
    if len(candidates) == 1:
        return {"status": "matched", "metadata_id": candidates[0]["metadata_id"]}
    year = parsed.get("year")
    year_hits = [c for c in candidates if year is not None and c.get("year") == year]
    if len(year_hits) == 1:
        return {"status": "matched", "metadata_id": year_hits[0]["metadata_id"]}
    # A unique exact title match is high-confidence, not a guess — accept it. This
    # rescues real shows like "Barry" that otherwise return many candidates. But
    # only for episodes (series names are reliable folder context) or when a year
    # corroborates — a bare no-year *movie* title is usually a junk-folder artifact
    # (e.g. "Specials", "Music Videos") that can exact-match an obscure title.
    want = normalize_title(parsed.get("movie_title") or parsed.get("series_title") or "")
    allow_exact = year is not None or bool(parsed.get("series_title"))
    if want and allow_exact:
        pool = year_hits or candidates
        exact = [c for c in pool if normalize_title(c.get("title") or "") == want]
        if len(exact) == 1:
            return {"status": "matched", "metadata_id": exact[0]["metadata_id"]}
    return {"status": "ambiguous", "metadata_id": None}


def match_one(parsed, provider):
    try:
        candidates = provider.search(parsed)
    except Exception:
        return {"status": "unmatched", "metadata_id": None}
    return decide_match(candidates or [], parsed)
