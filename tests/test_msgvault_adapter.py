from relationship_substrate.adapters.msgvault import MsgvaultAdapter, parse_query_output
from relationship_substrate.config import Settings


def test_parse_query_output_returns_rows():
    payload = {
        "columns": ["from_email", "message_count"],
        "rows": [["person@example.com", 7]],
        "row_count": 1,
    }

    rows = parse_query_output(payload)

    assert rows == [{"from_email": "person@example.com", "message_count": 7}]


def test_sender_query_command_uses_msgvault_read_only_cli():
    adapter = MsgvaultAdapter(Settings())

    command = adapter.build_query_command("SELECT * FROM v_senders LIMIT 1")

    assert command[:5] == [
        "/Users/braydon/.local/bin/msgvault",
        "--home",
        "/Volumes/data2/msgvault",
        "--config",
        "/Volumes/data2/msgvault/config.toml",
    ]
    assert command[-3:] == ["query", "--format", "json"]
