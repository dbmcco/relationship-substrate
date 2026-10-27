import json
import logging
from typing import Any

import pytest

from relationship_substrate.adapters.msgvault import (
    MalformedPayloadLog,
    MsgvaultAdapter,
    _CYCLE_LOG,
    parse_msgvault_json_output,
    parse_query_output,
)
from relationship_substrate.config import Settings
import urllib.request


class _FakeResponse:
    """Minimal stand-in for urllib's HTTPResponse context manager."""

    def __init__(self, payload: Any) -> None:
        if isinstance(payload, (bytes, bytearray)):
            self._data = bytes(payload)
        else:
            self._data = json.dumps(payload).encode("utf-8")

    def read(self) -> bytes:
        return self._data

    def __enter__(self) -> "_FakeResponse":
        return self

    def __exit__(self, *args: object) -> bool:
        return False


def _patch_urlopen(monkeypatch, payload: Any, *, capture: dict | None = None) -> None:
    def fake(request, timeout=None, **kwargs):  # noqa: ANN001
        if capture is not None:
            capture["timeout"] = timeout
        return _FakeResponse(payload)

    monkeypatch.setattr(urllib.request, "urlopen", fake)


# --------------------------------------------------------------------------
# Pure helpers (unchanged behaviour)
# --------------------------------------------------------------------------
def test_parse_query_output_returns_rows():
    payload = [{"key": "person@example.com", "count": 7, "total_size": 100}]

    rows = parse_query_output(payload, key_name="email")

    assert rows == [
        {
            "email": "person@example.com",
            "message_count": 7,
            "total_size": 100,
            "attachment_size": 0,
        }
    ]


def test_parse_msgvault_json_output_tolerates_cli_status_logs():
    output = """time=2026-05-13T16:27:19-04:00 level=INFO msg="search start"
Searching...
[
  {
    "id": 25075,
    "from_email": "andrew@example.com",
    "sent_at": "2022-04-07T07:57:03Z",
    "subject": "Re: Pharma Forum"
  }
]
time=2026-05-13T16:27:19-04:00 level=INFO msg="msgvault exit"
"""

    rows = parse_msgvault_json_output(output)

    assert rows == [
        {
            "id": 25075,
            "from_email": "andrew@example.com",
            "sent_at": "2022-04-07T07:57:03Z",
            "subject": "Re: Pharma Forum",
        }
    ]


# --------------------------------------------------------------------------
# SQL builders (senders + domains routed through /api/v1/query)
# --------------------------------------------------------------------------
def test_senders_sql_targets_v_senders_with_limit():
    sql = MsgvaultAdapter.build_senders_sql(10)

    assert "FROM v_senders" in sql
    assert "from_email AS key" in sql
    assert "message_count AS count" in sql
    assert "attachment_size" in sql
    assert sql.rstrip().endswith("LIMIT 10")


def test_domains_sql_targets_v_domains_and_derives_attachment_size():
    sql = MsgvaultAdapter.build_domains_sql(5)

    # v_domains has no attachment_size column; it must be derived from attachments.
    assert "FROM v_domains" in sql
    assert "attachments" in sql
    assert "SUM(a.size)" in sql
    assert "domain AS key" in sql
    assert sql.rstrip().endswith("LIMIT 5")


# --------------------------------------------------------------------------
# HTTP primitives
# --------------------------------------------------------------------------
def test_http_query_zips_columns_into_row_dicts(monkeypatch):
    adapter = MsgvaultAdapter(Settings())
    _patch_urlopen(
        monkeypatch,
        {"columns": ["key", "count", "total_size", "attachment_size"],
         "rows": [["a@x.com", 5, 100, 10]]},
    )

    rows = adapter._http_query("SELECT 1")

    assert rows == [
        {"key": "a@x.com", "count": 5, "total_size": 100, "attachment_size": 10}
    ]


def test_http_search_returns_results_list(monkeypatch):
    adapter = MsgvaultAdapter(Settings())
    _patch_urlopen(monkeypatch, {"results": [{"id": 1, "from_email": "a@x.com"}]})

    rows = adapter._http_search("from:a@x.com", limit=5)

    assert rows == [{"id": 1, "from_email": "a@x.com"}]


def test_http_search_returns_empty_when_no_results(monkeypatch):
    adapter = MsgvaultAdapter(Settings())
    _patch_urlopen(monkeypatch, {"results": []})

    assert adapter.search_messages("from:missing@example.com") == []


def test_http_search_skips_and_counts_malformed_payload(monkeypatch, caplog):
    """2026-10-27 crash class: a malformed search payload raised ValueError
    and took the whole substrate cycle down mid-run. It must instead be
    skipped, counted, and logged -- never raised."""
    log = MalformedPayloadLog()
    adapter = MsgvaultAdapter(Settings(), malformed_log=log)
    _patch_urlopen(monkeypatch, {"unexpected": True})

    with caplog.at_level(logging.WARNING, logger="relationship_substrate.adapters.msgvault"):
        rows = adapter.search_messages("from:broken@example.com")

    assert rows == []
    assert len(log) == 1
    assert "results" in log.entries[0]
    assert any("malformed payload" in record.message for record in caplog.records)


def test_http_search_skips_and_counts_non_json_payload(monkeypatch):
    log = MalformedPayloadLog()
    adapter = MsgvaultAdapter(Settings(), malformed_log=log)
    _patch_urlopen(monkeypatch, b"<html>gateway error</html>")

    assert adapter.search_messages("from:down@example.com") == []
    assert len(log) == 1
    assert "not valid JSON" in log.entries[0]


# --------------------------------------------------------------------------
# Public contract
# --------------------------------------------------------------------------
def test_top_sender_candidates_maps_rows_to_email_counts(monkeypatch):
    adapter = MsgvaultAdapter(Settings())
    monkeypatch.setattr(
        MsgvaultAdapter,
        "_http_query",
        lambda self, sql: [{"key": "a@x.com", "count": 9, "total_size": 200, "attachment_size": 40}],
    )

    rows = adapter.top_sender_candidates(limit=1)

    assert rows == [
        {"email": "a@x.com", "message_count": 9, "total_size": 200, "attachment_size": 40}
    ]


def test_top_domain_candidates_maps_rows_to_domain_counts(monkeypatch):
    adapter = MsgvaultAdapter(Settings())
    monkeypatch.setattr(
        MsgvaultAdapter,
        "_http_query",
        lambda self, sql: [{"key": "x.com", "count": 3, "total_size": 50, "attachment_size": 5}],
    )

    rows = adapter.top_domain_candidates(limit=1)

    assert rows == [
        {"domain": "x.com", "message_count": 3, "total_size": 50, "attachment_size": 5}
    ]


def test_correspondence_messages_returns_empty_when_both_searches_have_no_results(monkeypatch):
    adapter = MsgvaultAdapter(Settings())
    queries: list[str] = []
    monkeypatch.setattr(
        MsgvaultAdapter, "search_messages",
        lambda self, query, *, limit=50: (queries.append(query) or []),
    )

    rows = adapter.correspondence_messages("missing@example.com", limit=10)

    assert rows == []
    assert queries == ["from:missing@example.com", "to:missing@example.com"]


def test_correspondence_messages_deduplicates_from_and_to_results(monkeypatch):
    adapter = MsgvaultAdapter(Settings())
    shared = {
        "id": 1,
        "from_email": "andrew@example.com",
        "from_name": "Andrew",
        "sent_at": "2024-01-02T00:00:00Z",
        "subject": "Inbound",
        "snippet": "hello",
    }
    outbound = {
        "id": 2,
        "from_email": "user@example.com",
        "from_name": "Example User",
        "sent_at": "2024-01-03T00:00:00Z",
        "subject": "Outbound",
        "snippet": "reply",
    }

    def fake_search(self, query, *, limit=50):
        return [shared] if query.startswith("from:") else [shared, outbound]

    monkeypatch.setattr(MsgvaultAdapter, "search_messages", fake_search)

    rows = adapter.correspondence_messages("andrew@example.com", limit=10)

    assert [row["id"] for row in rows] == [2, 1]
    assert rows[0]["relationship_email"] == "andrew@example.com"
    assert rows[0]["relationship_direction"] == "to_contact"
    assert rows[1]["relationship_direction"] == "from_contact"


# --------------------------------------------------------------------------
# Timeout / configuration
# --------------------------------------------------------------------------
def test_http_calls_use_configured_timeout(monkeypatch):
    adapter = MsgvaultAdapter(Settings(msgvault_timeout_seconds=7))
    captured: dict[str, Any] = {}
    _patch_urlopen(monkeypatch, {"columns": [], "rows": []}, capture=captured)

    adapter._http_query("SELECT 1")

    assert captured.get("timeout") == 7


# --------------------------------------------------------------------------
# Malformed-payload tolerance (2026-10-27 crash class)
# --------------------------------------------------------------------------
def test_http_query_skips_and_counts_non_json_payload(monkeypatch):
    log = MalformedPayloadLog()
    adapter = MsgvaultAdapter(Settings(), malformed_log=log)
    _patch_urlopen(monkeypatch, b"not json at all")

    assert adapter._http_query("SELECT 1") == []
    assert len(log) == 1
    assert "not valid JSON" in log.entries[0]


def test_http_query_skips_and_counts_non_object_payload(monkeypatch):
    log = MalformedPayloadLog()
    adapter = MsgvaultAdapter(Settings(), malformed_log=log)
    _patch_urlopen(monkeypatch, [1, 2, 3])

    assert adapter._http_query("SELECT 1") == []
    assert len(log) == 1
    assert "not a JSON object" in log.entries[0]


def test_http_query_skips_rows_that_do_not_match_columns(monkeypatch):
    log = MalformedPayloadLog()
    adapter = MsgvaultAdapter(Settings(), malformed_log=log)
    _patch_urlopen(monkeypatch, {"columns": ["email", "count"], "rows": [["a@x.com", 5], ["b@x.com"]]})

    rows = adapter._http_query("SELECT ...")

    assert rows == [{"email": "a@x.com", "count": 5}]
    assert len(log) == 1
    assert "declared columns" in log.entries[0]


def test_correspondence_messages_skips_and_counts_rows_without_message_id(monkeypatch):
    log = MalformedPayloadLog()
    adapter = MsgvaultAdapter(Settings(), malformed_log=log)
    _patch_urlopen(
        monkeypatch,
        {
            "results": [
                {"id": 7, "sent_at": "2026-01-01T00:00:00Z"},
                {"subject": "row with no id"},
            ]
        },
    )

    rows = adapter.correspondence_messages("a@x.com", limit=10)

    assert [row["id"] for row in rows] == [7]
    # from: and to: searches each return the malformed row once.
    assert len(log) == 2
    assert all("no message id" in entry for entry in log.entries)


def test_parse_query_output_skips_rows_missing_required_keys():
    log = MalformedPayloadLog()
    payload = [
        {"key": "a@x.com", "count": 3, "total_size": 10},
        {"key": "b@x.com"},  # no count
        {"count": 4},  # no key
        "not even a dict",
    ]

    rows = parse_query_output(payload, key_name="email", malformed_log=log)

    assert rows == [
        {
            "email": "a@x.com",
            "message_count": 3,
            "total_size": 10,
            "attachment_size": 0,
        }
    ]
    assert len(log) == 3


def test_default_malformed_log_is_shared_per_cycle():
    # One substrate cycle is one process: every adapter constructed in the
    # cycle must share one log so the cycle can report a single total.
    one = MsgvaultAdapter(Settings())
    two = MsgvaultAdapter(Settings())

    assert one.malformed_log is two.malformed_log
    assert one.malformed_log is _CYCLE_LOG


def test_ingest_msgvault_correspondence_survives_malformed_payload(monkeypatch):
    """The exact 2026-10-27 crash: a malformed search payload raised
    ValueError inside _ingest_msgvault_correspondence and killed the
    substrate cycle mid-run (while holding the coordination lock). The
    ingest must return empty stats, count the skip in the cycle log,
    and never raise."""
    from relationship_substrate.operations import _ingest_msgvault_correspondence

    _CYCLE_LOG.clear()
    _patch_urlopen(monkeypatch, {"unexpected": True})

    stats = _ingest_msgvault_correspondence(
        Settings(), email="broken@example.com", limit=5
    )

    assert stats["events_seen"] == 0
    assert stats["events_upserted"] == 0
    # from: and to: searches both hit the malformed payload.
    assert len(_CYCLE_LOG) == 2
    _CYCLE_LOG.clear()
