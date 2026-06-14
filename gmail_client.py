from __future__ import annotations

import base64
import json
import logging
from email.mime.text import MIMEText
from pathlib import Path
from typing import Iterable

from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build

from config import Settings
from models import EmailAttachment, EmailContext


LOGGER = logging.getLogger(__name__)

SCOPES = [
    "https://www.googleapis.com/auth/gmail.readonly",
    "https://www.googleapis.com/auth/gmail.send",
    "https://www.googleapis.com/auth/drive.file",
]


def _header(headers: Iterable[dict], name: str) -> str:
    for header in headers:
        if header.get("name", "").lower() == name.lower():
            return header.get("value", "")
    return ""


def get_google_credentials(settings: Settings) -> Credentials:
    credentials = None
    token_file = settings.google_token_file
    credentials_file = settings.google_credentials_file

    if token_file.exists():
        credentials = Credentials.from_authorized_user_file(str(token_file), SCOPES)
    elif settings.google_token_json:
        credentials = Credentials.from_authorized_user_info(json.loads(settings.google_token_json), SCOPES)

    if not credentials or not credentials.valid:
        if credentials and credentials.expired and credentials.refresh_token:
            credentials.refresh(Request())
        else:
            if settings.google_credentials_json:
                flow = InstalledAppFlow.from_client_config(json.loads(settings.google_credentials_json), SCOPES)
            elif credentials_file.exists():
                flow = InstalledAppFlow.from_client_secrets_file(str(credentials_file), SCOPES)
            else:
                raise RuntimeError(
                    f"Missing Gmail OAuth client file: {credentials_file}. "
                    "Download it from Google Cloud, set GOOGLE_CREDENTIALS_JSON, or run auth-gmail locally."
                )
            credentials = flow.run_local_server(port=0)
        token_file.write_text(credentials.to_json(), encoding="utf-8")

    return credentials


def get_gmail_service(settings: Settings):
    credentials = get_google_credentials(settings)
    return build("gmail", "v1", credentials=credentials)


def authorize_gmail(settings: Settings) -> None:
    get_gmail_service(settings)
    LOGGER.info("Gmail authorization complete. Token saved to %s", settings.google_token_file)


def get_message_with_attachments(settings: Settings, message_id: str) -> tuple[EmailContext, list[EmailAttachment]]:
    service = get_gmail_service(settings)
    message = service.users().messages().get(userId="me", id=message_id, format="full").execute()
    payload = message.get("payload", {})
    headers = payload.get("headers", [])

    context = EmailContext(
        message_id=message["id"],
        thread_id=message.get("threadId", ""),
        sender=_header(headers, "From"),
        subject=_header(headers, "Subject"),
        received_date=_header(headers, "Date"),
    )

    attachments: list[EmailAttachment] = []
    for part in _walk_parts(payload):
        filename = part.get("filename") or ""
        body = part.get("body", {})
        if not filename:
            continue

        raw_data = body.get("data")
        if raw_data:
            data = _decode_urlsafe(raw_data)
        else:
            attachment_id = body.get("attachmentId")
            if not attachment_id:
                continue
            fetched = (
                service.users()
                .messages()
                .attachments()
                .get(userId="me", messageId=message_id, id=attachment_id)
                .execute()
            )
            data = _decode_urlsafe(fetched["data"])

        attachments.append(
            EmailAttachment(
                filename=Path(filename).name,
                mime_type=part.get("mimeType", "application/octet-stream"),
                data=data,
            )
        )

    return context, attachments


def send_gmail_notification(settings: Settings, to: str, subject: str, body: str) -> None:
    service = get_gmail_service(settings)
    message = MIMEText(body)
    message["to"] = to
    message["subject"] = subject
    encoded = base64.urlsafe_b64encode(message.as_bytes()).decode("utf-8")
    service.users().messages().send(userId="me", body={"raw": encoded}).execute()


def _walk_parts(part: dict):
    yield part
    for child in part.get("parts", []) or []:
        yield from _walk_parts(child)


def _decode_urlsafe(data: str) -> bytes:
    return base64.urlsafe_b64decode(data.encode("utf-8"))
