from relationship_substrate.adapters.msgvault import MsgvaultAdapter, parse_query_output
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

    assert command[:5] == [
        "/Users/braydon/.local/bin/msgvault",
        "--home",
        "/Volumes/data2/msgvault",
        "--config",
        "/Volumes/data2/msgvault/config.toml",
    ]
    assert command[-4:] == ["list-senders", "--json", "--limit", "10"]


def test_domain_command_uses_supported_msgvault_analytics_cli():
    adapter = MsgvaultAdapter(Settings())

    command = adapter.build_domain_command(5)

    assert command[-4:] == ["list-domains", "--json", "--limit", "5"]
