from pathlib import Path

from relationship_substrate.adapters.calendar import iter_calendar_export_paths, iter_calendar_json_events
from relationship_substrate.contracts import SourcePosture


def test_calendar_json_events_preserve_gws_event_payload(tmp_path: Path):
    calendar_json = tmp_path / "calendar.json"
    calendar_json.write_text(
        """
        {
          "items": [
            {
              "id": "event-1",
              "summary": "Intro with Jane",
              "start": {"dateTime": "2026-05-01T15:00:00-04:00"},
              "end": {"dateTime": "2026-05-01T15:30:00-04:00"},
              "attendees": [
                {"email": "user@example.com", "self": true},
                {"email": "Jane@Example.com", "displayName": "Jane Doe"}
              ]
            }
          ]
        }
        """,
        encoding="utf-8",
    )

    events = list(iter_calendar_json_events(calendar_json))

    assert len(events) == 1
    event = events[0]
    assert event.source_name == "calendar"
    assert event.source_event_type == "calendar_event"
    assert event.source_event_key == "calendar:calendar.json:event-1"
    assert event.source_posture == SourcePosture.DIRECT_INTERACTION
    assert event.provenance_status == "calendar_export"
    assert event.trust_role == "calendar attendance evidence"
    assert event.source_payload["summary"] == "Intro with Jane"
    assert event.source_payload["attendees"][1]["email"] == "Jane@Example.com"


def test_calendar_export_paths_include_sorted_json_pages_from_directory(tmp_path: Path):
    export_dir = tmp_path / "calendar-pages"
    export_dir.mkdir()
    (export_dir / "page-2.json").write_text('{"items": []}', encoding="utf-8")
    (export_dir / "notes.txt").write_text("skip", encoding="utf-8")
    (export_dir / "page-1.json").write_text('{"items": []}', encoding="utf-8")

    assert [path.name for path in iter_calendar_export_paths(export_dir)] == ["page-1.json", "page-2.json"]


def test_calendar_json_events_read_embedded_pages(tmp_path: Path):
    calendar_json = tmp_path / "calendar-pages.json"
    calendar_json.write_text(
        """
        {
          "pages": [
            {"items": [{"id": "event-page-1", "summary": "First page"}]},
            {"items": [{"id": "event-page-2", "summary": "Second page"}]}
          ]
        }
        """,
        encoding="utf-8",
    )

    events = list(iter_calendar_json_events(calendar_json))

    assert [event.source_event_key for event in events] == [
        "calendar:calendar-pages.json:event-page-1",
        "calendar:calendar-pages.json:event-page-2",
    ]
    assert [event.source_payload["summary"] for event in events] == ["First page", "Second page"]
