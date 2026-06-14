from __future__ import annotations

import io
import logging

from googleapiclient.discovery import build
from googleapiclient.http import MediaIoBaseUpload

from .config import Settings
from .gmail_client import get_google_credentials


LOGGER = logging.getLogger(__name__)


def upload_to_google_drive(
    settings: Settings,
    filename: str,
    data: bytes,
    mime_type: str = "application/octet-stream",
) -> str:
    credentials = get_google_credentials(settings)
    service = build("drive", "v3", credentials=credentials)
    metadata: dict[str, object] = {"name": filename}
    if settings.google_drive_folder_id:
        metadata["parents"] = [settings.google_drive_folder_id]

    media = MediaIoBaseUpload(io.BytesIO(data), mimetype=mime_type, resumable=False)
    created = (
        service.files()
        .create(body=metadata, media_body=media, fields="id,webViewLink")
        .execute()
    )
    file_id = created["id"]

    if settings.google_drive_share_files:
        service.permissions().create(
            fileId=file_id,
            body={"type": "anyone", "role": "reader"},
            fields="id",
        ).execute()
        return f"https://drive.google.com/file/d/{file_id}/view"

    return created.get("webViewLink") or f"https://drive.google.com/file/d/{file_id}/view"
