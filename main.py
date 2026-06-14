from __future__ import annotations

import argparse
import logging
from typing import Any

import uvicorn
from fastapi import FastAPI, Header, HTTPException, Request
from pydantic import BaseModel

from automation import process_gmail_message
from config import Settings
from gmail_client import authorize_gmail


logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s - %(message)s",
)
LOGGER = logging.getLogger(__name__)
settings = Settings.load()
app = FastAPI(title="Drawing Email Automation")


class GmailMessagePayload(BaseModel):
    message_id: str | None = None
    messageId: str | None = None
    id: str | None = None
    webhook_secret: str | None = None


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


@app.post("/webhook/gmail-message")
async def gmail_message_webhook(
    payload: GmailMessagePayload,
    request: Request,
    x_webhook_secret: str | None = Header(default=None),
) -> dict[str, Any]:
    verify_webhook_secret(settings, payload.webhook_secret or x_webhook_secret)
    message_id = payload.message_id or payload.messageId or payload.id
    if not message_id:
        # Some n8n Gmail nodes wrap output inside the raw JSON body.
        raw = await request.json()
        message_id = raw.get("json", {}).get("id") if isinstance(raw, dict) else None
    if not message_id:
        raise HTTPException(status_code=400, detail="Missing Gmail message id")

    results = process_gmail_message(settings, message_id)
    return {"message_id": message_id, "processed": [result.__dict__ for result in results]}


def verify_webhook_secret(settings: Settings, provided: str | None) -> None:
    if not settings.webhook_secret:
        return
    if provided != settings.webhook_secret:
        raise HTTPException(status_code=401, detail="Invalid webhook secret")


def cli() -> None:
    parser = argparse.ArgumentParser(description="Drawing email automation")
    subparsers = parser.add_subparsers(dest="command", required=True)

    subparsers.add_parser("auth-gmail", help="Create or refresh the Gmail OAuth token")

    process_parser = subparsers.add_parser("process-message", help="Process one Gmail message id")
    process_parser.add_argument("message_id")

    serve_parser = subparsers.add_parser("serve", help="Run the webhook API")
    serve_parser.add_argument("--host", default="0.0.0.0")
    serve_parser.add_argument("--port", default=8000, type=int)

    args = parser.parse_args()
    if args.command == "auth-gmail":
        authorize_gmail(settings)
    elif args.command == "process-message":
        results = process_gmail_message(settings, args.message_id)
        for result in results:
            LOGGER.info("%s - %s - %s", result.filename, result.status, result.message)
    elif args.command == "serve":
         uvicorn.run("main:app", host=args.host, port=args.port, reload=False)


if __name__ == "__main__":
    cli()
