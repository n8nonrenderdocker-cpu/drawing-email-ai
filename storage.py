from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from config import Settings
from google_drive_client import upload_to_google_drive


@dataclass(frozen=True)
class StoredFile:
    path: Optional[Path]
    link: str
    backend: str


def save_original_file(
    settings: Settings,
    filename: str,
    data: bytes,
    file_hash: str,
    mime_type: str = "application/octet-stream",
) -> StoredFile:
    if settings.storage_backend == "google_drive":
        safe_name = _safe_filename(filename)
        drive_name = f"{file_hash[:12]}_{safe_name}"
        link = upload_to_google_drive(settings, drive_name, data, mime_type)
        return StoredFile(path=None, link=link, backend="google_drive")

    today = datetime.now(timezone.utc)
    relative_dir = Path(str(today.year)) / f"{today.month:02d}" / f"{today.day:02d}"
    safe_name = _safe_filename(filename)
    target_dir = settings.storage_dir / relative_dir
    target_dir.mkdir(parents=True, exist_ok=True)
    target = target_dir / f"{file_hash[:12]}_{safe_name}"
    target.write_bytes(data)

    relative_path = target.relative_to(settings.storage_dir).as_posix()
    if settings.public_file_base_url:
        link = f"{settings.public_file_base_url.rstrip('/')}/{relative_path}"
    else:
        link = str(target)
    return StoredFile(path=target, link=link, backend="local")


def _safe_filename(filename: str) -> str:
    cleaned = re.sub(r"[^A-Za-z0-9._-]+", "_", filename).strip("._")
    return cleaned or "drawing"
