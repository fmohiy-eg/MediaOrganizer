import json
import subprocess

_ENGLISH = {"eng", "en"}
_UNKNOWN_TAGS = {"", "und", "unknown", None}

# color_transfer hints → dynamic range profile
_HDR_TRANSFERS = {"smpte2084": "HDR10", "arib-std-b67": "HLG"}


def _derive_english(langs):
    if any(l in _ENGLISH for l in langs):
        return "yes"
    usable = [l for l in langs if l not in _UNKNOWN_TAGS]
    if not usable:
        return "unknown"
    return "no"


def parse_probe_json(data):
    fmt = data.get("format", {}) or {}
    streams = data.get("streams", []) or []
    video = next((s for s in streams if s.get("codec_type") == "video"), {})
    audios = [s for s in streams if s.get("codec_type") == "audio"]
    subtitles = [s for s in streams if s.get("codec_type") == "subtitle"]

    duration = fmt.get("duration")
    duration_ms = int(float(duration) * 1000) if duration else None
    bitrate = int(fmt["bit_rate"]) if fmt.get("bit_rate") else None
    container_title = (fmt.get("tags") or {}).get("title") or \
        ((video.get("tags") or {}).get("title") if video else None)

    transfer = video.get("color_transfer")
    color_profile = _HDR_TRANSFERS.get(transfer, "SDR") if video else None

    langs = []
    for a in audios:
        tag = (a.get("tags") or {}).get("language")
        langs.append(tag if tag is not None else "und")

    primary = audios[0] if audios else {}
    audio_profile = None
    if primary:
        ch = primary.get("channels")
        audio_profile = (f"{primary.get('codec_name', '?')} {ch}ch"
                         if ch else primary.get("codec_name"))

    sub_langs = []
    for s in subtitles:
        tag = (s.get("tags") or {}).get("language")
        sub_langs.append(tag if tag is not None else "und")
    # Embedded English subtitle: 'no' when there are no subtitle tracks at all.
    has_embedded_eng = "no" if not subtitles else _derive_english([l.lower() for l in sub_langs])

    return {
        "duration_ms": duration_ms,
        "bitrate": bitrate,
        "resolution_width": video.get("width") if video else None,
        "resolution_height": video.get("height") if video else None,
        "video_codec": video.get("codec_name") if video else None,
        "color_profile": color_profile,
        "audio_languages": json.dumps(langs),
        "has_english_audio": _derive_english([l.lower() for l in langs]),
        "audio_profile": audio_profile,
        "subtitle_languages": json.dumps(sub_langs),
        "has_embedded_english_subtitle": has_embedded_eng,
        "container_title": container_title,
    }


def probe_raw_json(filepath, timeout, retries, binary="ffprobe"):
    """Raw ffprobe format+streams JSON (incl. all tags), or None. Used for embedded
    episode-tag extraction; `probe_streams` parses this into stream fields."""
    cmd = [binary, "-v", "quiet", "-print_format", "json",
           "-show_format", "-show_streams", filepath]
    for _ in range(max(1, retries)):
        try:
            # ffprobe emits UTF-8 JSON; force UTF-8 decoding (Windows defaults to
            # cp1252, which crashes on non-ASCII metadata).
            result = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout,
                                    encoding="utf-8", errors="replace")
        except (subprocess.TimeoutExpired, FileNotFoundError):
            continue
        if result.returncode == 0 and result.stdout:
            try:
                return json.loads(result.stdout)
            except (json.JSONDecodeError, TypeError):
                return None
    return None


def probe_streams(filepath, timeout, retries, binary="ffprobe"):
    data = probe_raw_json(filepath, timeout, retries, binary)
    if not data:
        return None
    try:
        return parse_probe_json(data)
    except (TypeError, KeyError, ValueError):
        return None
