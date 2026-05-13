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


def parse_msgvault_json_output(output: str) -> Any:
    start_candidates = [index for index in (output.find("["), output.find("{")) if index >= 0]
    if not start_candidates:
        raise ValueError("msgvault output did not contain JSON")
    start = min(start_candidates)
    end = max(output.rfind("]"), output.rfind("}"))
    if end < start:
        raise ValueError("msgvault output contained incomplete JSON")

    import json

    return json.loads(output[start : end + 1])


def _normalize_email(value: object) -> str:
    return str(value or "").strip().lower()


def _message_sort_key(row: dict[str, Any]) -> str:
    return str(row.get("sent_at") or "")


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

    def build_search_command(self, query: str, *, limit: int = 50) -> list[str]:
        return [*self._base_command(), "search", query, "--json", "--limit", str(int(limit))]

    def _run_json(self, command: list[str]) -> Any:
        completed = subprocess.run(command, check=True, capture_output=True, text=True)
        return parse_msgvault_json_output(completed.stdout)

    def top_sender_candidates(self, limit: int = 100) -> list[dict[str, Any]]:
        return parse_query_output(self._run_json(self.build_sender_command(limit)), key_name="email")

    def top_domain_candidates(self, limit: int = 100) -> list[dict[str, Any]]:
        return parse_query_output(self._run_json(self.build_domain_command(limit)), key_name="domain")

    def search_messages(self, query: str, *, limit: int = 50) -> list[dict[str, Any]]:
        payload = self._run_json(self.build_search_command(query, limit=limit))
        if not isinstance(payload, list):
            raise ValueError("msgvault search returned non-list JSON")
        return payload

    def correspondence_messages(self, email: str, *, limit: int = 50) -> list[dict[str, Any]]:
        normalized_email = _normalize_email(email)
        messages: dict[str, dict[str, Any]] = {}
        for query, direction in (
            (f"from:{normalized_email}", "from_contact"),
            (f"to:{normalized_email}", "to_contact"),
        ):
            for row in self.search_messages(query, limit=limit):
                message_id = str(row.get("id") or row.get("source_message_id") or "")
                if not message_id:
                    continue
                existing = messages.get(message_id)
                if existing is not None and existing.get("relationship_direction") == "from_contact":
                    continue
                normalized = dict(row)
                normalized["relationship_email"] = normalized_email
                normalized["relationship_direction"] = direction
                messages[message_id] = normalized
        return sorted(messages.values(), key=_message_sort_key, reverse=True)[:limit]
