from __future__ import annotations

from typing import Any
from uuid import UUID

import psycopg
from psycopg.types.json import Jsonb


def _person_summary(person: dict[str, Any]) -> dict[str, Any]:
    return {
        "email": person.get("email"),
        "search_hit": person.get("search_hit"),
        "packet_readiness": person.get("packet_readiness"),
        "evidence_summary": person.get("evidence_summary"),
        "organization_context": person.get("organization_context"),
        "model_inputs": person.get("model_inputs"),
    }


def _source_refs(packet: dict[str, Any]) -> dict[str, Any]:
    people: list[dict[str, Any]] = []
    for person in packet.get("people", []):
        people.append(
            {
                "email": person.get("email"),
                "evidence_refs": (person.get("model_inputs") or {}).get("candidate_evidence_refs", []),
                "research_refs": (person.get("model_inputs") or {}).get("candidate_research_refs", []),
            }
        )
    return {
        "people": people,
        "research_sources": [
            str(source.get("id") or source.get("url") or source.get("source_url"))
            for source in (packet.get("research_context") or {}).get("sources", [])
            if source.get("id") or source.get("url") or source.get("source_url")
        ],
    }


def _packet_summary(packet: dict[str, Any]) -> dict[str, Any]:
    return {
        "ask_stage": packet.get("ask_stage"),
        "count": packet.get("count"),
        "people": [_person_summary(person) for person in packet.get("people", [])],
        "research_context": packet.get("research_context"),
    }


def _model_recommendations(packet: dict[str, Any]) -> list[dict[str, Any]]:
    validation = packet.get("model_recommendation_validation") or {}
    return validation.get("ranked_recommendations") or []


def _row_to_packet(row: tuple) -> dict[str, Any]:
    return {
        "id": str(row[0]),
        "packet_kind": row[1],
        "contract_version": row[2],
        "query": row[3],
        "readiness": row[4],
        "packet_summary": row[5],
        "source_refs": row[6],
        "model_recommendations": row[7],
        "created_at": row[8].isoformat() if row[8] else None,
    }


def persist_ask_network_packet(database_url: str, packet: dict[str, Any]) -> dict[str, Any]:
    with psycopg.connect(database_url) as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO relationship_substrate.network_packet (
                  packet_kind,
                  contract_version,
                  query,
                  readiness,
                  packet_summary,
                  source_refs,
                  model_recommendations
                )
                VALUES ('ask_network', %s, %s, %s, %s, %s, %s)
                RETURNING
                  id, packet_kind, contract_version, query, readiness,
                  packet_summary, source_refs, model_recommendations, created_at
                """,
                (
                    int(packet.get("contract_version") or 0),
                    Jsonb(packet.get("query") or {}),
                    Jsonb(packet.get("readiness") or {}),
                    Jsonb(_packet_summary(packet)),
                    Jsonb(_source_refs(packet)),
                    Jsonb(_model_recommendations(packet)),
                ),
            )
            row = cur.fetchone()
        conn.commit()
    if row is None:
        raise RuntimeError("network_packet insert returned no row")
    return _row_to_packet(row)


def get_network_packet(database_url: str, *, packet_id: str) -> dict[str, Any]:
    with psycopg.connect(database_url) as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT
                  id, packet_kind, contract_version, query, readiness,
                  packet_summary, source_refs, model_recommendations, created_at
                FROM relationship_substrate.network_packet
                WHERE id = %s
                """,
                (UUID(packet_id),),
            )
            row = cur.fetchone()
    if row is None:
        raise ValueError(f"network_packet not found: {packet_id}")
    return _row_to_packet(row)
