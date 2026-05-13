from pathlib import Path

from openpyxl import Workbook

from relationship_substrate.adapters.next_up import iter_people_workbook_events
from relationship_substrate.contracts import SourcePosture


def test_people_workbook_rows_are_unknown_upstream_curated_exports(tmp_path: Path):
    workbook = tmp_path / "people.xlsx"
    wb = Workbook()
    ws = wb.active
    ws.title = "Contacts"
    ws.append(["First Name", "Last Name", "Title", "Company", "Email"])
    ws.append(["Jane", "Doe", "VP Product", "ExampleCo", "jane@example.com"])
    wb.save(workbook)

    events = list(iter_people_workbook_events(workbook))

    assert len(events) == 1
    assert events[0].source_posture == SourcePosture.CURATED_EXPORT
    assert events[0].provenance_status == "unknown_upstream"
    assert events[0].trust_role == "identity/context seed"
    assert events[0].source_payload["email"] == "jane@example.com"
