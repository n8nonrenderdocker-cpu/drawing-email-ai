from __future__ import annotations

import logging
from typing import Iterable

import requests

from .config import Settings
from .gmail_client import send_gmail_notification
from .models import ProcessResult


LOGGER = logging.getLogger(__name__)


def notify(settings: Settings, subject: str, body: str) -> None:
    mode = settings.notification_mode
    if mode == "none":
        return
    if mode == "gmail":
        if not settings.notification_email_to:
            LOGGER.warning("NOTIFICATION_MODE=gmail but NOTIFICATION_EMAIL_TO is empty")
            return
        send_gmail_notification(settings, settings.notification_email_to, subject, body)
        return
    if mode == "slack":
        if not settings.slack_webhook_url:
            LOGGER.warning("NOTIFICATION_MODE=slack but SLACK_WEBHOOK_URL is empty")
            return
        requests.post(settings.slack_webhook_url, json={"text": f"*{subject}*\n{body}"}, timeout=15).raise_for_status()
        return
    if mode == "telegram":
        if not settings.telegram_bot_token or not settings.telegram_chat_id:
            LOGGER.warning("NOTIFICATION_MODE=telegram but Telegram settings are incomplete")
            return
        url = f"https://api.telegram.org/bot{settings.telegram_bot_token}/sendMessage"
        requests.post(
            url,
            json={"chat_id": settings.telegram_chat_id, "text": f"{subject}\n\n{body}"},
            timeout=15,
        ).raise_for_status()
        return

    LOGGER.warning("Unknown NOTIFICATION_MODE=%s", mode)


def notify_results(settings: Settings, email_subject: str, results: Iterable[ProcessResult]) -> None:
    results = list(results)
    if not results:
        return

    subject = f"Drawing automation processed {len(results)} attachment(s)"
    lines = [f"Email subject: {email_subject}", ""]
    for result in results:
        lines.extend(
            [
                f"File: {result.filename}",
                f"Status: {result.status}",
                f"Message: {result.message}",
            ]
        )
        if result.airtable_record_id:
            lines.append(f"Airtable record: {result.airtable_record_id}")
        if result.duplicate_match_record_id:
            lines.append(f"Matched existing record: {result.duplicate_match_record_id}")
        lines.append("")

    notify(settings, subject, "\n".join(lines).strip())
