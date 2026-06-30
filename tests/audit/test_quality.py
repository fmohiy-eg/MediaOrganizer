from src.audit.quality import quality_score, group_variants, select_keeper

PRI = ["resolution", "bitrate", "codec", "audio_channels"]


def _row(mid, w, h, br, codec, prof="aac 2ch"):
    return {"metadata_id": mid, "resolution_width": w, "resolution_height": h,
            "bitrate": br, "video_codec": codec, "audio_profile": prof}


def test_higher_resolution_scores_higher():
    hd = _row("tmdb:1", 1920, 1080, 5_000_000, "h264")
    sd = _row("tmdb:1", 720, 480, 5_000_000, "h264")
    assert quality_score(hd, PRI) > quality_score(sd, PRI)


def test_codec_breaks_tie_when_resolution_and_bitrate_equal():
    av1 = _row("tmdb:1", 1920, 1080, 5_000_000, "av1")
    h264 = _row("tmdb:1", 1920, 1080, 5_000_000, "h264")
    assert quality_score(av1, PRI) > quality_score(h264, PRI)


def test_group_variants_only_multi():
    rows = [_row("tmdb:1", 1920, 1080, 5, "h264"),
            _row("tmdb:1", 720, 480, 4, "h264"),
            _row("tmdb:2", 1920, 1080, 5, "h264")]
    groups = group_variants(rows)
    assert set(groups) == {"tmdb:1"} and len(groups["tmdb:1"]) == 2


def test_select_keeper_picks_best():
    rows = [_row("tmdb:1", 720, 480, 4_000_000, "h264"),
            _row("tmdb:1", 3840, 2160, 20_000_000, "hevc")]
    assert select_keeper(rows, PRI)["resolution_height"] == 2160
