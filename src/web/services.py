import json
import os
import re

from src.parsing import parse_path
from src.audit.gaps import analyze_gaps
from src.audit.quality import group_variants, select_keeper, quality_score


def probe_targets(conn):
    """Files the runtime/audio probe should cover: every duplicate-group file plus
    every movie, EXCLUDING DVD `VIDEO_TS` `.vob` fragments — those can't be probed
    as standalone files, so they'd otherwise sit in 'remaining' forever. Shared by
    probe_dupes.py and the dashboard's probe-progress display so both agree."""
    dup = {it["filepath"] for g in variant_conflicts(conn) for it in g["items"]}
    movies = {r["filepath"] for r in conn.execute("SELECT filepath FROM media_files")
              if parse_path(r["filepath"])["item_type"] == "movie"}
    return {p for p in (dup | movies)
            if "/video_ts/" not in p.replace("\\", "/").lower()}


def admin_status(conn):
    """Cheap catalog health/freshness counts for the Admin tab."""
    def n(sql):
        return conn.execute(sql).fetchone()[0]
    return {
        "rows": n("SELECT COUNT(*) FROM media_files"),
        "probed": n("SELECT COUNT(*) FROM media_files WHERE duration_ms IS NOT NULL"),
        "unmatched": n("SELECT COUNT(*) FROM media_files "
                       "WHERE match_status IN ('unmatched','ambiguous')"),
        "episode_cache_series": n("SELECT COUNT(*) FROM metadata_cache "
                                  "WHERE episode_map IS NOT NULL"),
        "backslash_paths": n("SELECT COUNT(*) FROM media_files "
                             "WHERE instr(filepath, char(92)) > 0"),
    }


def library_kpis(conn):
    row = conn.execute(
        "SELECT COUNT(*) c, COALESCE(SUM(file_size_bytes),0) b FROM media_files").fetchone()
    issues = conn.execute(
        "SELECT COUNT(*) c FROM media_files WHERE match_status IN ('unmatched','ambiguous')"
    ).fetchone()["c"]
    reclaim = conn.execute(
        "SELECT COALESCE(SUM(file_size_bytes),0) b FROM media_files "
        "WHERE match_status = 'marked_delete'").fetchone()["b"]
    return {"total_items": row["c"], "total_bytes": row["b"],
            "issue_count": issues, "reclaimable_bytes": reclaim}


_LEGACY_EXTS = {".rm", ".rmvb", ".vob", ".mpg", ".mpeg", ".wmv", ".divx", ".flv", ".m2ts"}


def _keeper_rank(item):
    # No ffprobe data, so decide by: modern format first, then resolution, then size.
    modern = item["extension"].lower() not in _LEGACY_EXTS
    return (modern, item.get("resolution_height") or 0, item["file_size_bytes"])


def _human_size(b):
    b = b or 0
    return f"{b / 1e9:.2f} GB" if b >= 1e9 else f"{b / 1e6:.0f} MB"


def _keeper_reason(items):
    """One-line 'why the keeper won' comparing the keeper (items[0], already sorted
    keeper-first) to the top runner-up on the same axes _keeper_rank uses."""
    keeper, runner = items[0], items[1]
    bits = []
    k_ext = keeper["extension"].lstrip(".").lower()
    r_ext = runner["extension"].lstrip(".").lower()
    if keeper["extension"].lower() not in _LEGACY_EXTS and runner["extension"].lower() in _LEGACY_EXTS:
        bits.append(f"modern format (.{k_ext} vs .{r_ext})")
    kh, rh = keeper.get("resolution_height") or 0, runner.get("resolution_height") or 0
    if kh and rh and kh != rh:
        bits.append(f"{kh}p vs {rh}p")
    if keeper["file_size_bytes"] != runner["file_size_bytes"]:
        bits.append(f"{_human_size(keeper['file_size_bytes'])} vs {_human_size(runner['file_size_bytes'])}")
    if not bits:
        return "Copies look equivalent — keep whichever you prefer."
    return "Suggested keeper: " + "; ".join(bits) + "."


def _variant_key(filepath):
    """A true redundant-copy group = same folder + same base name, different extension
    (e.g. Movie.avi / Movie.mp4 / Movie.rm). This excludes multi-part files (CD1/CD2),
    different episodes, and unrelated files that merely share a metadata_id."""
    return (os.path.dirname(filepath), os.path.splitext(os.path.basename(filepath))[0])


def _runtime_class(items, deviation_seconds):
    """'same' if every copy has a runtime and they agree within tolerance; 'different'
    if any copy's runtime deviates; 'unknown' if any copy hasn't been probed yet."""
    durs = [it["duration_ms"] for it in items if it.get("duration_ms")]
    if len(durs) < len(items):
        return "unknown"
    if (max(durs) - min(durs)) / 1000.0 >= deviation_seconds:
        return "different"
    return "same"


def variant_conflicts(conn, deviation_seconds=120):
    """Groups of 2+ same-name files (different formats) in one folder, enriched for
    triage and sorted by reclaimable space. Each group is classified by runtime
    ('same'/'different'/'unknown') so the dashboard can split true duplicates from
    possible different versions."""
    rows = conn.execute(
        "SELECT m.metadata_id, m.filepath, m.extension, m.resolution_height, "
        "       m.video_codec, m.file_size_bytes, m.duration_ms, c.title "
        "FROM media_files m LEFT JOIN metadata_cache c ON c.metadata_id = m.metadata_id "
        "ORDER BY m.filepath").fetchall()
    groups = {}
    meta = {}
    for r in rows:
        key = _variant_key(r["filepath"])
        groups.setdefault(key, []).append(dict(r))
        meta[key] = (r["metadata_id"], r["title"])

    out = []
    for key, items in groups.items():
        if len(items) < 2:
            continue
        keeper = max(items, key=_keeper_rank)
        reclaimable = 0
        for it in items:
            it["format"] = it["extension"].lstrip(".").lower()
            it["is_legacy"] = it["extension"].lower() in _LEGACY_EXTS
            it["is_keeper"] = it["filepath"] == keeper["filepath"]
            if not it["is_keeper"]:
                reclaimable += it["file_size_bytes"]
        items.sort(key=_keeper_rank, reverse=True)  # keeper first
        mid, title = meta[key]
        # Show the shared base name as the group label (more useful than a raw id).
        label = title or os.path.splitext(os.path.basename(items[0]["filepath"]))[0]
        kind = "tv" if parse_path(items[0]["filepath"])["item_type"] == "episode" else "movie"
        out.append({"metadata_id": mid, "title": label, "items": items,
                    "reclaimable_bytes": reclaimable, "kind": kind,
                    "keeper_reason": _keeper_reason(items),
                    "runtime_class": _runtime_class(items, deviation_seconds)})
    out.sort(key=lambda g: g["reclaimable_bytes"], reverse=True)
    return out


_DEFAULT_PRIORITY = ("resolution", "bitrate", "codec", "audio_channels")

# Multi-part markers (CD1/CD2, Disc 1, part2, pt3, "1 of 2"). Anchored to the end of the
# filename stem so a part of a split film is recognised as ONE movie, not a rival copy.
_MULTIPART_RE = re.compile(
    r"(?:^|[\s._\-\(\[])(?:cd|dvd|disc|disk|part|pt)[\s._\-]?\d{1,2}"
    r"(?:\s*of\s*\d{1,2})?[\s._\-\)\]]*$", re.IGNORECASE)


def _is_multipart(filepath):
    """True if the filename looks like one part of a split movie (CD1/CD2/part2/disc1).
    Such files share a single metadata_id but are ONE film, so they must never be
    offered as rival quality copies."""
    stem = os.path.splitext(os.path.basename(filepath.replace("\\", "/")))[0]
    return bool(_MULTIPART_RE.search(stem))


# An episode token in the filename (SxxExx, 1x01, bare Enn/EpNN) or a season-style
# ancestor folder marks a file as TV. This catches the bare-`Enn` episodes that
# `parse_path` mis-reads as movies — critical because every episode of a show shares
# one series-level metadata_id, so they must never be grouped as one movie's copies.
_TV_TOKEN_RE = re.compile(
    r"(?:^|[\s._-])(?:s\d{1,2}e\d{1,3}|\d{1,2}x\d{2,3}|e\d{1,3}|ep\d{1,3}|episode\s*\d{1,3})"
    r"(?:[\s._-]|$)", re.IGNORECASE)
_SEASON_DIR_RE = re.compile(r"^(?:season\s*\d+|specials|s\d{1,2})$", re.IGNORECASE)


def _looks_like_tv(filepath):
    segs = [s for s in filepath.replace("\\", "/").split("/") if s]
    if any(_SEASON_DIR_RE.match(s) for s in segs[:-1]):
        return True
    stem = os.path.splitext(segs[-1])[0] if segs else ""
    return bool(_TV_TOKEN_RE.search(stem))


def _quality_label(row):
    parts = []
    if row.get("resolution_height"):
        parts.append(f"{row.get('resolution_width') or '?'}x{row['resolution_height']}")
    if row.get("video_codec"):
        parts.append(row["video_codec"])
    if row.get("bitrate"):
        parts.append(f"{row['bitrate'] // 1000}kbps")
    return " · ".join(parts) or "unprobed"


def quality_variant_conflicts(conn, priority=_DEFAULT_PRIORITY, deviation_seconds=120):
    """The SAME movie present at different quality (resolution/codec/bitrate) across
    DIFFERENT folders — e.g. a 720p copy in one folder and a 1080p in another. Invisible
    to the same-folder Duplicates tab. The highest-quality copy is the suggested keeper;
    the rest are reclaim candidates.

    SAFETY (guards hardened against a real 53k-row catalog): the stored `item_type`
    column is unpopulated (NULL from the inventory scan), and `parse_path` mis-reads
    bare-`Enn` episodes (no `Sxx`) as movies — and every episode of a show shares ONE
    series-level metadata_id. Grouping by id alone would offer a whole show's episodes
    as "quality variants of one movie" (the catastrophic false-delete CLAUDE.md warns
    about). So a group is surfaced ONLY when it is genuinely one work in several places,
    proven by data, not by the unreliable type flag:
      * tmdb:-namespaced id (movies are matched via TMDB; episodes carry tvdb:);
      * cross-folder — spans >= 2 distinct parent directories;
      * not TV — no season-style folder or episode token (see _looks_like_tv);
      * not multi-part — a split film (CD1/CD2) shares one id but is one movie;
      * single release year — an upstream mis-match sharing one id (e.g. "Solace"
        tagged as "Quantum of Solace") must not group two different films;
      * same runtime within `deviation_seconds` — distinct episodes differ in length,
        and an extended cut is a *different version*, not a redundant copy.
    Probed files only (ranking needs ffprobe data)."""
    # Fetch only members of ids that occur 2+ times (uses idx_media_metadata) — on a
    # large catalog almost every movie is single-copy, and /api/summary calls this on
    # every load, so filtering in SQL keeps the Python side to a handful of rows.
    rows = conn.execute(
        "SELECT m.filepath, m.parent_directory, m.metadata_id, m.duration_ms, "
        "       m.resolution_width, m.resolution_height, m.bitrate, m.video_codec, "
        "       m.audio_profile, m.file_size_bytes, c.title "
        "FROM media_files m LEFT JOIN metadata_cache c ON c.metadata_id = m.metadata_id "
        "WHERE m.metadata_id LIKE 'tmdb:%' AND m.duration_ms IS NOT NULL "
        "  AND m.metadata_id IN ("
        "    SELECT metadata_id FROM media_files "
        "    WHERE metadata_id LIKE 'tmdb:%' AND duration_ms IS NOT NULL "
        "    GROUP BY metadata_id HAVING COUNT(*) > 1)").fetchall()
    groups = group_variants([dict(r) for r in rows])
    out = []
    for mid, members in groups.items():
        # TV/episode guard, applied only to the few rows that share a tmdb id
        # (group_variants already dropped single-copy movies — the vast majority).
        members = [m for m in members
                   if not _looks_like_tv(m["filepath"])
                   and parse_path(m["filepath"])["item_type"] != "episode"]
        if len(members) < 2:
            continue
        # Cross-folder only — same-folder clusters are the Duplicates tab's job (and a
        # same-folder multi-file dump is usually episodes).
        if len({os.path.dirname(m["filepath"].replace("\\", "/")) for m in members}) < 2:
            continue
        if any(_is_multipart(m["filepath"]) for m in members):
            continue  # split film (CD1/CD2) — one movie, not rival copies
        years = {parse_path(m["filepath"])["year"] for m in members}
        years.discard(None)
        if len(years) > 1:
            continue  # different release years => different films (upstream mis-match)
        durs = [m["duration_ms"] for m in members]
        if (max(durs) - min(durs)) / 1000.0 >= deviation_seconds:
            continue  # different runtimes => distinct works or a different version
        keeper = select_keeper(members, priority)
        for m in members:
            m["is_keeper"] = m["filepath"] == keeper["filepath"]
            m["quality"] = _quality_label(m)
        members.sort(key=lambda m: quality_score(m, priority), reverse=True)
        reclaimable = sum(m["file_size_bytes"] for m in members if not m["is_keeper"])
        title = members[0].get("title") or os.path.basename(
            os.path.dirname(members[0]["filepath"].replace("\\", "/")))
        out.append({"metadata_id": mid, "title": title, "items": members,
                    "reclaimable_bytes": reclaimable})
    out.sort(key=lambda g: g["reclaimable_bytes"], reverse=True)
    return {"groups": out, "group_count": len(out),
            "total_bytes": sum(g["reclaimable_bytes"] for g in out)}


# A file is a subtitle "deficit" only if it has NEITHER an external English sidecar NOR
# an embedded English subtitle track. has_embedded_english_subtitle is NULL until the
# file is probed, so NULL/'no'/'unknown' still count as a deficit (we don't hide real
# gaps); only a confirmed 'yes' embedded track clears it. This stops the list (and the
# OpenSubtitles quota) from being wasted on files that already carry English subs.
_NO_ENG_SUB = (
    "NOT EXISTS (SELECT 1 FROM sidecar_assets s WHERE s.media_file_id = m.id "
    "AND s.asset_type = 'subtitle' AND ("
    "  lower(s.asset_path) LIKE '%.eng.%' OR lower(s.asset_path) LIKE '%.en.%' "
    "  OR lower(s.asset_path) LIKE '%english%')) "
    "AND (m.has_embedded_english_subtitle IS NULL "
    "     OR m.has_embedded_english_subtitle != 'yes')")


def english_subtitle_deficit_count(conn):
    return conn.execute(
        f"SELECT COUNT(*) c FROM media_files m WHERE {_NO_ENG_SUB}").fetchone()["c"]


def english_subtitle_deficits(conn, limit=200, offset=0):
    """Media files with no English subtitle sidecar (candidates for fetching)."""
    rows = conn.execute(
        "SELECT m.filepath, m.metadata_id, m.item_type, m.season_number, m.episode_number, "
        "       m.file_size_bytes "
        f"FROM media_files m WHERE {_NO_ENG_SUB} "
        "ORDER BY m.filepath LIMIT ? OFFSET ?", (limit, offset)).fetchall()
    return [dict(r) for r in rows]


def legacy_duplicates(conn):
    """Legacy-format files (.rm/.rmvb/.vob/...) that have a MODERN copy of the same
    title in the same folder — high-confidence safe cleanup. Biggest first."""
    rows = conn.execute(
        "SELECT filepath, extension, file_size_bytes FROM media_files").fetchall()
    groups = {}
    for r in rows:
        groups.setdefault(_variant_key(r["filepath"]), []).append(dict(r))

    targets, total = [], 0
    for items in groups.values():
        if len(items) < 2:
            continue
        exts = {i["extension"].lower() for i in items}
        if not (exts & _LEGACY_EXTS) or all(e in _LEGACY_EXTS for e in exts):
            continue  # need at least one legacy AND one modern
        keeper = max(items, key=_keeper_rank)  # modern beats legacy, so never a legacy file
        for it in items:
            if it["extension"].lower() in _LEGACY_EXTS and it["filepath"] != keeper["filepath"]:
                targets.append({"filepath": it["filepath"],
                                "format": it["extension"].lstrip(".").lower(),
                                "file_size_bytes": it["file_size_bytes"],
                                "keeper": keeper["filepath"]})
                total += it["file_size_bytes"]
    targets.sort(key=lambda t: -t["file_size_bytes"])
    return {"count": len(targets), "total_bytes": total, "targets": targets}


def missing_episodes(conn, today):
    """For each TV series with a cached episode_map, diff the aired episodes against
    what's on disk. Returns series with gaps, most-missing first."""
    series_ids = [r["metadata_id"] for r in conn.execute(
        "SELECT DISTINCT metadata_id FROM media_files WHERE metadata_id LIKE 'tvdb:%'")]
    out = []
    for sid in series_ids:
        cache = conn.execute(
            "SELECT title, episode_map FROM metadata_cache WHERE metadata_id = ?",
            (sid,)).fetchone()
        if not cache or not cache["episode_map"]:
            continue
        # Exclude Season 0 (Specials) — TVDB lists hundreds of recaps/webisodes that
        # nobody tracks as "missing episodes"; they'd bury the real gaps.
        emap = [e for e in json.loads(cache["episode_map"])
                if e.get("season") not in (0, None)]
        present = set()
        for r in conn.execute("SELECT filepath FROM media_files WHERE metadata_id = ?", (sid,)):
            p = parse_path(r["filepath"])
            if p["season_number"] is not None and p["episode_number"] is not None:
                present.add((p["season_number"], p["episode_number"]))
        gaps = analyze_gaps(emap, present, today)
        if gaps["missing"]:
            out.append({"metadata_id": sid, "title": cache["title"],
                        "missing": gaps["missing"], "missing_count": len(gaps["missing"]),
                        "upcoming_count": len(gaps["upcoming"])})
    out.sort(key=lambda s: -s["missing_count"])
    return out


def unmatched_list(conn):
    rows = conn.execute(
        "SELECT filepath, item_type, season_number, episode_number FROM media_files "
        "WHERE match_status IN ('unmatched','ambiguous')").fetchall()
    return [dict(r) for r in rows]


def flagged_audio_movies(conn, languages, staging_subdir):
    """Movies whose audio_languages intersects the configured `languages` (case-
    insensitive), excluding TV, not-yet-probed files, and anything already under
    `staging_subdir`. Returns an empty result when `languages` is empty (feature off)."""
    wanted = {str(l).lower() for l in (languages or [])}
    if not wanted:
        return {"items": [], "count": 0, "total_bytes": 0}
    rows = conn.execute(
        "SELECT filepath, file_size_bytes, audio_languages, audio_profile, duration_ms "
        "FROM media_files WHERE audio_languages IS NOT NULL").fetchall()
    items = []
    for r in rows:
        fp = r["filepath"]
        segments = fp.replace("\\", "/").split("/")
        if staging_subdir and staging_subdir in segments:
            continue
        if parse_path(fp)["item_type"] != "movie":
            continue
        langs = json.loads(r["audio_languages"] or "[]")
        if not any(str(l).lower() in wanted for l in langs):
            continue
        items.append({
            "filepath": fp,
            "title": os.path.basename(os.path.dirname(fp.replace("\\", "/"))),
            "size_bytes": r["file_size_bytes"],
            "audio_profile": r["audio_profile"],
            "audio_languages": langs,
            "duration_ms": r["duration_ms"],
        })
    items.sort(key=lambda it: it["title"].lower())
    return {"items": items, "count": len(items),
            "total_bytes": sum(it["size_bytes"] for it in items)}


def mismatched_videos(conn, movies_prefix):
    """Folders in the movies library that contain video file(s) whose base name
    (sans extension) != the folder name — e.g. 'Title (Year) - CD1.mkv' inside a
    'Title (Year)' folder, or a stray sample/episode. Grouped by folder so each
    can be reviewed and Fix-relocated one at a time. Scoped to movies_prefix (the
    movie share) so TV episodes, which never match their 'Season NN' folder, are
    excluded. movies_prefix is the NAS catalog prefix (e.g. '/share/Movies')."""
    if not movies_prefix:
        return {"groups": [], "group_count": 0, "file_count": 0, "total_bytes": 0}
    pref = movies_prefix.replace("\\", "/").rstrip("/") + "/"
    rows = conn.execute(
        "SELECT filepath, file_size_bytes FROM media_files").fetchall()
    groups = {}
    for r in rows:
        norm = r["filepath"].replace("\\", "/")
        if not norm.startswith(pref):
            continue
        folder, _, name = norm.rpartition("/")
        folder_name = folder.rpartition("/")[2]
        # case-insensitive: a file differing only by capitalisation is the same
        # title, not misplaced content — don't flag it.
        if os.path.splitext(name)[0].lower() == folder_name.lower():
            continue
        g = groups.setdefault(folder, {"folder": folder, "folder_name": folder_name,
                                       "items": [], "total_bytes": 0})
        g["items"].append({"filepath": r["filepath"], "filename": name,
                           "file_size_bytes": r["file_size_bytes"]})
        g["total_bytes"] += r["file_size_bytes"] or 0
    out = sorted(groups.values(), key=lambda g: g["folder_name"].lower())
    for g in out:
        g["file_count"] = len(g["items"])
    return {"groups": out, "group_count": len(out),
            "file_count": sum(len(g["items"]) for g in out),
            "total_bytes": sum(g["total_bytes"] for g in out)}
