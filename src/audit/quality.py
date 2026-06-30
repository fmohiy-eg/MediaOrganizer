import re

_CODEC_RANK = {"av1": 3, "hevc": 2, "h265": 2, "h264": 1}


def _channels(audio_profile):
    if not audio_profile:
        return 0
    m = re.search(r"(\d+)\s*ch", audio_profile)
    return int(m.group(1)) if m else 0


def _metric(row, key):
    if key == "resolution":
        return (row.get("resolution_width") or 0) * (row.get("resolution_height") or 0)
    if key == "bitrate":
        return row.get("bitrate") or 0
    if key == "codec":
        return _CODEC_RANK.get((row.get("video_codec") or "").lower(), 0)
    if key == "audio_channels":
        return _channels(row.get("audio_profile"))
    return 0


def quality_score(row, priority):
    return tuple(_metric(row, key) for key in priority)


def group_variants(rows):
    groups = {}
    for r in rows:
        mid = r.get("metadata_id")
        if mid:
            groups.setdefault(mid, []).append(r)
    return {mid: members for mid, members in groups.items() if len(members) > 1}


def select_keeper(rows, priority):
    return max(rows, key=lambda r: quality_score(r, priority))
