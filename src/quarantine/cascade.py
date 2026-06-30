import os

from src.repository import get_media_row
from src.quarantine.assets import is_global_asset


def _sidecar_owned_by(asset_path, video_stem):
    """A sidecar belongs to a video if its filename starts with the video's base name
    (e.g. 'Movie.eng.srt', 'Movie.nfo', 'Movie.trickplay', 'Movie-thumb.jpg' all
    belong to the video whose stem is 'Movie')."""
    name = os.path.basename(asset_path.replace("\\", "/"))
    return name.startswith(video_stem)


def build_deletion_plan(conn, filepath):
    """Plan which files move when `filepath` is deleted.

    Only sidecars owned *exclusively* by the deleted video cascade. A sidecar that a
    surviving same-name video in the folder still claims (the classic case of one
    movie stored in several formats — Movie.mkv / Movie.mp4 / Movie.avi sharing
    Movie.nfo and Movie.eng.srt) is preserved, as are folder-global assets.
    """
    row = get_media_row(conn, filepath)
    if row is None:
        raise ValueError(f"Not in database: {filepath}")

    folder = os.path.dirname(filepath)
    deleted_stem = os.path.splitext(os.path.basename(filepath))[0]

    siblings = conn.execute(
        "SELECT filepath FROM media_files WHERE parent_directory = ? AND filepath != ?",
        (folder, filepath)).fetchall()
    sibling_stems = {os.path.splitext(os.path.basename(s["filepath"]))[0] for s in siblings}

    assets = conn.execute(
        "SELECT asset_path FROM sidecar_assets WHERE media_file_id = ?",
        (row["id"],)).fetchall()

    cascade, preserved = [], []
    for a in assets:
        path = a["asset_path"]
        if is_global_asset(path):
            preserved.append(path)
        elif not _sidecar_owned_by(path, deleted_stem):
            preserved.append(path)              # not this video's sidecar at all
        elif any(_sidecar_owned_by(path, sib) for sib in sibling_stems):
            preserved.append(path)              # shared with a surviving copy
        else:
            cascade.append(path)
    return {"video": filepath, "cascade": cascade, "preserved": preserved}
