"""File uploads: charger photos (public) and ID documents (private, admin-only).

STORAGE_BACKEND=local    -> files saved on the server disk (fine for development; use a persistent disk in production)
STORAGE_BACKEND=supabase -> files saved in Supabase Storage buckets (recommended for production)
"""
import secrets
from pathlib import Path

import httpx
from fastapi import HTTPException

from ..config import get_settings

ALLOWED_TYPES = {"image/jpeg": "jpg", "image/png": "png", "image/webp": "webp", "application/pdf": "pdf"}


def _new_name(content_type: str) -> str:
    ext = ALLOWED_TYPES.get(content_type)
    if ext is None:
        raise HTTPException(400, "Only JPG, PNG, WEBP or PDF files are allowed")
    return f"{secrets.token_hex(16)}.{ext}"


def save(data: bytes, content_type: str, private: bool) -> dict:
    """Returns {"key": ..., "url": ...}. url is only set for public files."""
    s = get_settings()
    if len(data) > s.max_upload_mb * 1024 * 1024:
        raise HTTPException(413, f"File too large (max {s.max_upload_mb} MB)")
    if not private and content_type == "application/pdf":
        raise HTTPException(400, "Photos must be images")
    name = _new_name(content_type)

    if s.storage_backend == "supabase":
        bucket = s.supabase_private_bucket if private else s.supabase_public_bucket
        r = httpx.post(
            f"{s.supabase_url}/storage/v1/object/{bucket}/{name}",
            content=data,
            headers={"authorization": f"Bearer {s.supabase_service_key}", "content-type": content_type},
            timeout=60,
        )
        if r.status_code >= 300:
            raise HTTPException(502, "Upload failed")
        url = None if private else f"{s.supabase_url}/storage/v1/object/public/{bucket}/{name}"
        return {"key": name, "url": url}

    folder = Path(s.local_upload_dir) / ("private" if private else "public")
    folder.mkdir(parents=True, exist_ok=True)
    (folder / name).write_bytes(data)
    url = None if private else f"{s.public_base_url}/media/{name}"
    return {"key": name, "url": url}


def read_private(key: str) -> tuple[bytes, str]:
    s = get_settings()
    if "/" in key or ".." in key:
        raise HTTPException(400, "Bad file key")
    ext = key.rsplit(".", 1)[-1]
    ctype = {v: k for k, v in ALLOWED_TYPES.items()}.get(ext, "application/octet-stream")
    if s.storage_backend == "supabase":
        r = httpx.get(
            f"{s.supabase_url}/storage/v1/object/{s.supabase_private_bucket}/{key}",
            headers={"authorization": f"Bearer {s.supabase_service_key}"},
            timeout=60,
        )
        if r.status_code >= 300:
            raise HTTPException(404, "File not found")
        return r.content, ctype
    path = Path(s.local_upload_dir) / "private" / key
    if not path.exists():
        raise HTTPException(404, "File not found")
    return path.read_bytes(), ctype
