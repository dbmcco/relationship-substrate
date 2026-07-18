import subprocess

import pytest

from relationship_substrate.adapters.msgvault import (
    MsgvaultAdapter,
    parse_msgvault_json_output,
    parse_query_output,
)
from relationship_substrate.config import Settings


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


def test_sender_command_uses_supported_msgvault_analytics_cli():
    adapter = MsgvaultAdapter(Settings())

    command = adapter.build_sender_command(10)

    assert command[0] == "msgvault"
    assert command[1] == "--home"
    assert command[3] == "--config"
    assert command[5] == "--local"
    assert command[-4:] == ["list-senders", "--json", "--limit", "10"]


def test_domain_command_uses_supported_msgvault_analytics_cli():
    adapter = MsgvaultAdapter(Settings())

    command = adapter.build_domain_command(5)

    assert command[-4:] == ["list-domains", "--json", "--limit", "5"]


def test_msgvault_client_uses_bounded_timeout(monkeypatch):
    adapter = MsgvaultAdapter(Settings(msgvault_timeout_seconds=7))
    captured = {}

    def fake_run(command, **kwargs):
        captured.update(kwargs)
        return subprocess.CompletedProcess(command, 0, stdout="[]", stderr="")

    monkeypatch.setattr(subprocess, "run", fake_run)

    assert adapter.top_sender_candidates(limit=1) == []
    assert captured["timeout"] == 7


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


@pytest.mark.parametrize("stdout", ["", "No messages found.\n"])
def test_search_messages_treats_empty_or_no_result_output_as_empty(monkeypatch, stdout):
    adapter = MsgvaultAdapter(Settings())

    def fake_run(command, **kwargs):
        assert kwargs["check"] is True
        assert kwargs["capture_output"] is True
        assert kwargs["text"] is True
        return subprocess.CompletedProcess(command, 0, stdout=stdout, stderr="")

    monkeypatch.setattr(subprocess, "run", fake_run)

    rows = adapter.search_messages("from:missing@example.com")

    assert rows == []


def test_search_messages_rejects_malformed_non_empty_output(monkeypatch):
    adapter = MsgvaultAdapter(Settings())

    def fake_run(command, **kwargs):
        return subprocess.CompletedProcess(command, 0, stdout="not json\n", stderr="")

    monkeypatch.setattr(subprocess, "run", fake_run)

    with pytest.raises(ValueError, match="msgvault output did not contain JSON"):
        adapter.search_messages("from:broken@example.com")


def test_correspondence_messages_returns_empty_when_both_searches_have_no_results(monkeypatch):
    adapter = MsgvaultAdapter(Settings())
    commands = []

    def fake_run(command, **kwargs):
        commands.append(command)
        return subprocess.CompletedProcess(command, 0, stdout="No messages found.\n", stderr="")

    monkeypatch.setattr(subprocess, "run", fake_run)

    rows = adapter.correspondence_messages("missing@example.com", limit=10)

    assert rows == []
    assert [command[-4] for command in commands] == [
        "from:missing@example.com",
        "to:missing@example.com",
    ]


def test_correspondence_messages_deduplicates_from_and_to_results(monkeypatch):
    adapter = MsgvaultAdapter(Settings())
    calls = []

    def fake_run_json(command):
        calls.append(command)
        if "from:andrew@example.com" in command:
            return [
                {
                    "id": 1,
                    "from_email": "andrew@example.com",
                    "from_name": "Andrew",
                    "sent_at": "2024-01-02T00:00:00Z",
                    "subject": "Inbound",
                    "snippet": "hello",
                }
            ]
        return [
            {
                "id": 1,
                "from_email": "andrew@example.com",
                "from_name": "Andrew",
                "sent_at": "2024-01-02T00:00:00Z",
                "subject": "Inbound",
                "snippet": "hello",
            },
            {
                "id": 2,
                "from_email": "user@example.com",
                "from_name": "Example User",
                "sent_at": "2024-01-03T00:00:00Z",
                "subject": "Outbound",
                "snippet": "reply",
            },
        ]

    monkeypatch.setattr(MsgvaultAdapter, "_run_json", lambda _self, command, **_kwargs: fake_run_json(command))

    rows = adapter.correspondence_messages("andrew@example.com", limit=10)

    assert [row["id"] for row in rows] == [2, 1]
    assert rows[0]["relationship_email"] == "andrew@example.com"
    assert rows[0]["relationship_direction"] == "to_contact"
    assert rows[1]["relationship_direction"] == "from_contact"
    assert len(calls) == 2
