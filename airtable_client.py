from __future__ import annotations

import json
import logging
from typing import Any, Optional
from urllib.parse import quote

import requests

from .config import Settings


LOGGER = logging.getLogger(__name__)


class AirtableClient:
    def __init__(self, settings: Settings):
        settings.validate_for_processing()
        self.settings = settings
        table = quote(settings.airtable_table_name, safe="")
        self.base_url = f"https://api.airtable.com/v0/{settings.airtable_base_id}/{table}"
        self.session = requests.Session()
        self.session.headers.update(
            {
                "Authorization": f"Bearer {settings.airtable_token}",
                "Content-Type": "application/json",
            }
        )

    def find_by_file_hash(self, file_hash: str) -> Optional[dict[str, Any]]:
        return self._find_one_by_field(self.settings.field_file_hash, file_hash)

    def find_by_geometry_fingerprint(self, fingerprint: str) -> Optional[dict[str, Any]]:
        return self._find_one_by_field(self.settings.field_geometry_fingerprint, fingerprint)

    def find_by_file_name(self, filename: str) -> list[dict[str, Any]]:
        formula = self._equals_formula(self.settings.field_file_name, filename)
        return self._list_records(formula=formula)

    def create_drawing_record(self, fields: dict[str, Any]) -> dict[str, Any]:
        clean_fields = {key: value for key, value in fields.items() if key and value is not None}
        response = self.session.post(self.base_url, data=json.dumps({"fields": clean_fields}), timeout=30)
        self._raise_for_status(response)
        return response.json()

    def update_record(self, record_id: str, fields: dict[str, Any]) -> dict[str, Any]:
        clean_fields = {key: value for key, value in fields.items() if key and value is not None}
        response = self.session.patch(
            f"{self.base_url}/{record_id}", data=json.dumps({"fields": clean_fields}), timeout=30
        )
        self._raise_for_status(response)
        return response.json()

    def _find_one_by_field(self, field_name: str, value: str) -> Optional[dict[str, Any]]:
        records = self._list_records(formula=self._equals_formula(field_name, value), max_records=1)
        return records[0] if records else None

    def _list_records(self, formula: str, max_records: int = 100) -> list[dict[str, Any]]:
        params = {"filterByFormula": formula, "maxRecords": max_records}
        response = self.session.get(self.base_url, params=params, timeout=30)
        self._raise_for_status(response)
        return response.json().get("records", [])

    def _equals_formula(self, field_name: str, value: str) -> str:
        escaped_value = value.replace("\\", "\\\\").replace("'", "\\'")
        escaped_field = field_name.replace("}", "\\}")
        return f"{{{escaped_field}}} = '{escaped_value}'"

    def _raise_for_status(self, response: requests.Response) -> None:
        if response.ok:
            return
        try:
            detail = response.json()
        except ValueError:
            detail = response.text
        LOGGER.error("Airtable API error: %s", detail)
        response.raise_for_status()
