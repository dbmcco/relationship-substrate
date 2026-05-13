from __future__ import annotations

from pathlib import Path
from typing import Iterator

from openpyxl import load_workbook

from relationship_substrate.contracts import SourceEventIn, SourcePosture


def _normalize_header(value: object) -> str:
    return str(value or "").strip().lower().replace(" ", "_")


def iter_people_workbook_events(path: Path) -> Iterator[SourceEventIn]:
    workbook = load_workbook(path, read_only=True, data_only=True)
    sheet = workbook["Contacts"]
    rows = sheet.iter_rows(values_only=True)
    headers = [_normalize_header(value) for value in next(rows)]
    for row_number, values in enumerate(rows, start=2):
        record = dict(zip(headers, values, strict=False))
        email = record.get("email")
        first_name = record.get("first_name")
        last_name = record.get("last_name")
        if not email and not first_name and not last_name:
            continue
        payload = {
            "first_name": first_name,
            "last_name": last_name,
            "title": record.get("title"),
            "company": record.get("company"),
            "email": email,
            "row_number": row_number,
            "path": str(path),
        }
        yield SourceEventIn(
            source_name="next_up",
            source_event_type="curated_contact",
            source_event_key=f"next_up:{path.name}:Contacts:{row_number}",
            source_payload=payload,
            source_posture=SourcePosture.CURATED_EXPORT,
            provenance_status="unknown_upstream",
            trust_role="identity/context seed",
        )
