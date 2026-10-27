from __future__ import annotations

import json
import logging
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass
from typing import Any

from relationship_substrate.config import Settings

DEFAULT_MSGVAULT_DAEMON_URL = "http://127.0.0.1:8080"

_LOG = logging.getLogger(__name__)


class MalformedPayloadLog:
    """Accumulates malformed-payload skips for one substrate cycle.

    A cycle is one process, so the module-level ``_CYCLE_LOG`` below is
    the default log shared by every :class:`MsgvaultAdapter` constructed
    in that cycle. Each skip is logged immediately (what was skipped and
    why); callers can report the cycle total from ``len(log)``.

    Boundary: only malformed *data* (bad JSON, wrong payload shape, rows
    missing required fields) is skipped and counted. Transport failures
    (connection refused, HTTP errors) still raise -- a down daemon is an
    infrastructure failure, not a bad payload, and silently treating it
    as "no messages" would corrupt the pipeline's picture.
    """

    def __init__(self) -> None:
        self.entries: list[str] = []

    def add(self, reason: str, *, context: str = "") -> None:
        entry = f"{reason} ({context})" if context else reason
        self.entries.append(entry)
        _LOG.warning("msgvault adapter skipped malformed payload: %s", entry)

    def clear(self) -> None:
        self.entries.clear()

    def __len__(self) -> int:
        return len(self.entries)


# One substrate cycle = one process; every adapter in the cycle shares
# this log so the cycle can report a single "how many" total.
_CYCLE_LOG = MalformedPayloadLog()


def _payload_preview(value: object) -> str:
    """Short, safe-to-log preview of a payload fragment."""
    text = repr(value)
    if len(text) > 120:
        return text[:120] + "..."
    return text


def parse_query_output(
    payload: list[dict[str, Any]],
    *,
    key_name: str,
    malformed_log: MalformedPayloadLog | None = None,
) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for row in payload:
        if not isinstance(row, dict) or "key" not in row or row.get("count") is None:
            reason = "query output row missing key/count"
            if malformed_log is not None:
                malformed_log.add(reason, context=_payload_preview(row))
            else:
                _LOG.warning(
                    "msgvault adapter skipped malformed payload: %s (%s)",
                    reason,
                    _payload_preview(row),
                )
            continue
        rows.append(
            {
                key_name: row["key"],
                "message_count": row["count"],
                "total_size": row.get("total_size", 0),
                "attachment_size": row.get("attachment_size", 0),
            }
        )
    return rows


def parse_msgvault_json_output(output: str, *, allow_empty_result: bool = False) -> Any:
    """Tolerant JSON extractor retained for callers that still parse CLI stdout.

    The adapter now routes through the daemon HTTP API (see ``_http_query`` /
    ``_http_search``), so this helper is kept only for backward compatibility and
    for tests that exercise legacy CLI output framing.
    """
    start_candidates = [index for index in (output.find("["), output.find("{")) if index >= 0]
    if not start_candidates:
        if allow_empty_result and output.strip() in {"", "No messages found."}:
            return []
        raise ValueError("msgvault output did not contain JSON")
    start = min(start_candidates)
    end = max(output.rfind("]"), output.rfind("}"))
    if end < start:
        raise ValueError("msgvault output contained incomplete JSON")

    return json.loads(output[start : end + 1])


def _normalize_email(value: object) -> str:
    return str(value or "").strip().lower()


def _message_sort_key(row: dict[str, Any]) -> str:
    return str(row.get("sent_at") or "")


@dataclass(frozen=True)
class MsgvaultAdapter:
    settings: Settings
    malformed_log: MalformedPayloadLog = _CYCLE_LOG

    @property
    def _daemon_url(self) -> str:
        url = getattr(self.settings, "msgvault_daemon_url", "") or DEFAULT_MSGVAULT_DAEMON_URL
        return url.rstrip("/")

    # ------------------------------------------------------------------
    # HTTP primitives (Python stdlib only — no subprocess, no msgvault binary).
    # Spawning the msgvault binary deadlocks under launchd on the production
    # home (pthread_cond_wait); routing read-only SQL/search through the daemon
    # avoids the deadlock entirely.
    # ------------------------------------------------------------------
    def _http_query(self, sql: str) -> list[dict[str, Any]]:
        """Run read-only SQL via POST /api/v1/query; return a list of row dicts.

        Malformed payloads (bad JSON, non-object payload, rows that do
        not match the declared columns) are skipped and counted on the
        adapter's malformed-payload log -- never raised.
        """
        body = json.dumps({"sql": sql}).encode("utf-8")
        request = urllib.request.Request(
            f"{self._daemon_url}/api/v1/query",
            data=body,
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with urllib.request.urlopen(
            request, timeout=self.settings.msgvault_timeout_seconds
        ) as response:
            raw = response.read().decode("utf-8", errors="replace")
        try:
            payload = json.loads(raw)
        except ValueError:
            self.malformed_log.add("query payload was not valid JSON", context=_payload_preview(raw))
            return []
        if not isinstance(payload, dict):
            self.malformed_log.add("query payload was not a JSON object", context=_payload_preview(payload))
            return []
        columns = payload.get("columns") or []
        rows = payload.get("rows") or []
        if not isinstance(columns, list) or not isinstance(rows, list):
            self.malformed_log.add(
                "query payload columns/rows were not lists", context=_payload_preview(payload)
            )
            return []
        out: list[dict[str, Any]] = []
        for row in rows:
            if not isinstance(row, list) or len(row) != len(columns):
                self.malformed_log.add(
                    "query row did not match the declared columns", context=_payload_preview(row)
                )
                continue
            out.append(dict(zip(columns, row)))
        return out

    def _http_search(self, query: str, *, limit: int) -> list[dict[str, Any]]:
        """Lexical search via GET /api/v1/cli/search (the CLI's own backing endpoint).

        The daemon returns ``{"results": [ ... ]}`` where each result is a
        superset of the ``msgvault search --json`` message shape, preserving the
        existing parsed-JSON contract. A payload that is not valid JSON or
        lacks a ``results`` list is skipped and counted, never raised: a
        malformed payload took the whole substrate cycle down mid-run on
        2026-10-27 (ValueError out of ``run_network_pipeline`` while the
        coordination lock was held).
        """
        params = urllib.parse.urlencode({"q": query, "limit": str(int(limit))})
        request = urllib.request.Request(
            f"{self._daemon_url}/api/v1/cli/search?{params}",
            headers={"Accept": "application/json"},
            method="GET",
        )
        with urllib.request.urlopen(
            request, timeout=self.settings.msgvault_timeout_seconds
        ) as response:
            raw = response.read().decode("utf-8", errors="replace")
        try:
            payload = json.loads(raw)
        except ValueError:
            self.malformed_log.add("search payload was not valid JSON", context=_payload_preview(raw))
            return []
        if isinstance(payload, dict) and isinstance(payload.get("results"), list):
            return payload["results"]
        self.malformed_log.add("search payload lacked a results list", context=_payload_preview(payload))
        return []

    # ------------------------------------------------------------------
    # SQL builders. ``v_senders`` / ``v_domains`` are the daemon's analytics
    # convenience views. ``v_domains`` lacks attachment_size, so it is derived
    # from the attachments table to match the CLI ``list-domains`` output.
    # ------------------------------------------------------------------
    @staticmethod
    def build_senders_sql(limit: int = 100) -> str:
        return (
            "SELECT from_email AS key, message_count AS count, "
            "total_size, attachment_size "
            "FROM v_senders ORDER BY message_count DESC "
            f"LIMIT {int(limit)}"
        )

    @staticmethod
    def build_domains_sql(limit: int = 100) -> str:
        return (
            "WITH da AS (SELECT m.from_domain AS dom, SUM(a.size) AS attachment_size "
            "FROM attachments a JOIN v_messages m ON m.id = a.message_id "
            "GROUP BY m.from_domain) "
            "SELECT d.domain AS key, d.message_count AS count, d.total_size, "
            "COALESCE(da.attachment_size, 0) AS attachment_size "
            "FROM v_domains d LEFT JOIN da ON da.dom = d.domain "
            f"ORDER BY d.message_count DESC LIMIT {int(limit)}"
        )

    def top_sender_candidates(self, limit: int = 100) -> list[dict[str, Any]]:
        return parse_query_output(
            self._http_query(self.build_senders_sql(limit)), key_name="email"
        )

    def top_domain_candidates(self, limit: int = 100) -> list[dict[str, Any]]:
        return parse_query_output(
            self._http_query(self.build_domains_sql(limit)), key_name="domain"
        )

    def search_messages(self, query: str, *, limit: int = 50) -> list[dict[str, Any]]:
        return self._http_search(query, limit=limit)

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
                    self.malformed_log.add(
                        "search result row had no message id", context=_payload_preview(row)
                    )
                    continue
                existing = messages.get(message_id)
                if existing is not None and existing.get("relationship_direction") == "from_contact":
                    continue
                normalized = dict(row)
                normalized["relationship_email"] = normalized_email
                normalized["relationship_direction"] = direction
                messages[message_id] = normalized
        return sorted(messages.values(), key=_message_sort_key, reverse=True)[:limit]
