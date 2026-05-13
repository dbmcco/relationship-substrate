from __future__ import annotations

from datetime import UTC, datetime


def _parse_datetime(value: str) -> datetime:
    normalized = value[:-1] + "+00:00" if value.endswith("Z") else value
    parsed = datetime.fromisoformat(normalized)
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=UTC)
    return parsed.astimezone(UTC)


def relationship_freshness(
    last_interaction_at: str | None,
    *,
    as_of: datetime | None = None,
) -> dict[str, int | str | None]:
    if not last_interaction_at:
        return {
            "state": "unknown",
            "days_since_last_interaction": None,
            "basis": "no_materialized_interaction",
        }

    as_of = as_of or datetime.now(UTC)
    if as_of.tzinfo is None:
        as_of = as_of.replace(tzinfo=UTC)
    else:
        as_of = as_of.astimezone(UTC)
    last_seen = _parse_datetime(last_interaction_at)
    days = max((as_of.date() - last_seen.date()).days, 0)

    if days <= 30:
        state = "recent"
    elif days <= 120:
        state = "active"
    elif days <= 365:
        state = "stale"
    else:
        state = "dormant"

    return {
        "state": state,
        "days_since_last_interaction": days,
        "basis": "last_materialized_interaction_at",
    }
