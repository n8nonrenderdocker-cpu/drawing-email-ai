from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Optional


STATUS_NEW = "New"
STATUS_DUPLICATE = "Duplicate"
STATUS_SAME_NAME_DIFFERENT = "Same Name Different Drawing"
STATUS_REVIEW = "Needs Manual Review"


@dataclass(frozen=True)
class EmailContext:
    message_id: str
    thread_id: str
    sender: str
    subject: str
    received_date: str


@dataclass(frozen=True)
class EmailAttachment:
    filename: str
    mime_type: str
    data: bytes


@dataclass(frozen=True)
class FingerprintResult:
    file_hash: str
    geometry_fingerprint: Optional[str]
    geometry_summary: dict[str, Any]
    drawing_code: Optional[str]
    confidence: str
    warnings: list[str]


@dataclass(frozen=True)
class ProcessResult:
    filename: str
    status: str
    message: str
    airtable_record_id: Optional[str] = None
    duplicate_match_record_id: Optional[str] = None
    file_hash: Optional[str] = None
    geometry_fingerprint: Optional[str] = None
