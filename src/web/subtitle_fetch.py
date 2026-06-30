"""Subtitle ingestion: turn a downloaded payload into a clean UTF-8 .srt next to the video.

Pure/injectable so it is testable without network or disk: the orchestration
(`fetch_and_ingest`) lives in the web layer; these helpers do the transform.
"""
import io
import os
import zipfile

from src.web.subtitle_ingest import collision_safe_path

_SUB_EXTS = (".srt", ".ass", ".ssa", ".sub", ".vtt")
_ENCODINGS = ("utf-8-sig", "utf-8", "cp1252", "latin-1")


def extract_subtitle_text(content):
    """Bytes (raw subtitle or a zip) -> decoded text string (normalized to UTF-8 on write)."""
    raw = content
    if content[:4] == b"PK\x03\x04":  # zip
        with zipfile.ZipFile(io.BytesIO(content)) as z:
            member = next((n for n in z.namelist() if n.lower().endswith(_SUB_EXTS)), None)
            if member is None:
                raise ValueError("zip contains no subtitle file")
            raw = z.read(member)
    for enc in _ENCODINGS:
        try:
            return raw.decode(enc)
        except UnicodeDecodeError:
            continue
    return raw.decode("latin-1")  # last resort, never raises


def target_subtitle_path(video_path, lang, exists_fn=os.path.exists):
    stem = os.path.splitext(video_path)[0]
    return collision_safe_path(f"{stem}.{lang}.srt", exists_fn)


def _default_write(path, data):
    with open(path, "wb") as f:
        f.write(data)


def ingest_subtitle(content, video_path, lang="eng",
                    exists_fn=os.path.exists, write_fn=_default_write):
    """Decode/unzip `content`, write UTF-8 `<video>.<lang>.srt` next to the video."""
    text = extract_subtitle_text(content)
    target = target_subtitle_path(video_path, lang, exists_fn)
    write_fn(target, text.encode("utf-8"))
    return {"target": target, "bytes_written": len(text.encode("utf-8"))}


def _best(results):
    # Prefer the most-downloaded, non-hearing-impaired English subtitle.
    return max(results, key=lambda r: ((r.get("hearing_impaired") is not True),
                                       (r.get("download_count") or 0)))


def fetch_and_ingest(client, token, video_local_path, search_params, http_get,
                     exists_fn=os.path.exists, write_fn=_default_write):
    """search -> pick best -> download (quota-aware) -> fetch link -> ingest UTF-8 .srt."""
    results = client.search(**search_params)
    if not results:
        return {"ok": False, "reason": "no_subtitles_found"}
    best = _best(results)
    dl = client.download(best["file_id"], token)
    if not dl.get("ok"):
        return {"ok": False, "reason": "quota_exhausted",
                "quota": dl.get("quota"), "message": dl.get("message")}
    content = http_get(dl["link"], timeout=60).content
    res = ingest_subtitle(content, video_local_path, lang="eng",
                          exists_fn=exists_fn, write_fn=write_fn)
    return {"ok": True, "target": res["target"], "quota": dl.get("quota"),
            "release": best.get("release")}


def to_local_path(path, path_map):
    """Translate a stored (NAS) path to a locally-accessible (SMB) path via prefix map."""
    norm = path.replace("\\", "/")
    for nas_prefix, local_prefix in sorted(path_map.items(), key=lambda kv: -len(kv[0])):
        np = nas_prefix.replace("\\", "/")
        if norm == np or norm.startswith(np.rstrip("/") + "/"):
            rest = norm[len(np):].lstrip("/")
            sep = "\\" if "\\" in local_prefix else "/"
            tail = rest.replace("/", sep)
            return local_prefix.rstrip("\\/") + sep + tail
    return path


def to_nas_path(path, path_map):
    """Inverse of to_local_path: translate a local (SMB) path back to its stored
    (NAS, forward-slash) form. Used so relocate/Arabic moves keep the catalog
    uniformly NAS-style instead of mixing in SMB backslash paths."""
    norm = path.replace("\\", "/")
    for nas_prefix, local_prefix in sorted(path_map.items(), key=lambda kv: -len(kv[1])):
        lp = local_prefix.replace("\\", "/").rstrip("/")
        if norm == lp or norm.startswith(lp + "/"):
            rest = norm[len(lp):].lstrip("/")
            np = nas_prefix.replace("\\", "/").rstrip("/")
            return np + "/" + rest if rest else np
    return path
