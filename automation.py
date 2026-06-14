from __future__ import annotations

import json
import logging
from typing import Any

from airtable_client import AirtableClient
from config import Settings
from drawing_processor import fingerprint_attachment, is_supported_drawing
from gmail_client import get_message_with_attachments
from models import (
    STATUS_DUPLICATE,
    STATUS_NEW,
    STATUS_REVIEW,
    STATUS_SAME_NAME_DIFFERENT,
    EmailAttachment,
    EmailContext,
    FingerprintResult,
    ProcessResult,
)
from notifier import notify_results
from storage import save_original_file


LOGGER = logging.getLogger(__name__)


def process_gmail_message(settings: Settings, message_id: str) -> list[ProcessResult]:
    context, attachments = get_message_with_attachments(settings, message_id)
    results = process_email_attachments(settings, context, attachments)
    notify_results(settings, context.subject, results)
    return results


def process_email_attachments(
    settings: Settings, context: EmailContext, attachments: list[EmailAttachment]
) -> list[ProcessResult]:
    airtable = AirtableClient(settings)
    results: list[ProcessResult] = []

    for attachment in attachments:
        if not is_supported_drawing(attachment.filename):
            LOGGER.info("Skipping non-DXF/DWG attachment: %s", attachment.filename)
            continue

        try:
            result = process_one_attachment(settings, airtable, context, attachment)
        except Exception as exc:
            LOGGER.exception("Unhandled processing error for %s", attachment.filename)
            result = ProcessResult(
                filename=attachment.filename,
                status=STATUS_REVIEW,
                message=f"Unhandled error: {exc}",
            )
        results.append(result)

    return results


def process_one_attachment(
    settings: Settings,
    airtable: AirtableClient,
    context: EmailContext,
    attachment: EmailAttachment,
) -> ProcessResult:
    fingerprint = fingerprint_attachment(settings, attachment.filename, attachment.data)

    exact_duplicate = airtable.find_by_file_hash(fingerprint.file_hash)
    if exact_duplicate:
        record_id = exact_duplicate["id"]
        return ProcessResult(
            filename=attachment.filename,
            status=STATUS_DUPLICATE,
            message="Exact duplicate found by SHA-256 file hash. File was not saved again.",
            duplicate_match_record_id=record_id,
            file_hash=fingerprint.file_hash,
            geometry_fingerprint=fingerprint.geometry_fingerprint,
        )

    geometry_duplicate = None
    if fingerprint.geometry_fingerprint:
        geometry_duplicate = airtable.find_by_geometry_fingerprint(fingerprint.geometry_fingerprint)
    if geometry_duplicate and fingerprint.confidence != "low":
        record_id = geometry_duplicate["id"]
        return ProcessResult(
            filename=attachment.filename,
            status=STATUS_DUPLICATE,
            message=(
                "Drawing appears to already exist by geometry fingerprint. "
                "The file hash or name may differ, so no new record was created."
            ),
            duplicate_match_record_id=record_id,
            file_hash=fingerprint.file_hash,
            geometry_fingerprint=fingerprint.geometry_fingerprint,
        )

    same_name_records = airtable.find_by_file_name(attachment.filename)
    status = STATUS_NEW
    duplicate_record_id = None
    difference_summary = ""

    if fingerprint.confidence == "low":
        status = STATUS_REVIEW
        difference_summary = "; ".join(fingerprint.warnings)
    elif same_name_records:
        status = STATUS_SAME_NAME_DIFFERENT
        duplicate_record_id = same_name_records[0]["id"]
        difference_summary = build_difference_summary(
            same_name_records[0].get("fields", {}), fingerprint, settings
        )

    stored = save_original_file(
        settings,
        attachment.filename,
        attachment.data,
        fingerprint.file_hash,
        attachment.mime_type,
    )
    fields = build_airtable_fields(
        settings=settings,
        context=context,
        attachment=attachment,
        fingerprint=fingerprint,
        status=status,
        original_file_link=stored.link,
        duplicate_record_id=duplicate_record_id,
        difference_summary=difference_summary,
    )
    created = airtable.create_drawing_record(fields)

    if status == STATUS_NEW:
        message = "New drawing saved to Airtable."
    elif status == STATUS_SAME_NAME_DIFFERENT:
        message = "Same file name already exists, but drawing content is different."
    else:
        message = "Drawing saved for manual review because parsing or confidence was low."

    return ProcessResult(
        filename=attachment.filename,
        status=status,
        message=message,
        airtable_record_id=created["id"],
        duplicate_match_record_id=duplicate_record_id,
        file_hash=fingerprint.file_hash,
        geometry_fingerprint=fingerprint.geometry_fingerprint,
    )


def build_airtable_fields(
    settings: Settings,
    context: EmailContext,
    attachment: EmailAttachment,
    fingerprint: FingerprintResult,
    status: str,
    original_file_link: str,
    duplicate_record_id: str | None,
    difference_summary: str,
) -> dict[str, Any]:
    notes = []
    if fingerprint.confidence:
        notes.append(f"Fingerprint confidence: {fingerprint.confidence}")
    if fingerprint.warnings:
        notes.extend(fingerprint.warnings)

    fields: dict[str, Any] = {
        settings.field_customer_email: context.sender,
        settings.field_email_subject: context.subject,
        settings.field_received_date: context.received_date,
        settings.field_file_name: attachment.filename,
        settings.field_file_type: attachment.filename.rsplit(".", 1)[-1].upper(),
        settings.field_file_hash: fingerprint.file_hash,
        settings.field_geometry_fingerprint: fingerprint.geometry_fingerprint,
        settings.field_drawing_code: fingerprint.drawing_code,
        settings.field_status: status,
        settings.field_duplicate_match_record: duplicate_record_id,
        settings.field_difference_summary: difference_summary,
        settings.field_notes: "\n".join(notes) if notes else None,
    }

    if settings.field_original_file_kind == "attachment":
        fields[settings.field_original_file_link] = [
            {"url": original_file_link, "filename": attachment.filename}
        ]
    else:
        fields[settings.field_original_file_link] = original_file_link

    if settings.field_geometry_summary:
        fields[settings.field_geometry_summary] = json.dumps(
            fingerprint.geometry_summary, sort_keys=True, ensure_ascii=True
        )
    return fields


def build_difference_summary(
    existing_fields: dict[str, Any], new_fingerprint: FingerprintResult, settings: Settings
) -> str:
    existing_summary_raw = None
    if settings.field_geometry_summary:
        existing_summary_raw = existing_fields.get(settings.field_geometry_summary)

    try:
        existing_summary = json.loads(existing_summary_raw) if existing_summary_raw else {}
    except (TypeError, ValueError):
        existing_summary = {}

    if not existing_summary:
        return (
            "Same file name exists, but no comparable geometry summary was stored on the existing "
            "record. New drawing has a different file hash/fingerprint."
        )

    parts = []
    old_counts = existing_summary.get("entity_counts", {})
    new_counts = new_fingerprint.geometry_summary.get("entity_counts", {})
    if old_counts != new_counts:
        parts.append(f"Entity counts changed from {old_counts} to {new_counts}.")

    old_layers = set(existing_summary.get("layer_names", []))
    new_layers = set(new_fingerprint.geometry_summary.get("layer_names", []))
    added_layers = sorted(new_layers - old_layers)
    removed_layers = sorted(old_layers - new_layers)
    if added_layers or removed_layers:
        parts.append(f"Layer changes: added={added_layers}, removed={removed_layers}.")

    old_bbox = existing_summary.get("bounding_box")
    new_bbox = new_fingerprint.geometry_summary.get("bounding_box")
    if old_bbox != new_bbox:
        parts.append(f"Bounding box changed from {old_bbox} to {new_bbox}.")

    old_text = set(existing_summary.get("text_labels", []))
    new_text = set(new_fingerprint.geometry_summary.get("text_labels", []))
    if old_text != new_text:
        parts.append(
            f"Text label changes: added={sorted(new_text - old_text)}, removed={sorted(old_text - new_text)}."
        )

    return " ".join(parts) or "Same file name exists, but geometry fingerprint differs."
