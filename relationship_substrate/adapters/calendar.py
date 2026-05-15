from __future__ import annotations

import json
from pathlib import Path
from typing import Iterator

from relationship_substrate.contracts import SourceEventIn, SourcePosture


def iter_calendar_export_paths(path: Path) -> Iterator[Path]:
    if path.is_dir():
        yield from sorted(child for child in path.iterdir() if child.is_file() and child.suffix == ".json")
        return
    yield path


def _items(payload: object) -> list[dict]:
    if isinstance(payload, list):
        return [item for item in payload if isinstance(item, dict)]
    if not isinstance(payload, dict):
        return []
    pages = payload.get("pages")
    if isinstance(pages, list):
        items: list[dict] = []
        for page in pages:
            items.extend(_items(page))
        return items
    for key in ("items", "events", "data"):
        value = payload.get(key)
        if isinstance(value, list):
            return [item for item in value if isinstance(item, dict)]
    return [payload]


def iter_calendar_json_events(path: Path) -> Iterator[SourceEventIn]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    for index, item in enumerate(_items(payload), start=1):
        event_id = str(item.get("id") or item.get("iCalUID") or index)
        source_payload = dict(item)
        source_payload["path"] = str(path)
        yield SourceEventIn(
            source_name="calendar",
            source_event_type="calendar_event",
            source_event_key=f"calendar:{path.name}:{event_id}",
            source_payload=source_payload,
            source_posture=SourcePosture.DIRECT_INTERACTION,
            provenance_status="calendar_export",
            trust_role="calendar attendance evidence",
        )
