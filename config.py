from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

from dotenv import load_dotenv


BASE_DIR = Path(__file__).resolve().parents[1]
load_dotenv(BASE_DIR / ".env")


def _path_from_env(name: str, default: str) -> Path:
    value = os.getenv(name, default)
    path = Path(value)
    if not path.is_absolute():
        path = BASE_DIR / path
    return path


def _float_from_env(name: str, default: float) -> float:
    raw = os.getenv(name)
    if raw in (None, ""):
        return default
    return float(raw)


def _int_from_env(name: str, default: int) -> int:
    raw = os.getenv(name)
    if raw in (None, ""):
        return default
    return int(raw)


@dataclass(frozen=True)
class Settings:
    webhook_secret: str

    google_credentials_file: Path
    google_token_file: Path
    google_credentials_json: Optional[str]
    google_token_json: Optional[str]

    airtable_token: str
    airtable_base_id: str
    airtable_table_name: str

    storage_backend: str
    storage_dir: Path
    public_file_base_url: Optional[str]
    google_drive_folder_id: Optional[str]
    google_drive_share_files: bool

    notification_mode: str
    notification_email_to: Optional[str]
    slack_webhook_url: Optional[str]
    telegram_bot_token: Optional[str]
    telegram_chat_id: Optional[str]

    dwg_converter_command: Optional[str]
    geometry_round_precision: int
    low_confidence_max_unsupported_ratio: float

    field_customer_email: str
    field_email_subject: str
    field_received_date: str
    field_file_name: str
    field_file_type: str
    field_original_file_link: str
    field_original_file_kind: str
    field_file_hash: str
    field_geometry_fingerprint: str
    field_drawing_code: str
    field_status: str
    field_duplicate_match_record: str
    field_difference_summary: str
    field_notes: str
    field_geometry_summary: Optional[str]

    @classmethod
    def load(cls) -> "Settings":
        return cls(
            webhook_secret=os.getenv("WEBHOOK_SECRET", ""),
            google_credentials_file=_path_from_env("GOOGLE_CREDENTIALS_FILE", "credentials.json"),
            google_token_file=_path_from_env("GOOGLE_TOKEN_FILE", "token.json"),
            google_credentials_json=os.getenv("GOOGLE_CREDENTIALS_JSON") or None,
            google_token_json=os.getenv("GOOGLE_TOKEN_JSON") or None,
            airtable_token=os.getenv("AIRTABLE_TOKEN", ""),
            airtable_base_id=os.getenv("AIRTABLE_BASE_ID", ""),
            airtable_table_name=os.getenv("AIRTABLE_TABLE_NAME", "Drawings"),
            storage_backend=os.getenv("STORAGE_BACKEND", "local").lower(),
            storage_dir=_path_from_env("STORAGE_DIR", "storage"),
            public_file_base_url=os.getenv("PUBLIC_FILE_BASE_URL") or None,
            google_drive_folder_id=os.getenv("GOOGLE_DRIVE_FOLDER_ID") or None,
            google_drive_share_files=os.getenv("GOOGLE_DRIVE_SHARE_FILES", "false").lower()
            in {"1", "true", "yes"},
            notification_mode=os.getenv("NOTIFICATION_MODE", "none").lower(),
            notification_email_to=os.getenv("NOTIFICATION_EMAIL_TO") or None,
            slack_webhook_url=os.getenv("SLACK_WEBHOOK_URL") or None,
            telegram_bot_token=os.getenv("TELEGRAM_BOT_TOKEN") or None,
            telegram_chat_id=os.getenv("TELEGRAM_CHAT_ID") or None,
            dwg_converter_command=os.getenv("DWG_CONVERTER_COMMAND") or None,
            geometry_round_precision=_int_from_env("GEOMETRY_ROUND_PRECISION", 4),
            low_confidence_max_unsupported_ratio=_float_from_env(
                "LOW_CONFIDENCE_MAX_UNSUPPORTED_RATIO", 0.50
            ),
            field_customer_email=os.getenv("AIRTABLE_FIELD_CUSTOMER_EMAIL", "Customer Email"),
            field_email_subject=os.getenv("AIRTABLE_FIELD_EMAIL_SUBJECT", "Email Subject"),
            field_received_date=os.getenv("AIRTABLE_FIELD_RECEIVED_DATE", "Received Date"),
            field_file_name=os.getenv("AIRTABLE_FIELD_FILE_NAME", "File Name"),
            field_file_type=os.getenv("AIRTABLE_FIELD_FILE_TYPE", "File Type"),
            field_original_file_link=os.getenv("AIRTABLE_FIELD_ORIGINAL_FILE_LINK", "Original File Link"),
            field_original_file_kind=os.getenv("AIRTABLE_FIELD_ORIGINAL_FILE_KIND", "url").lower(),
            field_file_hash=os.getenv("AIRTABLE_FIELD_FILE_HASH", "File Hash"),
            field_geometry_fingerprint=os.getenv(
                "AIRTABLE_FIELD_GEOMETRY_FINGERPRINT", "Geometry Fingerprint"
            ),
            field_drawing_code=os.getenv("AIRTABLE_FIELD_DRAWING_CODE", "Drawing Code / Product Code"),
            field_status=os.getenv("AIRTABLE_FIELD_STATUS", "Status"),
            field_duplicate_match_record=os.getenv(
                "AIRTABLE_FIELD_DUPLICATE_MATCH_RECORD", "Duplicate Match Record"
            ),
            field_difference_summary=os.getenv("AIRTABLE_FIELD_DIFFERENCE_SUMMARY", "Difference Summary"),
            field_notes=os.getenv("AIRTABLE_FIELD_NOTES", "Notes"),
            field_geometry_summary=os.getenv("AIRTABLE_FIELD_GEOMETRY_SUMMARY", "Geometry Summary JSON")
            or None,
        )

    def validate_for_processing(self) -> None:
        missing = []
        if not self.airtable_token:
            missing.append("AIRTABLE_TOKEN")
        if not self.airtable_base_id:
            missing.append("AIRTABLE_BASE_ID")
        if missing:
            raise RuntimeError(f"Missing required environment variables: {', '.join(missing)}")
