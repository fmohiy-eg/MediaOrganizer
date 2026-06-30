from src.audit.subtitles import subtitle_flag


def test_has_subtitle_no_flag():
    assert subtitle_flag("no", True) is None


def test_no_english_audio_missing_sub_is_critical():
    assert subtitle_flag("no", False) == "critical"


def test_english_audio_missing_sub_is_minor():
    assert subtitle_flag("yes", False) == "minor"


def test_unknown_audio_missing_sub_needs_review():
    assert subtitle_flag("unknown", False) == "needs_review"
