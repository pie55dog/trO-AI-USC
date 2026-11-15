"""Files on disk: profile photos and raw bracelet uploads.

Everything lives under MEDIA_DIR. The database stores paths *relative* to
MEDIA_DIR so the folder can move between machines.
"""

from __future__ import annotations

import secrets
from pathlib import Path
from typing import Optional

MAX_PHOTO_BYTES = 5 * 1024 * 1024

# Recognize images by their first bytes instead of trusting the declared
# content type or file name, which the client controls.
_IMAGE_SIGNATURES: tuple[tuple[bytes, str], ...] = (
    (b"\xff\xd8\xff", ".jpg"),
    (b"\x89PNG\r\n\x1a\n", ".png"),
)

PHOTO_MEDIA_TYPES = {".jpg": "image/jpeg", ".png": "image/png", ".webp": "image/webp"}


def image_extension(data: bytes) -> Optional[str]:
    """Return '.jpg', '.png' or '.webp' if ``data`` is that image type, else None."""
    for signature, ext in _IMAGE_SIGNATURES:
        if data.startswith(signature):
            return ext
    if len(data) >= 12 and data[:4] == b"RIFF" and data[8:12] == b"WEBP":
        return ".webp"
    return None


def save_photo(media_dir: Path, user_id: int, data: bytes) -> str:
    """Store a headshot and return its path relative to ``media_dir``.

    Raises ValueError if the bytes aren't a supported image or are too big.
    A new random file name is used each time so browsers never show a stale
    cached photo after the user changes it.
    """
    if len(data) > MAX_PHOTO_BYTES:
        raise ValueError("photo is larger than 5 MB")
    ext = image_extension(data)
    if ext is None:
        raise ValueError("photo must be a JPEG, PNG or WebP image")
    rel = Path("photos") / f"{user_id}-{secrets.token_hex(8)}{ext}"
    target = media_dir / rel
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes(data)
    return rel.as_posix()


def delete_media(media_dir: Path, rel_path: Optional[str]) -> None:
    """Remove a stored file if it exists; ignore anything already gone."""
    if not rel_path:
        return
    target = resolve_media(media_dir, rel_path)
    if target is not None:
        target.unlink(missing_ok=True)


def resolve_media(media_dir: Path, rel_path: str) -> Optional[Path]:
    """Turn a stored relative path into an absolute one inside ``media_dir``.

    Returns None if the path would escape ``media_dir`` (defense in depth
    against a bad value ever reaching the database).
    """
    root = media_dir.resolve()
    candidate = (root / rel_path).resolve()
    if root != candidate and root not in candidate.parents:
        return None
    return candidate


def upload_dir(media_dir: Path, upload_id: int) -> Path:
    """Folder for the files of one bracelet upload."""
    path = media_dir / "uploads" / str(upload_id)
    path.mkdir(parents=True, exist_ok=True)
    return path


def safe_filename(name: Optional[str], fallback: str) -> str:
    """Strip any directory parts and odd characters from an uploaded file name."""
    base = Path(name or "").name
    cleaned = "".join(c for c in base if c.isalnum() or c in "._-")[:100]
    return cleaned.lstrip(".") or fallback
