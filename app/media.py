import os, re
from pathlib import Path
ROOT = Path(os.environ.get("MEDIA_ROOT", "/tmp/personaai-media"))
ALLOWED = {".jpg", ".jpeg", ".png", ".webp", ".mp4", ".mov", ".m4v"}
PHOTOS = {".jpg", ".jpeg", ".png", ".webp"}
VIDEOS = {".mp4", ".mov", ".m4v"}

def folder(profile_id):
    path = ROOT / re.sub(r"[^a-zA-Z0-9_-]", "", profile_id)
    path.mkdir(parents=True, exist_ok=True)
    return path

def list_files(profile_id):
    rows = []
    for item in sorted(folder(profile_id).iterdir()):
        if item.is_file() and item.suffix.lower() in ALLOWED:
            rows.append({"name": item.name, "kind": "video" if item.suffix.lower() in VIDEOS else "photo", "url": f"/media/%s/%s" % (profile_id, item.name), "path": str(item)})
    return rows

def save_upload(profile_id, filename, data):
    suffix = Path(filename or "").suffix.lower()
    if suffix not in ALLOWED:
        raise ValueError("unsupported_type")
    if len(data) > 50 * 1024 * 1024:
        raise ValueError("too_large")
    safe = re.sub(r"[^a-zA-Z0-9._-]", "", Path(filename).name) or ("file" + suffix)
    dest = folder(profile_id) / safe
    dest.write_bytes(data)
    return dest

def first_file(profile_id, kind):
    wanted = VIDEOS if kind == "video" else PHOTOS
    for item in list_files(profile_id):
        if Path(item["path"]).suffix.lower() in wanted:
            return item["path"]
    return None


def resolve(profile_id, name):
    base = folder(profile_id).resolve()
    if not re.fullmatch(r"[a-zA-Z0-9._-]+", name or ""):
        return None
    path = (base / name).resolve()
    if base != path and base not in path.parents:
        return None
    return path if path.is_file() else None
