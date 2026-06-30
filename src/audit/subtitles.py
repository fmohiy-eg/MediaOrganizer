def subtitle_flag(has_english_audio, has_english_subtitle):
    if has_english_subtitle:
        return None
    if has_english_audio == "no":
        return "critical"
    if has_english_audio == "yes":
        return "minor"
    return "needs_review"
