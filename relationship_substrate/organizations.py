from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

import psycopg
from psycopg.types.json import Jsonb

from relationship_substrate.freshness import relationship_freshness


DEFAULT_SKIPPED_ORGANIZATION_DOMAINS = {
    "aol.com",
    "gmail.com",
    "go2impact.com",
    "hotmail.com",
    "icloud.com",
    "intempio.com",
    "intempio.us",
    "lehigh.edu",
    "linkedin.com",
    "live.com",
    "me.com",
    "mcco.us",
    "msn.com",
    "outlook.com",
    "proton.me",
    "protonmail.com",
    "rvibe.com",
    "thepracticalaccountant.com",
    "yahoo.com",
}

ENRICHMENT_VALUE_FIELDS = (
    "company_type",
    "employee_count_label",
    "employee_count_min",
    "employee_count_max",
    "consultant_count_estimate",
)


def _clean_text(value: object) -> str:
    return str(value or "").strip()


def _clean_lookup_value(value: object) -> str:
    return _clean_text(value).lower()


def _clean_aliases(values: object) -> list[str]:
    if values is None:
        return []
    if isinstance(values, str):
        values = [values]
    if not isinstance(values, list | tuple | set):
        return []
    aliases: list[str] = []
    seen: set[str] = set()
    for value in values:
        alias = _clean_lookup_value(value)
        if alias and alias not in seen:
            aliases.append(alias)
            seen.add(alias)
    return aliases


def _enrichment_reasons(
    *,
    has_enrichment: bool,
    direct_people_count: int,
    known_people_count: int,
    total_interaction_count: int,
    calendar_interaction_count: int,
) -> list[str]:
    reasons: list[str] = []
    if not has_enrichment:
        reasons.append("missing_organization_enrichment")
    if total_interaction_count > 0:
        reasons.append("direct_history_present")
    if calendar_interaction_count > 0:
        reasons.append("calendar_history_present")
    if direct_people_count > 1:
        reasons.append("multiple_direct_people")
    if known_people_count > 1:
        reasons.append("multiple_known_people")
    return reasons


def _has_actionable_enrichment(enrichment: dict[str, Any] | None) -> bool:
    if not enrichment:
        return False
    return any(enrichment.get(field) not in (None, "") for field in ENRICHMENT_VALUE_FIELDS)


def upsert_organization_enrichment(
    database_url: str,
    *,
    company_name: str,
    domain: str | None = None,
    aliases: list[str] | None = None,
    company_type: str | None = None,
    employee_count_min: int | None = None,
    employee_count_max: int | None = None,
    employee_count_label: str | None = None,
    consultant_count_estimate: int | None = None,
    source_name: str,
    source_url: str | None = None,
    provenance_status: str,
) -> dict[str, Any]:
    name = _clean_text(company_name)
    if not name:
        raise ValueError("company_name is required")
    normalized_domain = _clean_lookup_value(domain)
    normalized_aliases = [
        alias
        for alias in _clean_aliases(aliases)
        if alias not in {name.lower(), normalized_domain}
    ]
    enrichment = {
        "company_type": company_type,
        "employee_count_label": employee_count_label,
        "employee_count_min": employee_count_min,
        "employee_count_max": employee_count_max,
        "consultant_count_estimate": consultant_count_estimate,
        "source_name": source_name,
        "source_url": source_url,
        "provenance_status": provenance_status,
    }
    if normalized_domain:
        enrichment["domain"] = normalized_domain
    if normalized_aliases:
        enrichment["aliases"] = normalized_aliases
    with psycopg.connect(database_url) as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT id
                FROM relationship_substrate.organization
                WHERE lower(name) = lower(%s)
                OR (%s::text IS NOT NULL AND lower(domain) = %s)
                OR (%s::text IS NOT NULL AND (metadata->'enrichment'->'aliases') ? %s)
                ORDER BY updated_at DESC
                LIMIT 1
                """,
                (
                    name,
                    normalized_domain or None,
                    normalized_domain,
                    normalized_domain or None,
                    normalized_domain,
                ),
            )
            row = cur.fetchone()
            if row is None:
                cur.execute(
                    """
                    INSERT INTO relationship_substrate.organization (
                      name, domain, source_posture, provenance_status, metadata
                    )
                    VALUES (%s, %s, 'enrichment', %s, %s)
                    RETURNING id
                    """,
                    (name, normalized_domain or None, provenance_status, Jsonb({"enrichment": enrichment})),
                )
                organization_id = cur.fetchone()[0]
            else:
                organization_id = row[0]
                cur.execute(
                    """
                    UPDATE relationship_substrate.organization
                    SET
                      domain = COALESCE(%s, domain),
                      source_posture = 'enrichment',
                      provenance_status = %s,
                      metadata = metadata || %s,
                      updated_at = now()
                    WHERE id = %s
                    """,
                    (
                        normalized_domain or None,
                        provenance_status,
                        Jsonb({"enrichment": enrichment}),
                        organization_id,
                    ),
                )
        conn.commit()
    return {"organization_id": str(organization_id), "company_name": name, "enrichment": enrichment}


def organization_enrichment_by_name(database_url: str) -> dict[str, dict[str, Any]]:
    with psycopg.connect(database_url) as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT
                  lower(name),
                  lower(domain),
                  metadata->'enrichment'
                FROM relationship_substrate.organization
                WHERE metadata ? 'enrichment'
                ORDER BY updated_at
                """
            )
            rows = cur.fetchall()
    enrichments: dict[str, dict[str, Any]] = {}
    for name, domain, enrichment in rows:
        if not _has_actionable_enrichment(enrichment):
            continue
        enrichments[name] = enrichment
        if domain:
            enrichments[domain] = enrichment
        for alias in enrichment.get("aliases") or []:
            clean_alias = _clean_lookup_value(alias)
            if clean_alias:
                enrichments[clean_alias] = enrichment
    return enrichments


def organization_enrichment_worklist(database_url: str, *, limit: int = 50) -> list[dict[str, Any]]:
    enrichments = organization_enrichment_by_name(database_url)
    with psycopg.connect(database_url) as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                WITH curated AS (
                  SELECT
                    nullif(source_payload->>'company', '') AS company_name,
                    nullif(source_payload->>'title', '') AS title
                  FROM relationship_substrate.source_event
                  WHERE source_name = 'next_up'
                  AND source_event_type = 'curated_contact'
                  AND nullif(source_payload->>'company', '') IS NOT NULL
                ),
                ranked_titles AS (
                  SELECT
                    company_name,
                    title,
                    row_number() OVER (
                      PARTITION BY company_name
                      ORDER BY title
                    ) AS title_rank
                  FROM (
                    SELECT DISTINCT company_name, title
                    FROM curated
                    WHERE title IS NOT NULL
                  ) titles
                ),
                company_counts AS (
                  SELECT company_name, count(*)::int AS known_people_at_company_count
                  FROM curated
                  GROUP BY company_name
                ),
                title_samples AS (
                  SELECT
                    company_name,
                    array_agg(title ORDER BY title) FILTER (WHERE title_rank <= 5) AS sample_titles
                  FROM ranked_titles
                  GROUP BY company_name
                )
                SELECT
                  cc.company_name,
                  cc.known_people_at_company_count,
                  COALESCE(ts.sample_titles, ARRAY[]::text[]) AS sample_titles
                FROM company_counts cc
                LEFT JOIN title_samples ts
                  ON ts.company_name = cc.company_name
                ORDER BY
                  CASE WHEN lower(cc.company_name) = ANY(%s) THEN 1 ELSE 0 END,
                  cc.known_people_at_company_count DESC,
                  cc.company_name
                LIMIT %s
                """,
                (list(enrichments.keys()), limit),
            )
            rows = cur.fetchall()
    return [
        {
            "company_name": row[0],
            "known_people_at_company_count": row[1],
            "has_enrichment": row[0].lower() in enrichments,
            "organization_enrichment": enrichments.get(row[0].lower()),
            "sample_titles": list(dict.fromkeys(row[2] or [])),
            "research_prompt": (
                "Find actual organization size, company type, whether this is a medcoms/medical "
                f"communications consultancy, and source URLs for {row[0]}."
            ),
        }
        for row in rows
    ]


def history_backed_organization_worklist(
    database_url: str,
    *,
    limit: int = 50,
    skipped_domains: set[str] | None = None,
    skipped_system_localparts: set[str] | None = None,
    skipped_system_prefixes: set[str] | None = None,
    missing_enrichment_only: bool = False,
    as_of: datetime | None = None,
) -> list[dict[str, Any]]:
    skipped = sorted(DEFAULT_SKIPPED_ORGANIZATION_DOMAINS | set(skipped_domains or set()))
    skipped_localparts = sorted(skipped_system_localparts or set())
    skipped_prefixes = sorted(skipped_system_prefixes or set())
    enrichments = organization_enrichment_by_name(database_url)
    enriched_names = sorted(enrichments.keys())
    missing_filter = (
        "WHERE lower(COALESCE(dc.company_name, d.domain)) <> ALL(%s)"
        if missing_enrichment_only
        else ""
    )
    params: list[object] = [skipped, skipped, skipped_localparts, skipped_localparts, skipped_prefixes]
    if missing_enrichment_only:
        params.append(enriched_names)
    params.append(limit)
    with psycopg.connect(database_url) as conn:
        with conn.cursor() as cur:
            cur.execute(
                f"""
                WITH curated AS (
                  SELECT
                    lower(nullif(source_payload->>'email', '')) AS email,
                    split_part(lower(nullif(source_payload->>'email', '')), '@', 2) AS domain,
                    nullif(source_payload->>'company', '') AS company_name,
                    nullif(source_payload->>'title', '') AS title
                  FROM relationship_substrate.source_event
                  WHERE source_name = 'next_up'
                  AND source_event_type = 'curated_contact'
                  AND nullif(source_payload->>'email', '') IS NOT NULL
                  AND split_part(lower(source_payload->>'email'), '@', 2) <> ALL(%s)
                ),
                curated_company_counts AS (
                  SELECT
                    domain,
                    company_name,
                    count(*)::int AS company_count,
                    row_number() OVER (
                      PARTITION BY domain
                      ORDER BY count(*) DESC, company_name
                    ) AS company_rank
                  FROM curated
                  WHERE domain IS NOT NULL
                  AND domain <> ''
                  AND company_name IS NOT NULL
                  GROUP BY domain, company_name
                ),
                domain_companies AS (
                  SELECT domain, company_name
                  FROM curated_company_counts
                  WHERE company_rank = 1
                ),
                ranked_titles AS (
                  SELECT
                    domain,
                    title,
                    row_number() OVER (
                      PARTITION BY domain
                      ORDER BY title
                    ) AS title_rank
                  FROM (
                    SELECT DISTINCT domain, title
                    FROM curated
                    WHERE title IS NOT NULL
                  ) titles
                ),
                domain_title_samples AS (
                  SELECT
                    domain,
                    array_agg(title ORDER BY title) FILTER (WHERE title_rank <= 5) AS sample_titles
                  FROM ranked_titles
                  GROUP BY domain
                ),
                curated_domain_counts AS (
                  SELECT
                    domain,
                    count(DISTINCT email)::int AS known_people_count
                  FROM curated
                  WHERE domain IS NOT NULL
                  AND domain <> ''
                  GROUP BY domain
                ),
                curated_email_titles AS (
                  SELECT
                    email,
                    max(title) AS title
                  FROM curated
                  WHERE email IS NOT NULL
                  AND title IS NOT NULL
                  GROUP BY email
                ),
                direct_people_raw AS (
                  SELECT
                    p.display_name,
                    p.primary_email AS email,
                    split_part(lower(p.primary_email), '@', 2) AS domain,
                    lower(split_part(p.primary_email, '@', 1)) AS localpart,
                    replace(
                      replace(lower(split_part(p.primary_email, '@', 1)), '.', '-'),
                      '_',
                      '-'
                    ) AS normalized_localpart,
                    COALESCE(e.interaction_count, 0)::int AS interaction_count,
                    COALESCE((e.metadata->>'calendar_interaction_count')::int, 0)::int AS calendar_interaction_count,
                    e.last_interaction_at
                  FROM relationship_substrate.person p
                  JOIN relationship_substrate.relationship_edge e
                    ON e.person_id = p.id
                  WHERE p.primary_email IS NOT NULL
                  AND split_part(lower(p.primary_email), '@', 2) <> ALL(%s)
                  AND COALESCE(e.interaction_count, 0) > 0
                ),
                direct_people AS (
                  SELECT *
                  FROM direct_people_raw
                  WHERE localpart <> ALL(%s)
                  AND normalized_localpart <> ALL(%s)
                  AND NOT EXISTS (
                    SELECT 1
                    FROM unnest(%s::text[]) AS prefix
                    WHERE normalized_localpart LIKE prefix || '%%'
                  )
                ),
                direct_domain_counts AS (
                  SELECT
                    domain,
                    count(DISTINCT email)::int AS direct_people_count,
                    sum(interaction_count)::int AS total_interaction_count,
                    sum(calendar_interaction_count)::int AS calendar_interaction_count,
                    max(last_interaction_at) AS last_interaction_at
                  FROM direct_people
                  WHERE domain IS NOT NULL
                  AND domain <> ''
                  GROUP BY domain
                ),
                ranked_people AS (
                  SELECT
                    dp.*,
                    c.title,
                    row_number() OVER (
                      PARTITION BY dp.domain
                      ORDER BY dp.interaction_count DESC, dp.last_interaction_at DESC NULLS LAST, dp.display_name
                    ) AS person_rank
                  FROM direct_people dp
                  LEFT JOIN curated_email_titles c
                    ON c.email = dp.email
                ),
                strongest_people AS (
                  SELECT
                    domain,
                    jsonb_agg(
                      jsonb_build_object(
                        'name', display_name,
                        'email', email,
                        'title', title,
                        'interaction_count', interaction_count,
                        'calendar_interaction_count', calendar_interaction_count,
                        'last_interaction_at', last_interaction_at
                      )
                      ORDER BY interaction_count DESC, last_interaction_at DESC NULLS LAST, display_name
                    ) FILTER (WHERE person_rank <= 5) AS strongest_people
                  FROM ranked_people
                  GROUP BY domain
                ),
                domains AS (
                  SELECT domain FROM curated_domain_counts
                  UNION
                  SELECT domain FROM direct_domain_counts
                )
                SELECT
                  COALESCE(dc.company_name, d.domain) AS company_name,
                  d.domain,
                  COALESCE(cdc.known_people_count, 0) AS known_people_count,
                  COALESCE(ddc.direct_people_count, 0) AS direct_people_count,
                  COALESCE(ddc.total_interaction_count, 0) AS total_interaction_count,
                  COALESCE(ddc.calendar_interaction_count, 0) AS calendar_interaction_count,
                  GREATEST(
                    COALESCE(ddc.total_interaction_count, 0) - COALESCE(ddc.calendar_interaction_count, 0),
                    0
                  ) AS email_interaction_count,
                  ddc.last_interaction_at,
                  COALESCE(dts.sample_titles, ARRAY[]::text[]) AS sample_titles,
                  COALESCE(sp.strongest_people, '[]'::jsonb) AS strongest_people
                FROM domains d
                LEFT JOIN domain_companies dc
                  ON dc.domain = d.domain
                LEFT JOIN curated_domain_counts cdc
                  ON cdc.domain = d.domain
                LEFT JOIN domain_title_samples dts
                  ON dts.domain = d.domain
                LEFT JOIN direct_domain_counts ddc
                  ON ddc.domain = d.domain
                LEFT JOIN strongest_people sp
                  ON sp.domain = d.domain
                {missing_filter}
                ORDER BY
                  COALESCE(ddc.total_interaction_count, 0) DESC,
                  COALESCE(ddc.direct_people_count, 0) DESC,
                  COALESCE(cdc.known_people_count, 0) DESC,
                  COALESCE(dc.company_name, d.domain)
                LIMIT %s
                """,
                params,
            )
            rows = cur.fetchall()
    worklist: list[dict[str, Any]] = []
    for row in rows:
        company_name = row[0]
        enrichment = enrichments.get(company_name.lower())
        has_enrichment = enrichment is not None
        if missing_enrichment_only and has_enrichment:
            continue
        known_people_count = int(row[2] or 0)
        direct_people_count = int(row[3] or 0)
        total_interaction_count = int(row[4] or 0)
        calendar_interaction_count = int(row[5] or 0)
        email_interaction_count = int(row[6] or 0)
        last_interaction_at = row[7].astimezone(UTC).isoformat() if row[7] else None
        worklist.append(
            {
                "company_name": company_name,
                "domain": row[1],
                "known_people_count": known_people_count,
                "direct_people_count": direct_people_count,
                "email_interaction_count": email_interaction_count,
                "calendar_interaction_count": calendar_interaction_count,
                "total_interaction_count": total_interaction_count,
                "last_interaction_at": last_interaction_at,
                "freshness": relationship_freshness(last_interaction_at, as_of=as_of),
                "has_enrichment": has_enrichment,
                "organization_enrichment": enrichment,
                "strongest_people": row[9] or [],
                "sample_titles": list(dict.fromkeys(row[8] or [])),
                "enrichment_reasons": _enrichment_reasons(
                    has_enrichment=has_enrichment,
                    direct_people_count=direct_people_count,
                    known_people_count=known_people_count,
                    total_interaction_count=total_interaction_count,
                    calendar_interaction_count=calendar_interaction_count,
                ),
                "research_prompt": (
                    "Find actual organization size, company type, consultant/team count, current "
                    f"positioning, and source URLs for {company_name} ({row[1]}). Prioritize "
                    "sources that support fields missing from organization_enrichment."
                ),
            }
        )
    return worklist


def import_organization_enrichments(
    database_url: str,
    records: list[dict[str, Any]],
) -> dict[str, int | str]:
    report: dict[str, int | str] = {
        "source": "organization_enrichment_import",
        "seen": len(records),
        "imported": 0,
        "skipped": 0,
    }
    for record in records:
        company_name = _clean_text(record.get("company_name") or record.get("company"))
        source_name = _clean_text(record.get("source_name"))
        provenance_status = _clean_text(record.get("provenance_status")) or "external_research"
        if not company_name or not source_name:
            report["skipped"] += 1
            continue
        upsert_organization_enrichment(
            database_url,
            company_name=company_name,
            domain=record.get("domain"),
            aliases=record.get("aliases"),
            company_type=record.get("company_type"),
            employee_count_min=record.get("employee_count_min"),
            employee_count_max=record.get("employee_count_max"),
            employee_count_label=record.get("employee_count_label"),
            consultant_count_estimate=record.get("consultant_count_estimate"),
            source_name=source_name,
            source_url=record.get("source_url"),
            provenance_status=provenance_status,
        )
        report["imported"] += 1
    return report
