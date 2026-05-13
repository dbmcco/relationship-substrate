from __future__ import annotations

import subprocess
from dataclasses import dataclass
from typing import Any

from relationship_substrate.config import Settings


def parse_query_output(payload: list[dict[str, Any]], *, key_name: str) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for row in payload:
        rows.append(
            {
                key_name: row["key"],
                "message_count": row["count"],
                "total_size": row.get("total_size", 0),
                "attachment_size": row.get("attachment_size", 0),
            }
        )
    return rows


@dataclass(frozen=True)
class MsgvaultAdapter:
    settings: Settings

    def _base_command(self) -> list[str]:
        return [
            self.settings.msgvault_binary,
            "--home",
            self.settings.msgvault_home,
            "--config",
            self.settings.msgvault_config,
        ]

    def build_sender_command(self, limit: int = 100) -> list[str]:
        return [*self._base_command(), "list-senders", "--json", "--limit", str(int(limit))]

    def build_domain_command(self, limit: int = 100) -> list[str]:
        return [*self._base_command(), "list-domains", "--json", "--limit", str(int(limit))]

    def _run_json(self, command: list[str]) -> Any:
        completed = subprocess.run(command, check=True, capture_output=True, text=True)
        import json

        return json.loads(completed.stdout)

    def top_sender_candidates(self, limit: int = 100) -> list[dict[str, Any]]:
        return parse_query_output(self._run_json(self.build_sender_command(limit)), key_name="email")

    def top_domain_candidates(self, limit: int = 100) -> list[dict[str, Any]]:
        return parse_query_output(self._run_json(self.build_domain_command(limit)), key_name="domain")
