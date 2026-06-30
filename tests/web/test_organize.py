from src.web.organize import (extract_episode_tags, episode_dest, subtitle_dest,
                               classify_sidecars, plan_folder, VIDEO_EXTS)

TV_ROOT = "/share/TV Shows/01-Ready"


# ---- extract_episode_tags ----------------------------------------------------

def _fmt(tags):
    return {"format": {"tags": tags}, "streams": []}


def test_extract_mp4_style_tags():
    pj = _fmt({"show": "Breaking Bad", "season_number": "2",
               "episode_id": "5", "title": "Breakage"})
    assert extract_episode_tags(pj) == {
        "show": "Breaking Bad", "season": 2, "episode": 5, "episode_title": "Breakage"}


def test_extract_is_case_insensitive():
    pj = _fmt({"SHOW": "Dexter", "Season_Number": "1", "EPISODE_ID": "3"})
    out = extract_episode_tags(pj)
    assert out["show"] == "Dexter" and out["season"] == 1 and out["episode"] == 3


def test_extract_episode_id_in_sxxexx_form():
    pj = _fmt({"show": "Lost", "season_number": "3", "episode_id": "S03E08"})
    assert extract_episode_tags(pj)["episode"] == 8


def test_extract_prefers_episode_sort_when_present():
    pj = _fmt({"show": "X", "season_number": "1", "episode_sort": "12", "episode_id": "S01E99"})
    assert extract_episode_tags(pj)["episode"] == 12


def test_extract_reads_stream_tags_as_fallback():
    pj = {"format": {"tags": {"show": "Y"}},
          "streams": [{"tags": {"season_number": "4", "episode_id": "2"}}]}
    out = extract_episode_tags(pj)
    assert out["season"] == 4 and out["episode"] == 2


def test_extract_returns_none_without_show():
    assert extract_episode_tags(_fmt({"season_number": "1", "episode_id": "2"})) is None


def test_extract_returns_none_without_season_or_episode():
    assert extract_episode_tags(_fmt({"show": "Z", "episode_id": "2"})) is None
    assert extract_episode_tags(_fmt({"show": "Z", "season_number": "1"})) is None


def test_extract_none_on_empty():
    assert extract_episode_tags(None) is None
    assert extract_episode_tags({}) is None


# ---- title-tag fallback (real case: everything packed into the 'title' tag) ----

def test_extract_parses_composite_title_tag():
    # Real HandBrake-tagged files: title = "<Show> SxxExx <Episode Title>"
    pj = _fmt({"title": "The West Wing S01E10 In Excelsis Deo"})
    assert extract_episode_tags(pj) == {
        "show": "The West Wing", "season": 1, "episode": 10,
        "episode_title": "In Excelsis Deo"}


def test_extract_composite_title_without_episode_title():
    pj = _fmt({"title": "The West Wing S06E01"})
    out = extract_episode_tags(pj)
    assert out["show"] == "The West Wing" and out["season"] == 6 and out["episode"] == 1
    assert out["episode_title"] is None


def test_extract_composite_title_nxnn_and_lowercase():
    assert extract_episode_tags(_fmt({"title": "Some Show 2x05 The One"})) == {
        "show": "Some Show", "season": 2, "episode": 5, "episode_title": "The One"}
    assert extract_episode_tags(_fmt({"title": "dexter s03e08 thing"}))["episode"] == 8


def test_extract_structured_tags_win_over_title_parse():
    pj = _fmt({"show": "Real Show", "season_number": "4", "episode_id": "2",
               "title": "Wrong Show S09E09 Nope"})
    out = extract_episode_tags(pj)
    assert out["show"] == "Real Show" and out["season"] == 4 and out["episode"] == 2


def test_extract_plain_title_without_sxxexx_is_none():
    assert extract_episode_tags(_fmt({"title": "Just A Movie Name"})) is None


# ---- dest builders -----------------------------------------------------------

def test_episode_dest_jellyfin_format():
    item = {"series": "Breaking Bad", "year": 2008, "season": 2, "episode": 5,
            "ep_title": "Breakage", "ext": ".mkv"}
    assert episode_dest(TV_ROOT, item) == \
        "/share/TV Shows/01-Ready/Breaking Bad (2008)/Season 02/Breaking Bad (2008) - S02E05 - Breakage.mkv"


def test_subtitle_dest_preserves_language_suffix():
    vdest = "/share/TV Shows/01-Ready/Breaking Bad (2008)/Season 02/Breaking Bad (2008) - S02E05 - Breakage.mkv"
    assert subtitle_dest(vdest, ".en.srt") == \
        "/share/TV Shows/01-Ready/Breaking Bad (2008)/Season 02/Breaking Bad (2008) - S02E05 - Breakage.en.srt"


# ---- classify_sidecars -------------------------------------------------------

def test_classify_sidecars_splits_subs_and_removes():
    vsrc = "/in/Show.S01E02.mkv"
    vdest = "/share/TV Shows/01-Ready/Show (2010)/Season 01/Show (2010) - S01E02 - T.mkv"
    files = [vsrc, "/in/Show.S01E02.en.srt", "/in/Show.S01E02.nfo",
             "/in/Show.S01E02.jpg", "/in/Unrelated.txt"]
    subs, removes = classify_sidecars(vsrc, files, vdest)
    assert subs == [{"src": "/in/Show.S01E02.en.srt",
                     "dest": "/share/TV Shows/01-Ready/Show (2010)/Season 01/Show (2010) - S01E02 - T.en.srt"}]
    assert set(removes) == {"/in/Show.S01E02.nfo", "/in/Show.S01E02.jpg"}


def test_classify_sidecars_requires_dot_boundary_not_prefix():
    # 'CD10' is a prefix of 'CD100' — must NOT grab CD100's sidecars (real bug).
    vsrc = "/in/Show - CD10.mp4"
    vdest = "/share/x/y.mp4"
    files = [vsrc, "/in/Show - CD10.nfo",
             "/in/Show - CD100.mp4", "/in/Show - CD100.nfo",
             "/in/Show - CD109.nfo"]
    subs, removes = classify_sidecars(vsrc, files, vdest)
    assert removes == ["/in/Show - CD10.nfo"]
    assert subs == []


def test_classify_sidecars_leaves_other_videos_alone():
    vsrc = "/in/Show.S01E02.mkv"
    vdest = "/share/x/y.mkv"
    files = [vsrc, "/in/Show.S01E02.avi"]   # a second video format, not a sidecar
    subs, removes = classify_sidecars(vsrc, files, vdest)
    assert subs == [] and removes == []


# ---- plan_folder -------------------------------------------------------------

def _identify(show, season, episode):
    if show != "Breaking Bad":
        return None
    return {"series": "Breaking Bad", "year": 2008, "metadata_id": "tvdb:81189",
            "ep_title": {(2, 5): "Breakage"}.get((season, episode))}


def test_plan_folder_matched_unmatched_and_no_tags():
    files = ["/in/a.mkv", "/in/b.mkv", "/in/c.mkv", "/in/a.srt", "/in/notes.txt"]
    probes = {
        "/in/a.mkv": _fmt({"show": "Breaking Bad", "season_number": "2", "episode_id": "5"}),
        "/in/b.mkv": _fmt({"show": "Unknown Show", "season_number": "1", "episode_id": "1"}),
        "/in/c.mkv": _fmt({"title": "no episode tags here"}),
    }
    plan = plan_folder("/in", walk_fn=lambda f: files,
                       probe_json_fn=lambda p: probes.get(p),
                       identify_fn=_identify, tv_root=TV_ROOT)
    by = {p["src"]: p for p in plan}
    assert by["/in/a.mkv"]["status"] == "matched"
    assert by["/in/a.mkv"]["dest"].endswith("Breaking Bad (2008) - S02E05 - Breakage.mkv")
    assert by["/in/a.mkv"]["subtitles"][0]["src"] == "/in/a.srt"
    assert by["/in/b.mkv"]["status"] == "unmatched"
    assert by["/in/c.mkv"]["status"] == "no_tags"
    # non-video files are not planned as their own rows
    assert "/in/a.srt" not in by and "/in/notes.txt" not in by


def test_plan_folder_dedupes_identify_per_show():
    files = ["/in/a.mkv", "/in/b.mkv"]
    probes = {"/in/a.mkv": _fmt({"show": "Breaking Bad", "season_number": "2", "episode_id": "5"}),
              "/in/b.mkv": _fmt({"show": "Breaking Bad", "season_number": "2", "episode_id": "6"})}
    calls = []
    def ident(show, s, e):
        calls.append(show)
        return _identify(show, s, e)
    plan_folder("/in", walk_fn=lambda f: files, probe_json_fn=lambda p: probes.get(p),
                identify_fn=ident, tv_root=TV_ROOT)
    # plan_folder itself does not cache (the web layer's identifier does); both call through
    assert calls == ["Breaking Bad", "Breaking Bad"]
