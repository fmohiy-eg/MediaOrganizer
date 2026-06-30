import os
import posixpath
import shutil
import sqlite3
import subprocess
import sys
import threading
from datetime import date, datetime


def _spawn_probe():
    """Launch probe_dupes.py as a detached process so it survives requests/restarts."""
    here = os.path.dirname(os.path.abspath(__file__))
    return subprocess.Popen(
        [sys.executable, "probe_dupes.py", "config.yaml"], cwd=here,
        creationflags=getattr(subprocess, "DETACHED_PROCESS", 0),
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

import requests
from fastapi import FastAPI, HTTPException
from fastapi.responses import HTMLResponse, JSONResponse
from pydantic import BaseModel

from src.database import get_connection, db_write_lock
from src.repository import delete_media_by_path, get_media_row, all_media_paths
from src.parsing import parse_path
from src.web.services import (library_kpis, variant_conflicts, unmatched_list,
                              english_subtitle_deficits, english_subtitle_deficit_count,
                              missing_episodes, legacy_duplicates, arabic_audio_movies,
                              mismatched_videos, admin_status, probe_targets)
from src.web.sync import find_missing
from src.web.subtitle_fetch import fetch_and_ingest, to_local_path, to_nas_path
from src.web.inspect import format_duration, assess_versions, title_mismatch
from src.web.relocate import pick_roots, build_target, relocate_file, arabic_target
from src.web import organize as organize_mod
from src.repository import update_media_path, upsert_media_file
from src.opensubtitles_client import OpenSubtitlesClient
from src.metadata_client import TmdbClient, TvdbClient
from src.metadata_repository import set_match, cache_metadata
from src.matcher import decide_match
from src.probe import probe_streams, probe_raw_json
from src.quarantine.cascade import build_deletion_plan
from src.quarantine.mover import plan_moves, execute_plan


class DeleteBody(BaseModel):
    filepath: str
    confirm: bool = False


class LoginBody(BaseModel):
    username: str
    password: str


class FetchBody(BaseModel):
    filepath: str


class ProbeBody(BaseModel):
    filepaths: list[str]


class ConfirmBody(BaseModel):
    confirm: bool = False


class PlayBody(BaseModel):
    filepath: str


class RelocateBody(BaseModel):
    filepath: str
    kind: str          # 'movie' | 'episode'
    details: dict      # {title, year, metadata_id, [season, episode, ep_title]}
    confirm: bool = False


class ArabicBody(BaseModel):
    filepath: str
    confirm: bool = False


class OrganizeScanBody(BaseModel):
    folder: str


class OrganizeApplyBody(BaseModel):
    items: list[dict]          # the user-SELECTED 'matched' rows from /api/organize/scan
    folder: str = ""           # source folder (needed for leftover cleanup)
    cleanup: bool = False       # also quarantine leftovers + remove the emptied folder
    confirm: bool = False


def _walk_files(folder):
    """All file paths under `folder`, recursively (forward-slash normalized)."""
    out = []
    for root, _dirs, names in os.walk(folder):
        for n in names:
            out.append(os.path.join(root, n).replace("\\", "/"))
    return out


def _scandir(folder):
    """Immediate children of `folder` (files AND dirs), forward-slash normalized."""
    return [os.path.join(folder, n).replace("\\", "/") for n in os.listdir(folder)]


def launch_player(local_path, player_bin=None):
    """Open a file in the configured/resolved player, else the OS default association.
    Runs on the machine hosting the dashboard. `player_bin` is the resolved VLC (or
    other) binary, or None to use the platform default. Cross-platform."""
    if player_bin:
        subprocess.Popen([player_bin, local_path])
        return
    if sys.platform == "win32":
        os.startfile(local_path)  # Windows default player for this file type
    elif sys.platform == "darwin":
        subprocess.Popen(["open", local_path])
    else:
        subprocess.Popen(["xdg-open", local_path])


def _search_params(filepath, row):
    """Build OpenSubtitles search params from a media row (tmdb for movies, query for TV)."""
    p = parse_path(filepath)
    mid = row["metadata_id"] or ""
    if p["item_type"] == "movie" and mid.startswith("tmdb:"):
        return {"tmdb_id": int(mid.split(":")[1])}
    params = {"query": p.get("series_title") or p.get("movie_title") or ""}
    if p.get("season_number") is not None:
        params["season_number"] = p["season_number"]
    if p.get("episode_number") is not None:
        params["episode_number"] = p["episode_number"]
    return params


def create_app(db_path, quarantine_path, os_api_key="", path_map=None,
               os_client=None, http_get=requests.get,
               ffprobe_binary="ffprobe", probe_fn=probe_streams,
               duration_deviation_seconds=120, player_fn=None, player_binary=None,
               tmdb_api_key="", tvdb_api_key="", tmdb_client=None, tvdb_client=None,
               media_paths=None, move_fn=shutil.move, makedirs_fn=os.makedirs,
               exists_fn=os.path.exists, build_id=None,
               probe_json_fn=probe_raw_json, walk_fn=_walk_files,
               getsize_fn=os.path.getsize, scandir_fn=_scandir, rmdir_fn=os.rmdir,
               spawn_probe_fn=_spawn_probe):
    app = FastAPI(title="NAS Media Organizer")
    build_id = build_id or "dev"
    path_map = path_map or {}
    media_paths = media_paths or []
    if player_fn is None:
        player_fn = lambda p: launch_player(p, player_binary)
    client = os_client or OpenSubtitlesClient(os_api_key)
    tmdb = tmdb_client or TmdbClient(tmdb_api_key)
    tvdb = tvdb_client or TvdbClient(tvdb_api_key)
    session = {"os_token": None}  # in-memory only; never persisted

    def conn():
        return get_connection(db_path)

    @app.get("/", response_class=HTMLResponse)
    def index():
        # No-store so the browser never serves a stale copy of the UI after an update.
        # The build stamp lets the user confirm a *server* restart took effect too
        # (uvicorn loads the app once; editing files alone won't reload a running server).
        html = _INDEX_HTML.replace("__BUILD_ID__", build_id)
        return HTMLResponse(html, headers={"Cache-Control": "no-store"})

    @app.get("/api/kpis")
    def kpis():
        return library_kpis(conn())

    @app.get("/api/summary")
    def summary():
        c = conn()
        groups = variant_conflicts(c)
        return {
            "kpis": library_kpis(c),
            "duplicate_groups": len(groups),
            "duplicate_reclaimable_bytes": sum(g["reclaimable_bytes"] for g in groups),
            "subtitle_deficits": english_subtitle_deficit_count(c),
            "unmatched": len(unmatched_list(c)),
            "arabic_movies": arabic_audio_movies(c)["count"],
        }

    @app.get("/api/variants")
    def variants():
        return variant_conflicts(conn())

    @app.post("/api/variant/probe")
    def variant_probe(body: ProbeBody):
        """On-demand ffprobe of a group's files, with a different-versions assessment."""
        items = []
        for fp in body.filepaths:
            local = to_local_path(fp, path_map)
            probed = probe_fn(local, 30, 1, ffprobe_binary) or {}
            w, h = probed.get("resolution_width"), probed.get("resolution_height")
            parsed = parse_path(fp)
            name_title = (parsed.get("movie_title") or parsed.get("episode_title")
                          or parsed.get("series_title"))
            container_title = probed.get("container_title")
            items.append({
                "filepath": fp,
                "duration_ms": probed.get("duration_ms"),
                "duration_label": format_duration(probed.get("duration_ms")),
                "resolution": f"{w}x{h}" if w and h else None,
                "video_codec": probed.get("video_codec"),
                "audio_profile": probed.get("audio_profile"),
                "subtitle_languages": probed.get("subtitle_languages"),
                "embedded_english_subtitle": probed.get("has_embedded_english_subtitle"),
                "container_title": container_title,
                "title_mismatch": title_mismatch(name_title, container_title),
                "edition": parsed.get("edition"),
            })
        assessment = assess_versions(items, duration_deviation_seconds)
        return {"items": items, **assessment}

    @app.get("/api/file/subs")
    def file_subs(filepath: str):
        """Probe one file for EMBEDDED subtitle tracks (so a download isn't wasted)."""
        probed = probe_fn(to_local_path(filepath, path_map), 30, 1, ffprobe_binary) or {}
        return {
            "filepath": filepath,
            "subtitle_languages": probed.get("subtitle_languages"),
            "embedded_english_subtitle": probed.get("has_embedded_english_subtitle"),
        }

    @app.get("/api/unmatched")
    def unmatched():
        return unmatched_list(conn())

    @app.get("/api/missing")
    def missing():
        return missing_episodes(conn(), today=date.today().isoformat())

    @app.post("/api/play")
    def play(body: PlayBody):
        if get_media_row(conn(), body.filepath) is None:
            raise HTTPException(status_code=404, detail="Unknown file")
        local = to_local_path(body.filepath, path_map)
        if not os.path.exists(local):
            raise HTTPException(status_code=404, detail=f"Not reachable: {local}")
        player_fn(local)
        return {"ok": True, "opened": local}

    # --- Relocate / fix misidentified file ---
    @app.get("/api/relocate/search")
    def relocate_search(kind: str, query: str):
        provider = tmdb if kind == "movie" else tvdb
        parsed = {"movie_title": query} if kind == "movie" else {"series_title": query}
        try:
            return provider.search(parsed)
        except Exception:
            raise HTTPException(status_code=502, detail="Lookup failed")

    @app.get("/api/relocate/episode")
    def relocate_episode(series_id: str, season: int, episode: int):
        try:
            eps = tvdb.get_episodes(series_id.split(":")[-1])
        except Exception:
            raise HTTPException(status_code=502, detail="TVDB lookup failed")
        match = next((e for e in eps if e["season"] == season and e["episode"] == episode), None)
        return {"ep_title": match.get("name") if match else None}

    def _require_row(c, filepath):
        if get_media_row(c, filepath) is None:
            raise HTTPException(status_code=404, detail="Unknown file")

    def _relocate_or_http(src_nas, dest_nas):
        """Move src->dest (catalog NAS paths, mapped to SMB for the disk op),
        surfacing the 409/404 the UI expects. Shared by relocate + Arabic move."""
        try:
            relocate_file(to_local_path(src_nas, path_map), to_local_path(dest_nas, path_map),
                          exists_fn, makedirs_fn, move_fn)
        except FileExistsError:
            raise HTTPException(status_code=409, detail=f"Destination already exists: {dest_nas}")
        except FileNotFoundError:
            raise HTTPException(status_code=404, detail="Source file not reachable")

    def _target(body):
        # media_paths may be SMB (PC config); reverse-map roots to NAS so the
        # destination — and the repointed catalog row — stays NAS-style.
        movies_root, tv_root = pick_roots(media_paths)
        movies_root = to_nas_path(movies_root, path_map) if movies_root else movies_root
        tv_root = to_nas_path(tv_root, path_map) if tv_root else tv_root
        return build_target(body.filepath, body.kind, body.details, movies_root, tv_root)

    @app.post("/api/relocate/preview")
    def relocate_preview(body: RelocateBody):
        _require_row(conn(), body.filepath)
        dest = _target(body)
        return {"src": body.filepath, "dest": dest,
                "dest_exists": exists_fn(to_local_path(dest, path_map))}

    @app.post("/api/relocate/execute")
    def relocate_execute(body: RelocateBody):
        if not body.confirm:
            raise HTTPException(status_code=400, detail="confirm=true required")
        c = conn()
        _require_row(c, body.filepath)
        dest = _target(body)
        _relocate_or_http(body.filepath, dest)
        update_media_path(c, body.filepath, dest, metadata_id=body.details.get("metadata_id"))
        return {"moved": True, "dest": dest}

    # --- Arabic audio ---
    ARABIC_SUBDIR = "02-ArabicReady"

    def _arabic_dest(filepath):
        movies_root, _ = pick_roots(media_paths)
        if not movies_root:
            raise HTTPException(status_code=400, detail="No movies root configured")
        # SMB root -> NAS so the repointed catalog row stays NAS-style.
        movies_root = to_nas_path(movies_root, path_map)
        return arabic_target(movies_root, filepath, ARABIC_SUBDIR)

    @app.get("/api/arabic")
    def arabic():
        return arabic_audio_movies(conn())

    @app.post("/api/arabic/preview")
    def arabic_preview(body: ArabicBody):
        _require_row(conn(), body.filepath)
        dest = _arabic_dest(body.filepath)
        return {"src": body.filepath, "dest": dest,
                "dest_exists": exists_fn(to_local_path(dest, path_map))}

    @app.post("/api/arabic/move")
    def arabic_move(body: ArabicBody):
        c = conn()
        _require_row(c, body.filepath)
        dest = _arabic_dest(body.filepath)
        if not body.confirm:
            return {"src": body.filepath, "dest": dest, "moved": False}
        _relocate_or_http(body.filepath, dest)
        update_media_path(c, body.filepath, dest)
        return {"moved": True, "dest": dest}

    # --- Organize a loose folder of TV files into the library ---
    def _tv_root():
        _movies, tv_root = pick_roots(media_paths)
        if not tv_root:
            raise HTTPException(status_code=400, detail="No TV root configured")
        # media_paths may be SMB; store/destine NAS-style like the rest of the catalog.
        return to_nas_path(tv_root, path_map)

    def _make_episode_identifier():
        """TVDB identifier with a per-scan cache so each show is looked up once."""
        cache = {}

        def identify(show, season, episode):
            key = show.lower()
            if key not in cache:
                try:
                    cands = tvdb.search({"series_title": show})
                except Exception:
                    cands = []
                if not cands:
                    cache[key] = None
                else:
                    best = cands[0]   # TVDB returns by relevance; user confirms before move
                    try:
                        eps = tvdb.get_episodes(best["metadata_id"].split(":")[-1])
                    except Exception:
                        eps = []
                    cache[key] = {
                        "series": best.get("title"), "year": best.get("year"),
                        "metadata_id": best["metadata_id"],
                        "episodes": {(e["season"], e["episode"]): e["name"] for e in eps}}
            info = cache[key]
            if not info:
                return None
            return {"series": info["series"], "year": info["year"],
                    "metadata_id": info["metadata_id"],
                    "ep_title": info["episodes"].get((season, episode))}
        return identify

    @app.post("/api/organize/scan")
    def organize_scan(body: OrganizeScanBody):
        folder = body.folder.strip()
        if not folder:
            raise HTTPException(status_code=400, detail="No folder given")
        if not exists_fn(folder):
            raise HTTPException(status_code=404, detail=f"Folder not reachable: {folder}")
        plan = organize_mod.plan_folder(
            folder, walk_fn=walk_fn,
            probe_json_fn=lambda p: probe_json_fn(p, 30, 3, ffprobe_binary),
            identify_fn=_make_episode_identifier(), tv_root=_tv_root())
        counts = {"matched": 0, "unmatched": 0, "no_tags": 0}
        for it in plan:
            counts[it["status"]] = counts.get(it["status"], 0) + 1
        return {"folder": folder, "items": plan, "counts": counts}

    def _quarantine_loose(src):
        """Move a leftover sidecar/info file into the central quarantine (recoverable —
        the app never unlinks). Collision-safe. Returns True if moved."""
        local = to_local_path(src, path_map)
        if not exists_fn(local):
            return False
        makedirs_fn(quarantine_path, exist_ok=True)
        base = posixpath.basename(src.replace("\\", "/"))
        stem, ext = posixpath.splitext(base)
        dest = posixpath.join(quarantine_path.replace("\\", "/"), base)
        n = 1
        while exists_fn(to_local_path(dest, path_map)) or exists_fn(dest):
            dest = posixpath.join(quarantine_path.replace("\\", "/"), f"{stem}.{n}{ext}")
            n += 1
        move_fn(local, to_local_path(dest, path_map))
        return True

    @app.post("/api/organize/apply")
    def organize_apply(body: OrganizeApplyBody):
        if not body.confirm:
            raise HTTPException(status_code=400, detail="confirm=true required")
        c = conn()
        tv_root = _tv_root()
        moved = subtitles_moved = removed = skipped = 0
        errors = []
        for item in body.items:
            if item.get("status") != "matched":
                continue
            try:
                dest = organize_mod.episode_dest(tv_root, item)
            except (KeyError, TypeError):
                skipped += 1
                continue
            try:
                _relocate_or_http(item["src"], dest)   # src is already local; dest NAS->SMB
            except HTTPException as e:
                errors.append({"src": item.get("src"), "detail": e.detail})
                skipped += 1
                continue
            moved += 1
            # subtitles: recompute the dest from the video base so we never trust a client path
            vbase = posixpath.splitext(posixpath.basename(item["src"].replace("\\", "/")))[0]
            for sub in item.get("subtitles", []):
                sname = posixpath.basename(sub["src"].replace("\\", "/"))
                if not sname.startswith(vbase):
                    continue
                sdest = organize_mod.subtitle_dest(dest, sname[len(vbase):])
                try:
                    _relocate_or_http(sub["src"], sdest)
                    subtitles_moved += 1
                except HTTPException as e:
                    errors.append({"src": sub.get("src"), "detail": e.detail})
            for rm in item.get("remove", []):
                try:
                    if _quarantine_loose(rm):
                        removed += 1
                except OSError as e:
                    errors.append({"src": rm, "detail": str(e)})
            # index the moved episode so it shows up in the library immediately.
            # If the source was already cataloged (e.g. a folder UNDER Movies), repoint
            # it: carry the already-probed stream data onto the new episode row and drop
            # the stale source row so it doesn't linger as a ghost.
            try:
                old_nas = to_nas_path(item["src"], path_map)
                old_row = get_media_row(c, old_nas)
                size = 0
                try:
                    size = getsize_fn(to_local_path(dest, path_map))
                except OSError:
                    pass
                rec = dict(
                    filepath=dest, filename=posixpath.basename(dest), extension=item["ext"],
                    parent_directory=posixpath.dirname(dest),
                    file_size_bytes=size or (old_row["file_size_bytes"] if old_row else 0),
                    fast_hash=old_row["fast_hash"] if old_row else "",
                    os_hash=old_row["os_hash"] if old_row else "",
                    item_type="episode", season_number=item.get("season"),
                    episode_number=item.get("episode"),
                    metadata_id=item.get("metadata_id"), match_status="matched")
                if old_row:
                    for col in ("duration_ms", "bitrate", "resolution_width",
                                "resolution_height", "video_codec", "color_profile",
                                "audio_languages", "has_english_audio", "audio_profile"):
                        if old_row[col] is not None:
                            rec[col] = old_row[col]
                upsert_media_file(c, rec)
                if old_row and old_nas != dest:
                    delete_media_by_path(c, old_nas)
            except Exception:
                pass   # indexing is best-effort; the file is already in place

        cleanup = None
        if body.cleanup and body.folder:
            # Sweep leftovers (stray artwork/.nfo/trickplay) into quarantine and remove
            # the emptied folder — but ONLY if no video remains (a deselected or
            # unidentified episode keeps the folder, and its siblings, intact).
            try:
                children = scandir_fn(body.folder)
            except OSError:
                children = []
            remaining_videos = [c for c in children
                                if organize_mod._ext(c) in organize_mod.VIDEO_EXTS]
            swept, folder_removed = 0, False
            if remaining_videos:
                cleanup = {"swept": 0, "folder_removed": False, "reason": "videos remain"}
            else:
                for ch in children:
                    try:
                        if _quarantine_loose(ch):
                            swept += 1
                    except OSError as e:
                        errors.append({"src": ch, "detail": str(e)})
                try:
                    rmdir_fn(body.folder)
                    folder_removed = True
                except OSError:
                    pass
                cleanup = {"swept": swept, "folder_removed": folder_removed}

        return {"moved": moved, "subtitles_moved": subtitles_moved,
                "removed": removed, "skipped": skipped, "errors": errors,
                "cleanup": cleanup}

    # --- Mismatched videos (file name != folder name, movies library only) ---
    def _movies_prefix():
        for k, v in path_map.items():
            if "movie" in (k + " " + str(v)).lower():
                return k
        return None

    @app.get("/api/mismatch")
    def mismatch():
        return mismatched_videos(conn(), _movies_prefix())

    @app.get("/api/cleanup/legacy")
    def cleanup_legacy():
        return legacy_duplicates(conn())

    @app.post("/api/cleanup/legacy/execute")
    def cleanup_legacy_execute(body: ConfirmBody):
        if not body.confirm:
            raise HTTPException(status_code=400, detail="confirm=true required")
        c = conn()
        moved, reclaimed = 0, 0
        skipped = 0
        for t in legacy_duplicates(c)["targets"]:
            try:
                plan = build_deletion_plan(c, t["filepath"])
            except ValueError:
                continue
            try:
                execute_plan(plan, quarantine_path, dry_run=False,
                             to_local=lambda p: to_local_path(p, path_map))
            except FileNotFoundError:
                skipped += 1            # unreachable — leave the file and its DB row alone
                continue
            delete_media_by_path(c, t["filepath"])   # only after a successful move
            moved += 1
            reclaimed += t["file_size_bytes"]
        return {"moved": moved, "reclaimed_bytes": reclaimed, "skipped_unreachable": skipped}

    @app.get("/api/subtitles/deficits")
    def sub_deficits(offset: int = 0, limit: int = 50):
        return english_subtitle_deficits(conn(), limit=limit, offset=offset)

    @app.post("/api/delete/preview")
    def delete_preview(body: DeleteBody):
        c = conn()
        try:
            plan = build_deletion_plan(c, body.filepath)
        except ValueError as e:
            raise HTTPException(status_code=404, detail=str(e))
        return {"plan": plan, "moves": plan_moves(plan, quarantine_path)}

    @app.post("/api/delete/execute")
    def delete_execute(body: DeleteBody):
        if not body.confirm:
            raise HTTPException(status_code=400, detail="confirm=true required")
        c = conn()
        try:
            plan = build_deletion_plan(c, body.filepath)
        except ValueError as e:
            raise HTTPException(status_code=404, detail=str(e))
        try:
            moved = execute_plan(plan, quarantine_path, dry_run=False,
                                 to_local=lambda p: to_local_path(p, path_map))
        except FileNotFoundError as e:
            raise HTTPException(status_code=404,
                detail=f"File not reachable — nothing was quarantined and the catalog "
                       f"was left unchanged: {e}")
        delete_media_by_path(c, body.filepath)   # only after a successful quarantine move
        return {"moved": moved}

    # --- Subtitles (OpenSubtitles) ---
    @app.post("/api/subtitles/login")
    def sub_login(body: LoginBody):
        try:
            out = client.login(body.username, body.password)
        except Exception:
            raise HTTPException(status_code=401, detail="OpenSubtitles login failed")
        session["os_token"] = out["token"]   # session memory only
        return {"ok": True, "logged_in": True}

    @app.get("/api/subtitles/quota")
    def sub_quota():
        """Live OpenSubtitles download quota (needs an active session login)."""
        if not session["os_token"]:
            return {"logged_in": False}
        try:
            d = client.user_info(session["os_token"])
        except Exception:
            raise HTTPException(status_code=502, detail="Could not read OpenSubtitles quota")
        return {"logged_in": True, "allowed": d.get("allowed_downloads"),
                "used": d.get("downloads_count"), "remaining": d.get("remaining_downloads"),
                "reset_time": d.get("reset_time")}

    @app.post("/api/subtitles/fetch")
    def sub_fetch(body: FetchBody):
        if not session["os_token"]:
            raise HTTPException(status_code=401, detail="Log in to OpenSubtitles first")
        row = get_media_row(conn(), body.filepath)
        if row is None:
            raise HTTPException(status_code=404, detail="Unknown file")
        local = to_local_path(body.filepath, path_map)
        result = fetch_and_ingest(client, session["os_token"], local,
                                  _search_params(body.filepath, row), http_get=http_get)
        if not result["ok"] and result.get("reason") == "quota_exhausted":
            return JSONResponse(status_code=429, content=result)
        return result

    # --- Admin (PC-only) ---
    def _snapshot_db(tag=""):
        """Consistent snapshot of the live (WAL) DB via SQLite's backup API."""
        bdir = os.path.join(os.path.dirname(db_path) or ".", "backups")
        os.makedirs(bdir, exist_ok=True)
        ts = datetime.now().strftime("%Y%m%d-%H%M%S")
        dest = os.path.join(bdir, f"media_audit_{tag}{ts}.db")
        src, dst = conn(), sqlite3.connect(dest)
        try:
            src.backup(dst)
        finally:
            dst.close()
        return dest

    sync_job = {"running": False, "phase": "idle", "checked": 0, "total": 0,
                "missing": [], "error": None}

    @app.get("/api/admin/status")
    def admin_status_ep():
        s = admin_status(conn())
        try:
            s["db_mtime"] = os.path.getmtime(db_path)
        except OSError:
            s["db_mtime"] = None
        s["build_id"] = build_id
        return s

    @app.get("/api/admin/integrity")
    def admin_integrity():
        return {"result": conn().execute("PRAGMA integrity_check").fetchone()[0]}

    @app.post("/api/admin/backup")
    def admin_backup():
        dest = _snapshot_db()
        return {"path": dest, "size_bytes": os.path.getsize(dest)}

    @app.post("/api/admin/sync/scan")
    def admin_sync_scan():
        if sync_job["running"]:
            return {"started": False, "running": True}
        sync_job.update(running=True, phase="scanning", checked=0, total=0,
                        missing=[], error=None)

        def run():
            try:
                paths = all_media_paths(conn())
                sync_job["total"] = len(paths)
                miss = find_missing(
                    paths, lambda p: exists_fn(to_local_path(p, path_map)),
                    progress=lambda d, _t: sync_job.update(checked=d))
                sync_job["missing"] = miss
                sync_job["phase"] = "done"
            except Exception as e:
                sync_job["error"] = str(e)
                sync_job["phase"] = "error"
            finally:
                sync_job["running"] = False

        threading.Thread(target=run, daemon=True).start()
        return {"started": True}

    @app.get("/api/admin/sync/status")
    def admin_sync_status():
        return {"running": sync_job["running"], "phase": sync_job["phase"],
                "checked": sync_job["checked"], "total": sync_job["total"],
                "missing_count": len(sync_job["missing"]),
                "sample": sync_job["missing"][:25], "error": sync_job["error"]}

    @app.post("/api/admin/sync/apply")
    def admin_sync_apply(body: ConfirmBody):
        if not body.confirm:
            raise HTTPException(status_code=400, detail="confirm=true required")
        if sync_job["phase"] != "done":
            raise HTTPException(status_code=400, detail="Run a deletion scan first")
        missing = sync_job["missing"]
        if not missing:
            return {"removed": 0, "backup": None}
        backup = _snapshot_db("presync_")        # safety net before a bulk delete
        c = conn()
        with db_write_lock:
            c.executemany("DELETE FROM media_files WHERE filepath = ?",
                          [(p,) for p in missing])
            c.commit()
        sync_job.update(phase="idle", missing=[], checked=0, total=0)
        return {"removed": len(missing), "backup": backup}

    # generic background job: work(job) runs in a daemon thread and may update
    # job['checked']; its return value lands in job['result'].
    def _bg_run(job, work):
        if job["running"]:
            return False
        job.update(running=True, phase="working", checked=0, result=None, error=None)

        def run():
            try:
                job["result"] = work(job)
                job["phase"] = "done"
            except Exception as e:
                job["error"] = str(e)
                job["phase"] = "error"
            finally:
                job["running"] = False
        threading.Thread(target=run, daemon=True).start()
        return True

    quar_job = {"running": False, "phase": "idle", "checked": 0, "result": None, "error": None}

    @app.post("/api/admin/quarantine/scan")
    def quar_scan():
        def work(job):
            size, count, items = 0, 0, []
            if os.path.isdir(quarantine_path):
                for dp, _dn, fns in os.walk(quarantine_path):
                    for f in fns:
                        p = os.path.join(dp, f)
                        try:
                            sz = getsize_fn(p)
                        except OSError:
                            sz = 0
                        size += sz
                        count += 1
                        job["checked"] = count
                        items.append({"path": p.replace("\\", "/"), "bytes": sz})
            items.sort(key=lambda x: -x["bytes"])
            return {"bytes": size, "count": count, "largest": items[:15]}
        return {"started": _bg_run(quar_job, work)}

    @app.get("/api/admin/quarantine/status")
    def quar_status():
        r = quar_job["result"] or {}
        return {"running": quar_job["running"], "phase": quar_job["phase"],
                "checked": quar_job["checked"], "bytes": r.get("bytes", 0),
                "count": r.get("count", 0), "largest": r.get("largest", []),
                "error": quar_job["error"]}

    @app.post("/api/admin/quarantine/purge")
    def quar_purge(body: ConfirmBody):
        if not body.confirm:
            raise HTTPException(status_code=400, detail="confirm=true required")
        if not os.path.isdir(quarantine_path):
            return {"removed": 0}
        removed = sum(len(fns) for _dp, _dn, fns in os.walk(quarantine_path))
        for entry in os.listdir(quarantine_path):
            p = os.path.join(quarantine_path, entry)
            try:
                shutil.rmtree(p) if os.path.isdir(p) else os.remove(p)
            except OSError:
                pass
        return {"removed": removed}

    # --- Re-match unmatched (TMDB/TVDB), one lookup per distinct title ---
    rematch_job = {"running": False, "phase": "idle", "checked": 0, "result": None,
                   "error": None}

    @app.post("/api/admin/rematch/start")
    def admin_rematch():
        def work(job):
            c = conn()
            groups = {}
            for r in unmatched_list(c):
                p = parse_path(r["filepath"])
                title = (p.get("movie_title") or p.get("series_title") or "").lower().strip()
                if not title:
                    continue
                groups.setdefault((p["item_type"], title, p.get("year")), []).append((r["filepath"], p))
            job["total"] = len(groups)
            matched = 0
            for i, (key, items) in enumerate(groups.items(), 1):
                provider = tvdb if key[0] == "episode" else tmdb
                parsed = items[0][1]
                try:
                    cands = provider.search(parsed) or []
                except Exception:
                    cands = []
                res = decide_match(cands, parsed)
                mid, status = res["metadata_id"], res["status"]
                if mid:
                    chosen = next((cc for cc in cands if cc["metadata_id"] == mid), None)
                    if chosen:
                        cache_metadata(c, mid, chosen.get("title") or key[1],
                                       release_date=str(chosen.get("year") or ""))
                    matched += 1
                for fp, _ in items:
                    set_match(c, fp, mid, status)
                job["checked"] = i
            return {"groups": len(groups), "newly_matched": matched}
        return {"started": _bg_run(rematch_job, work)}

    @app.get("/api/admin/rematch/status")
    def admin_rematch_status():
        r = rematch_job["result"] or {}
        return {"running": rematch_job["running"], "phase": rematch_job["phase"],
                "checked": rematch_job["checked"], "groups": r.get("groups", 0),
                "newly_matched": r.get("newly_matched", 0), "error": rematch_job["error"]}

    # --- Probe runtimes/audio (detached, long-running) ---
    probe_state = {"proc": None, "target_set": None, "last_count": None, "last_change": 0.0}

    def _probe_target_set(c):
        """The exact set of files the probe aims to cover (dup-group files + all
        movies), matching probe_dupes.py. Cached — it's a full scan and changes
        little; recomputed on each fresh Start."""
        if probe_state["target_set"] is None:
            probe_state["target_set"] = probe_targets(c)
        return probe_state["target_set"]

    def _track_running(probed_count):
        """Note when the probed count last climbed, so we can tell a probe is running
        in another process (e.g. after a dashboard restart) without its handle."""
        if probe_state["last_count"] is None:
            probe_state["last_count"] = probed_count
        elif probed_count != probe_state["last_count"]:
            probe_state["last_count"] = probed_count
            probe_state["last_change"] = datetime.now().timestamp()

    def _probe_running():
        p = probe_state["proc"]
        if p is not None and p.poll() is None:
            return True
        lc = probe_state["last_change"]                  # count climbed within 20s => running
        return lc > 0 and (datetime.now().timestamp() - lc) < 20

    @app.post("/api/admin/probe/start")
    def probe_start():
        n = conn().execute(
            "SELECT COUNT(*) FROM media_files WHERE duration_ms IS NOT NULL").fetchone()[0]
        _track_running(n)
        if _probe_running():
            return {"started": False, "running": True}
        probe_state["target_set"] = None      # recompute the target for a fresh run
        probe_state["proc"] = spawn_probe_fn()
        return {"started": True}

    @app.get("/api/admin/probe/status")
    def probe_status():
        c = conn()
        tset = _probe_target_set(c)
        probed_paths = {r[0] for r in c.execute(
            "SELECT filepath FROM media_files WHERE duration_ms IS NOT NULL")}
        _track_running(len(probed_paths))
        done = len(tset & probed_paths)
        target = len(tset)
        remaining_paths = sorted(tset - probed_paths)
        return {"running": _probe_running(), "probed": done, "target": target,
                "remaining": target - done, "remaining_paths": remaining_paths[:50]}

    @app.post("/api/admin/probe/stop")
    def probe_stop():
        p = probe_state["proc"]
        if p is not None and p.poll() is None:
            p.terminate()
            return {"stopped": True}
        return {"stopped": False}

    return app
_TEMPLATE_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                              "src", "web", "index.html")
with open(_TEMPLATE_PATH, encoding="utf-8") as _f:
    _INDEX_HTML = _f.read()   # frontend template; served by index() with __BUILD_ID__ filled in
