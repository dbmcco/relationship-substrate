from __future__ import annotations

import json
import subprocess
from dataclasses import dataclass
from typing import Any

from relationship_substrate.config import Settings


def parse_query_output(payload: dict[str, Any]) -> list[dict[str, Any]]:
    columns = payload["columns"]
    return [dict(zip(columns, row, strict=True)) for row in payload["rows"]]


@dataclass(frozen=True)
class MsgvaultAdapter:
    settings: Settings

    def build_query_command(self, sql: str) -> list[str]:
        _ = sql
        return [
            self.settings.msgvault_binary,
            "--home",
            self.settings.msgvault_home,
            "--config",
            self.settings.msgvault_config,
            "query",
            "--format",
            "json",
        ]

    def top_sender_candidates(self, limit: int = 100) -> list[dict[str, Any]]:
        sql = f"""
        SELECT from_email, from_name, message_count, first_seen, last_seen
        FROM v_senders
        ORDER BY message_count DESC
        LIMIT {int(limit)}
        """
        completed = subprocess.run(
            [*self.build_query_command(sql), sql],
            check=True,
            capture_output=True,
            text=True,
        )
        return parse_query_output(json.loads(completed.stdout))
