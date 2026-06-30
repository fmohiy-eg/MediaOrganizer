import json
from src.probe import parse_probe_json

SAMPLE = {
    "format": {"duration": "5400.5", "bit_rate": "8000000"},
    "streams": [
        {"codec_type": "video", "codec_name": "hevc", "width": 1920, "height": 1080,
         "color_transfer": "smpte2084"},
        {"codec_type": "audio", "codec_name": "dts", "channels": 6,
         "tags": {"language": "eng"}},
        {"codec_type": "audio", "codec_name": "aac", "channels": 2,
         "tags": {"language": "ara"}},
    ],
}


def test_parse_core_video_fields():
    out = parse_probe_json(SAMPLE)
    assert out["duration_ms"] == 5400500
    assert out["bitrate"] == 8000000
    assert out["resolution_width"] == 1920
    assert out["resolution_height"] == 1080
    assert out["video_codec"] == "hevc"
    assert out["color_profile"] == "HDR10"


def test_parse_audio_languages_and_english_yes():
    out = parse_probe_json(SAMPLE)
    assert json.loads(out["audio_languages"]) == ["eng", "ara"]
    assert out["has_english_audio"] == "yes"


def test_english_no_when_all_non_english():
    data = {"format": {}, "streams": [
        {"codec_type": "audio", "codec_name": "aac", "channels": 2, "tags": {"language": "ara"}}]}
    assert parse_probe_json(data)["has_english_audio"] == "no"


def test_english_unknown_when_untagged():
    data = {"format": {}, "streams": [
        {"codec_type": "audio", "codec_name": "aac", "channels": 2, "tags": {"language": "und"}},
        {"codec_type": "audio", "codec_name": "aac", "channels": 2}]}
    assert parse_probe_json(data)["has_english_audio"] == "unknown"


def test_audio_profile_primary_track():
    out = parse_probe_json(SAMPLE)
    assert out["audio_profile"] == "dts 6ch"


def test_embedded_english_subtitle_detected():
    data = {"format": {}, "streams": [
        {"codec_type": "video", "codec_name": "hevc"},
        {"codec_type": "subtitle", "codec_name": "subrip", "tags": {"language": "eng"}},
        {"codec_type": "subtitle", "codec_name": "subrip", "tags": {"language": "ara"}}]}
    out = parse_probe_json(data)
    assert json.loads(out["subtitle_languages"]) == ["eng", "ara"]
    assert out["has_embedded_english_subtitle"] == "yes"


def test_no_subtitle_streams_means_no_embedded_english():
    out = parse_probe_json(SAMPLE)  # SAMPLE has video + audio, no subtitle streams
    assert json.loads(out["subtitle_languages"]) == []
    assert out["has_embedded_english_subtitle"] == "no"


def test_container_title_extracted():
    data = {"format": {"tags": {"title": "The Matrix"}}, "streams": []}
    assert parse_probe_json(data)["container_title"] == "The Matrix"
    assert parse_probe_json(SAMPLE)["container_title"] is None   # no title tag


def test_untagged_embedded_subtitle_is_unknown():
    data = {"format": {}, "streams": [
        {"codec_type": "subtitle", "codec_name": "subrip", "tags": {"language": "und"}},
        {"codec_type": "subtitle", "codec_name": "subrip"}]}
    assert parse_probe_json(data)["has_embedded_english_subtitle"] == "unknown"
