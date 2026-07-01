from src.database import init_db, get_connection
from src.repository import upsert_media_file
from src.metadata_repository import set_match
from src.web.services import library_kpis, variant_conflicts, unmatched_list


def _conn(tmp_path):
    db = str(tmp_path / "m.db"); init_db(db); return get_connection(db)


def _rec(path, mid=None, size=100, **over):
    base = dict(filepath=path, filename="v.mkv", extension=".mkv",
                parent_directory="/d", file_size_bytes=size, fast_hash="fh", os_hash="oh")
    if mid:
        base["metadata_id"] = mid
    base.update(over)
    return base


def test_kpis_counts(tmp_path):
    conn = _conn(tmp_path)
    upsert_media_file(conn, _rec("/d/a.mkv", size=1000))
    upsert_media_file(conn, _rec("/d/b.mkv", size=2000))
    set_match(conn, "/d/b.mkv", None, "unmatched")
    k = library_kpis(conn)
    assert k["total_items"] == 2
    assert k["total_bytes"] == 3000
    assert k["issue_count"] == 1


def test_probe_targets_excludes_video_ts_vob_fragments(tmp_path):
    from src.web.services import probe_targets
    conn = _conn(tmp_path)
    upsert_media_file(conn, _rec("/share/Movies/Heat (1995)/Heat (1995).mkv"))
    upsert_media_file(conn, _rec("/share/Movies/Heat (1995)/Heat (1995).avi"))   # dup format
    upsert_media_file(conn, _rec("/share/TV/Show/S1/ep/VIDEO_TS/VTS_01_2.VOB"))  # DVD fragment
    t = probe_targets(conn)
    assert "/share/Movies/Heat (1995)/Heat (1995).mkv" in t
    assert "/share/Movies/Heat (1995)/Heat (1995).avi" in t
    assert not any("VIDEO_TS" in p for p in t)


def test_admin_status_counts(tmp_path):
    from src.web.services import admin_status
    conn = _conn(tmp_path)
    upsert_media_file(conn, _rec("/share/Movies/a.mkv", duration_ms=1000))
    upsert_media_file(conn, _rec("/share/Movies/b.mkv"))               # not probed
    upsert_media_file(conn, _rec(r"\\nas\Movies\c.mkv"))               # backslash path
    set_match(conn, "/share/Movies/b.mkv", None, "unmatched")
    s = admin_status(conn)
    assert s["rows"] == 3 and s["probed"] == 1
    assert s["unmatched"] == 1 and s["backslash_paths"] == 1


def test_variant_conflicts_groups_same_name_diff_format(tmp_path):
    conn = _conn(tmp_path)
    # Same folder + same base name, different formats = one redundant-copy group.
    upsert_media_file(conn, dict(_rec("/d/Movie.mkv", mid="tmdb:1"), extension=".mkv"))
    upsert_media_file(conn, dict(_rec("/d/Movie.avi", mid="tmdb:1"), extension=".avi"))
    # A different title in the same folder is its own (non-)group.
    upsert_media_file(conn, dict(_rec("/d/Other.mkv", mid="tmdb:2"), extension=".mkv"))
    groups = variant_conflicts(conn)
    assert len(groups) == 1
    assert len(groups[0]["items"]) == 2


def test_legacy_duplicates(tmp_path):
    from src.web.services import legacy_duplicates
    conn = _conn(tmp_path)
    d = "/m/Movie (2010)"
    upsert_media_file(conn, dict(_rec(d + "/Movie (2010).mkv"), parent_directory=d,
                                 extension=".mkv", file_size_bytes=1000))
    upsert_media_file(conn, dict(_rec(d + "/Movie (2010).rm"), parent_directory=d,
                                 extension=".rm", file_size_bytes=300))
    # a lone legacy with NO modern sibling -> not a target
    d2 = "/m/Old (1999)"
    upsert_media_file(conn, dict(_rec(d2 + "/Old (1999).rmvb"), parent_directory=d2,
                                 extension=".rmvb", file_size_bytes=200))
    out = legacy_duplicates(conn)
    assert out["count"] == 1
    assert out["total_bytes"] == 300
    t = out["targets"][0]
    assert t["filepath"] == d + "/Movie (2010).rm" and t["keeper"].endswith("Movie (2010).mkv")


def test_episodes_of_same_series_do_not_group(tmp_path):
    conn = _conn(tmp_path)
    # Two DIFFERENT episodes sharing the series-level tvdb id must NOT be a dup group.
    s = "/share/TV Shows/01-Ready/Dilbert (1999)/Season 01/"
    upsert_media_file(conn, dict(_rec(s + "Dilbert - S01E01 - The Name.mkv", mid="tvdb:78581"),
                                 extension=".mkv"))
    upsert_media_file(conn, dict(_rec(s + "Dilbert - S01E02 - The Competition.mkv", mid="tvdb:78581"),
                                 extension=".mkv"))
    assert variant_conflicts(conn) == []
    # ...but two files of the SAME episode DO group.
    upsert_media_file(conn, dict(_rec(s + "Dilbert - S01E01 - The Name.avi", mid="tvdb:78581"),
                                 extension=".avi"))
    groups = variant_conflicts(conn)
    assert len(groups) == 1 and len(groups[0]["items"]) == 2


def test_variant_runtime_classification(tmp_path):
    conn = _conn(tmp_path)
    d = "/m/Show"
    # same runtime group
    upsert_media_file(conn, dict(_rec(d + "/A.mkv"), parent_directory=d, extension=".mkv",
                                 duration_ms=3600000))
    upsert_media_file(conn, dict(_rec(d + "/A.avi"), parent_directory=d, extension=".avi",
                                 duration_ms=3600500))   # 0.5s apart -> same
    # different runtime group
    upsert_media_file(conn, dict(_rec(d + "/B.mkv"), parent_directory=d, extension=".mkv",
                                 duration_ms=3600000))
    upsert_media_file(conn, dict(_rec(d + "/B.avi"), parent_directory=d, extension=".avi",
                                 duration_ms=4500000))   # 15 min apart -> different
    # unprobed group (one missing duration)
    upsert_media_file(conn, dict(_rec(d + "/C.mkv"), parent_directory=d, extension=".mkv",
                                 duration_ms=3600000))
    upsert_media_file(conn, dict(_rec(d + "/C.avi"), parent_directory=d, extension=".avi"))
    classes = {g["title"]: g["runtime_class"] for g in variant_conflicts(conn)}
    assert classes["A"] == "same"
    assert classes["B"] == "different"
    assert classes["C"] == "unknown"


def test_variant_keeper_prefers_modern_over_legacy(tmp_path):
    conn = _conn(tmp_path)
    # legacy .rm is bigger but should NOT be the keeper; modern .mkv wins
    upsert_media_file(conn, dict(_rec("/d/x.rm", mid="tmdb:5"), extension=".rm",
                                 file_size_bytes=900))
    upsert_media_file(conn, dict(_rec("/d/x.mkv", mid="tmdb:5"), extension=".mkv",
                                 file_size_bytes=500))
    g = variant_conflicts(conn)[0]
    keeper = next(i for i in g["items"] if i["is_keeper"])
    assert keeper["filepath"] == "/d/x.mkv"
    assert g["items"][0]["is_keeper"] is True          # keeper sorted first
    assert g["reclaimable_bytes"] == 900               # the legacy file's bytes


def test_unmatched_list(tmp_path):
    conn = _conn(tmp_path)
    upsert_media_file(conn, _rec("/d/a.mkv"))
    set_match(conn, "/d/a.mkv", None, "ambiguous")
    rows = unmatched_list(conn)
    assert rows[0]["filepath"] == "/d/a.mkv"


def test_missing_episodes(tmp_path):
    import json
    from src.metadata_repository import cache_metadata
    from src.web.services import missing_episodes
    conn = _conn(tmp_path)
    base = "/share/TV Shows/01-Ready/Show (2020)/Season 01/Show - S01E0{} - x.mkv"
    upsert_media_file(conn, dict(_rec(base.format(1)), metadata_id="tvdb:1"))
    upsert_media_file(conn, dict(_rec(base.format(2)), metadata_id="tvdb:1"))
    emap = [
        {"season": 0, "episode": 1, "air_date": "2019-01-01"},   # special -> excluded
        {"season": 1, "episode": 1, "air_date": "2020-01-01"},
        {"season": 1, "episode": 2, "air_date": "2020-01-08"},
        {"season": 1, "episode": 3, "air_date": "2020-01-15"},   # aired, NOT on disk -> missing
        {"season": 1, "episode": 4, "air_date": "2999-01-01"},   # future -> upcoming, not missing
    ]
    cache_metadata(conn, "tvdb:1", "Show", episode_map=json.dumps(emap))
    out = missing_episodes(conn, today="2026-06-23")
    assert len(out) == 1
    assert out[0]["missing_count"] == 1   # only S01E03; the S00 special is excluded
    assert (out[0]["missing"][0]["season"], out[0]["missing"][0]["episode"]) == (1, 3)
    assert out[0]["upcoming_count"] == 1


def test_english_subtitle_deficits(tmp_path):
    from src.repository import add_sidecar
    from src.web.services import english_subtitle_deficits
    conn = _conn(tmp_path)
    has = upsert_media_file(conn, _rec("/d/HasSub.mkv"))
    add_sidecar(conn, has, "/d/HasSub.eng.srt", "subtitle")
    upsert_media_file(conn, _rec("/d/NoSub.mkv"))
    deficits = [r["filepath"] for r in english_subtitle_deficits(conn)]
    assert deficits == ["/d/NoSub.mkv"]


def test_quality_variant_conflicts_flags_cross_folder_quality(tmp_path):
    from src.web.services import quality_variant_conflicts
    conn = _conn(tmp_path)
    # SAME movie in two different folders at different quality, both probed
    upsert_media_file(conn, _rec("/movies/Heat 1080p/Heat.mkv", mid="tmdb:1",
        item_type="movie", size=8_000_000_000, resolution_width=1920,
        resolution_height=1080, video_codec="hevc", bitrate=10_000_000, duration_ms=6_000_000))
    upsert_media_file(conn, _rec("/movies/Heat 720p/Heat.mkv", mid="tmdb:1",
        item_type="movie", size=3_000_000_000, resolution_width=1280,
        resolution_height=720, video_codec="h264", bitrate=4_000_000, duration_ms=6_000_000))
    # a different movie with a single copy -> not a conflict
    upsert_media_file(conn, _rec("/movies/Other/Other.mkv", mid="tmdb:2",
        item_type="movie", resolution_height=1080, duration_ms=5_000_000))
    res = quality_variant_conflicts(conn)
    assert res["group_count"] == 1
    g = res["groups"][0]
    assert g["items"][0]["is_keeper"] and g["items"][0]["resolution_height"] == 1080
    assert not g["items"][1]["is_keeper"]
    assert res["total_bytes"] == 3_000_000_000          # the 720p copy is reclaimable


def test_quality_variants_excludes_episodes_unprobed_and_same_folder(tmp_path):
    from src.web.services import quality_variant_conflicts
    conn = _conn(tmp_path)
    # episodes share ONE series-level id — must never be grouped as a quality conflict
    upsert_media_file(conn, _rec("/tv/Show/S01/Show - S01E01.mkv", mid="tvdb:9",
        item_type="episode", resolution_height=1080, duration_ms=1000))
    upsert_media_file(conn, _rec("/tv/Show/S01/Show - S01E02.mkv", mid="tvdb:9",
        item_type="episode", resolution_height=1080, duration_ms=1000))
    # same movie, same folder, format-only variants -> the Duplicates tab's job, not here
    upsert_media_file(conn, _rec("/m/Heat/Heat.mkv", mid="tmdb:3",
        item_type="movie", resolution_height=1080, duration_ms=1000))
    upsert_media_file(conn, _rec("/m/Heat/Heat.avi", mid="tmdb:3",
        item_type="movie", resolution_height=1080, duration_ms=1000))
    # cross-folder movie pair but UNPROBED (no quality data) -> excluded
    upsert_media_file(conn, _rec("/m/A 1080/A.mkv", mid="tmdb:4", item_type="movie"))
    upsert_media_file(conn, _rec("/m/A 720/A.mkv", mid="tmdb:4", item_type="movie"))
    assert quality_variant_conflicts(conn)["group_count"] == 0


def test_variant_conflicts_explains_keeper_choice(tmp_path):
    conn = _conn(tmp_path)
    # .wmv is a legacy format; .mkv is modern -> the reason should call that out,
    # plus the resolution and size comparison the ranking used.
    upsert_media_file(conn, _rec("/d/Heat.mkv", extension=".mkv",
                                 size=2_000_000_000, resolution_height=1080))
    upsert_media_file(conn, _rec("/d/Heat.wmv", extension=".wmv",
                                 size=700_000_000, resolution_height=720))
    g = variant_conflicts(conn)[0]
    assert g["items"][0]["extension"] == ".mkv"          # keeper sorted first
    reason = g["keeper_reason"]
    assert "modern format (.mkv vs .wmv)" in reason
    assert "1080p vs 720p" in reason
    assert "2.00 GB vs 700 MB" in reason


def test_variant_conflicts_keeper_reason_falls_back_when_equivalent(tmp_path):
    conn = _conn(tmp_path)  # same modern format, same resolution, same size
    upsert_media_file(conn, _rec("/d/A.mkv", extension=".mkv", size=1000, resolution_height=1080))
    upsert_media_file(conn, _rec("/d/A.mp4", extension=".mp4", size=1000, resolution_height=1080))
    reason = variant_conflicts(conn)[0]["keeper_reason"]
    assert "equivalent" in reason.lower()


def test_deficit_excludes_files_with_embedded_english_subtitle(tmp_path):
    from src.web.services import english_subtitle_deficits, english_subtitle_deficit_count
    conn = _conn(tmp_path)
    # embedded English track -> NOT a deficit (don't waste an OpenSubtitles download)
    upsert_media_file(conn, _rec("/d/Embedded.mkv", has_embedded_english_subtitle="yes"))
    # embedded subs present but not English -> still a deficit
    upsert_media_file(conn, _rec("/d/OtherLang.mkv", has_embedded_english_subtitle="no"))
    # never probed (NULL) -> still a deficit (we don't hide unknown gaps)
    upsert_media_file(conn, _rec("/d/Unprobed.mkv"))
    deficits = sorted(r["filepath"] for r in english_subtitle_deficits(conn))
    assert deficits == ["/d/OtherLang.mkv", "/d/Unprobed.mkv"]
    assert english_subtitle_deficit_count(conn) == 2


def test_flagged_audio_movies_filters_and_summarizes(tmp_path):
    from src.web.services import flagged_audio_movies
    conn = _conn(tmp_path)
    # qualifies: movie with an Arabic-tagged track
    upsert_media_file(conn, _rec("/share/Movies/Heat (1995)/Heat (1995).mkv",
                                 item_type="movie", file_size_bytes=1000,
                                 audio_languages='["eng", "ara"]'))
    # qualifies: short tag "ar"
    upsert_media_file(conn, _rec("/share/Movies/Salah (2020)/Salah (2020).mkv",
                                 item_type="movie", file_size_bytes=500,
                                 audio_languages='["ar"]'))
    # excluded: no Arabic track
    upsert_media_file(conn, _rec("/share/Movies/Eng (2001)/Eng (2001).mkv",
                                 item_type="movie", audio_languages='["eng"]'))
    # excluded: not yet probed (audio_languages NULL)
    upsert_media_file(conn, _rec("/share/Movies/Unprobed (2002)/Unprobed (2002).mkv",
                                 item_type="movie"))
    # excluded: TV episode even though Arabic-tagged
    upsert_media_file(conn, _rec("/share/TV Shows/Show/Season 01/Show - S01E01.mkv",
                                 item_type="episode", audio_languages='["ara"]'))
    # excluded: already moved into 02-ArabicReady
    upsert_media_file(conn, _rec("/share/Movies/02-ArabicReady/Done (1999)/Done (1999).mkv",
                                 item_type="movie", audio_languages='["ara"]'))
    out = flagged_audio_movies(conn, ["ara", "ar"], "02-ArabicReady")
    assert out["count"] == 2
    assert out["total_bytes"] == 1500
    titles = [it["title"] for it in out["items"]]
    assert titles == ["Heat (1995)", "Salah (2020)"]   # sorted by title
    assert out["items"][0]["audio_languages"] == ["eng", "ara"]


def test_flagged_audio_movies_disabled_when_no_languages(tmp_path):
    from src.web.services import flagged_audio_movies
    conn = _conn(tmp_path)
    upsert_media_file(conn, _rec("/share/Movies/Heat (1995)/Heat (1995).mkv",
                                 item_type="movie", file_size_bytes=1000,
                                 audio_languages='["eng", "ara"]'))
    out = flagged_audio_movies(conn, [], "02-ArabicReady")
    assert out == {"items": [], "count": 0, "total_bytes": 0}


def test_flagged_audio_movies_configurable_language(tmp_path):
    from src.web.services import flagged_audio_movies
    conn = _conn(tmp_path)
    upsert_media_file(conn, _rec("/share/Movies/Amelie (2001)/Amelie (2001).mkv",
                                 item_type="movie", file_size_bytes=800,
                                 audio_languages='["fre"]'))
    upsert_media_file(conn, _rec("/share/Movies/Heat (1995)/Heat (1995).mkv",
                                 item_type="movie", audio_languages='["ara"]'))
    out = flagged_audio_movies(conn, ["fre"], "02-FrenchReady")
    assert out["count"] == 1
    assert out["items"][0]["title"] == "Amelie (2001)"


def test_mismatched_videos_groups_by_folder(tmp_path):
    from src.web.services import mismatched_videos
    conn = _conn(tmp_path)
    P = "/share/Movies/01-Ready"
    # canonical movie: file base == folder name -> NOT a mismatch
    upsert_media_file(conn, _rec(P + "/Superman (1978)/Superman (1978).mkv", file_size_bytes=100))
    upsert_media_file(conn, _rec(P + "/Superman (1978)/Superman (1978).mp4", file_size_bytes=200))
    # two mismatched files in the same folder
    upsert_media_file(conn, _rec(P + "/Superman (1978)/Superman (1978) - CD1.mkv", file_size_bytes=10))
    upsert_media_file(conn, _rec(P + "/Superman (1978)/Superman (1978) - CD2.mkv", file_size_bytes=20))
    # a mismatch in a different folder
    upsert_media_file(conn, _rec(P + "/Heat (1995)/sample.mkv", file_size_bytes=5))
    # case-only difference (folder 'Casino (1995)' vs file 'casino (1995)') -> NOT flagged
    upsert_media_file(conn, _rec(P + "/Casino (1995)/casino (1995).mkv", file_size_bytes=7))
    # TV file (different share) must be excluded entirely
    upsert_media_file(conn, _rec("/share/TV Shows/01-Ready/Dilbert (1999)/Season 01/Dilbert - S01E01.mkv"))
    out = mismatched_videos(conn, "/share/Movies")
    assert out["group_count"] == 2
    assert out["file_count"] == 3
    assert out["total_bytes"] == 35
    # sorted by folder_name: Heat (1995) before Superman (1978)
    names = [g["folder_name"] for g in out["groups"]]
    assert names == ["Heat (1995)", "Superman (1978)"]
    superman = next(g for g in out["groups"] if g["folder_name"] == "Superman (1978)")
    assert [it["filename"] for it in superman["items"]] == \
        ["Superman (1978) - CD1.mkv", "Superman (1978) - CD2.mkv"]


def test_mismatched_videos_no_prefix_returns_empty(tmp_path):
    from src.web.services import mismatched_videos
    conn = _conn(tmp_path)
    upsert_media_file(conn, _rec("/share/Movies/01-Ready/X/y.mkv"))
    assert mismatched_videos(conn, None)["group_count"] == 0


def test_variant_conflicts_tags_kind(tmp_path):
    conn = _conn(tmp_path)
    # movie dup group (two formats in a movie folder)
    M = "/share/Movies/01-Ready/Heat (1995)"
    upsert_media_file(conn, dict(_rec(M + "/Heat (1995).mkv", mid="tmdb:949"), extension=".mkv"))
    upsert_media_file(conn, dict(_rec(M + "/Heat (1995).avi", mid="tmdb:949"), extension=".avi"))
    # tv dup group (two formats of one episode)
    T = "/share/TV Shows/01-Ready/Dilbert (1999)/Season 01"
    upsert_media_file(conn, dict(_rec(T + "/Dilbert - S01E01 - The Name.mkv", mid="tvdb:1"), extension=".mkv"))
    upsert_media_file(conn, dict(_rec(T + "/Dilbert - S01E01 - The Name.avi", mid="tvdb:1"), extension=".avi"))
    groups = variant_conflicts(conn)
    kinds = {g["title"]: g["kind"] for g in groups}
    # movie group labelled by folder base name, tv group by episode title
    movie_g = next(g for g in groups if "Heat" in g["title"])
    tv_g = next(g for g in groups if "Dilbert" in g["title"] or "Name" in g["title"])
    assert movie_g["kind"] == "movie"
    assert tv_g["kind"] == "tv"
