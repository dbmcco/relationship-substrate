from __future__ import annotations

import json
import os
import urllib.error
import urllib.request
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import psycopg

from relationship_substrate.organizations import (
    history_backed_organization_worklist,
    import_organization_enrichments,
)
from relationship_substrate.research import upsert_research_snapshot


DEFAULT_PERPLEXITY_ENDPOINT = "https://api.perplexity.ai/chat/completions"
DEFAULT_PERPLEXITY_MODEL = "sonar-pro"
DEFAULT_ORGANIZATION_RESEARCH_TTL_HOURS = 24 * 30
DEFAULT_ORGANIZATION_FAILURE_RETRY_HOURS = 24

ResearchCompany = Callable[[dict[str, Any]], dict[str, Any]]


def _clean_text(value: object) -> str:
    return str(value or "").strip()


def _write_json(path: Path, payload: object) -> str:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True, default=str) + "\n")
    return str(path)


def _coerce_int(value: object) -> int | None:
    if value is None or value == "":
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _coerce_positive_int(value: object, *, default: int) -> int:
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        return default
    if parsed <= 0:
        return default
    return parsed


def _retry_after(ttl_hours: int) -> str:
    return (datetime.now(UTC) + timedelta(hours=ttl_hours)).isoformat()


def _organization_lookup_keys(company: dict[str, Any]) -> set[str]:
    keys = {
        _clean_text(company.get("company_name")).lower(),
        _clean_text(company.get("domain")).lower(),
    }
    enrichment = company.get("organization_enrichment")
    if isinstance(enrichment, dict):
        keys.add(_clean_text(enrichment.get("domain")).lower())
        for alias in enrichment.get("aliases") or []:
            keys.add(_clean_text(alias).lower())
    return {key for key in keys if key}


def _recent_research_keys(
    database_url: str,
    *,
    subject_type: str,
    keys: set[str],
    ttl_hours: int,
) -> set[str]:
    if not keys:
        return set()
    cutoff = datetime.now(UTC) - timedelta(hours=ttl_hours)
    with psycopg.connect(database_url) as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT DISTINCT lower(subject)
                FROM relationship_substrate.research_snapshot
                WHERE subject_type = %s
                AND retrieved_at >= %s
                AND (
                  lower(subject) = ANY(%s)
                  OR lower(metadata->>'domain') = ANY(%s)
                  OR lower(metadata->>'company_name') = ANY(%s)
                )
                """,
                (subject_type, cutoff, sorted(keys), sorted(keys), sorted(keys)),
            )
            rows = cur.fetchall()
    return {row[0] for row in rows if row[0]}


def _active_failure_keys(
    database_url: str,
    *,
    subject_type: str,
    keys: set[str],
) -> set[str]:
    if not keys:
        return set()
    with psycopg.connect(database_url) as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT DISTINCT lower(subject)
                FROM relationship_substrate.research_snapshot
                WHERE subject_type = %s
                AND (
                  lower(subject) = ANY(%s)
                  OR lower(metadata->>'domain') = ANY(%s)
                  OR lower(metadata->>'company_name') = ANY(%s)
                )
                AND nullif(metadata->>'retry_after', '')::timestamptz > now()
                """,
                (subject_type, sorted(keys), sorted(keys), sorted(keys)),
            )
            rows = cur.fetchall()
    return {row[0] for row in rows if row[0]}


def _should_skip_recent_research(
    database_url: str,
    *,
    company: dict[str, Any],
    subject_type: str,
    ttl_hours: int,
) -> bool:
    keys = _organization_lookup_keys(company)
    return bool(_recent_research_keys(database_url, subject_type=subject_type, keys=keys, ttl_hours=ttl_hours))


def _should_skip_active_failure(
    database_url: str,
    *,
    company: dict[str, Any],
    subject_type: str,
) -> bool:
    keys = _organization_lookup_keys(company)
    return bool(_active_failure_keys(database_url, subject_type=subject_type, keys=keys))


def _classify_research_failure(exc: Exception) -> str:
    message = str(exc).lower()
    if "did not contain a json object" in message or "requires at least one source url" in message:
        return "invalid_response"
    if "429" in message or "rate limit" in message:
        return "rate_limited"
    if "perplexity" in message and any(code in message for code in (" 500", " 502", " 503", " 504")):
        return "transient_provider_error"
    if "unique constraint" in message:
        return "persistence_conflict"
    return "research_failure"


def _alternate_research_company(company: dict[str, Any], *, previous_error: str) -> dict[str, Any]:
    return {
        **company,
        "research_plan": "domain_focused_retry",
        "previous_research_error": previous_error,
    }


def _record_research_failure(
    database_url: str,
    *,
    company: dict[str, Any],
    subject_type: str,
    exc: Exception,
    failure_kind: str,
    retry_ttl_hours: int,
    attempts: int,
) -> dict[str, Any]:
    subject = _clean_text(company.get("domain")) or _clean_text(company.get("company_name")) or "unknown_organization"
    return upsert_research_snapshot(
        database_url,
        subject_type=subject_type,
        subject=subject,
        summary=str(exc)[:1000] or failure_kind,
        confidence="failure",
        sources=[],
        metadata={
            "company_name": company.get("company_name"),
            "domain": company.get("domain"),
            "failure_kind": failure_kind,
            "retry_after": _retry_after(retry_ttl_hours),
            "attempts": attempts,
        },
    )


def parse_research_json(content: str) -> dict[str, Any]:
    text = content.strip()
    if text.startswith("```"):
        lines = text.splitlines()
        if lines and lines[0].startswith("```"):
            lines = lines[1:]
        if lines and lines[-1].startswith("```"):
            lines = lines[:-1]
        text = "\n".join(lines).strip()
    decoder = json.JSONDecoder()
    for index, char in enumerate(text):
        if char != "{":
            continue
        try:
            value, _end = decoder.raw_decode(text[index:])
        except json.JSONDecodeError:
            continue
        if isinstance(value, dict):
            return value
    raise ValueError("research response did not contain a JSON object")


def _source_url(source: dict[str, Any]) -> str | None:
    url = _clean_text(source.get("url"))
    return url or None


def _normalize_sources(payload_sources: object, citations: list[str]) -> list[dict[str, Any]]:
    sources: list[dict[str, Any]] = []
    if isinstance(payload_sources, list):
        for index, source in enumerate(payload_sources, start=1):
            if isinstance(source, str):
                url = _clean_text(source)
                if url:
                    sources.append({"id": f"source:{index}", "url": url})
                continue
            if not isinstance(source, dict):
                continue
            url = _source_url(source)
            if not url:
                continue
            source_id = _clean_text(source.get("id")) or f"source:{index}"
            sources.append({**source, "id": source_id, "url": url})
    if sources:
        return sources
    for index, citation in enumerate(citations, start=1):
        if isinstance(citation, dict):
            url = _source_url(citation)
            source = {**citation, "id": _clean_text(citation.get("id")) or f"citation:{index}"}
        else:
            url = _clean_text(citation)
            source = {"id": f"citation:{index}", "url": url}
        if not url or any(existing.get("url") == url for existing in sources):
            continue
        sources.append({**source, "url": url})
    return sources


def organization_enrichment_record_from_research(
    company: dict[str, Any],
    research: dict[str, Any],
) -> dict[str, Any]:
    payload = parse_research_json(_clean_text(research.get("content")))
    sources = _normalize_sources(payload.get("sources"), list(research.get("citations") or []))
    if not sources:
        raise ValueError("organization research requires at least one source URL")
    company_name = _clean_text(payload.get("company_name")) or _clean_text(company.get("company_name"))
    domain = _clean_text(payload.get("domain")) or _clean_text(company.get("domain"))
    if not company_name:
        raise ValueError("organization research requires company_name")
    return {
        "company_name": company_name,
        "domain": domain or None,
        "aliases": payload.get("aliases") if isinstance(payload.get("aliases"), list) else [],
        "company_type": _clean_text(payload.get("company_type")) or None,
        "employee_count_min": _coerce_int(payload.get("employee_count_min")),
        "employee_count_max": _coerce_int(payload.get("employee_count_max")),
        "employee_count_label": _clean_text(payload.get("employee_count_label")) or None,
        "consultant_count_estimate": _coerce_int(payload.get("consultant_count_estimate")),
        "source_name": "perplexity_research",
        "source_url": sources[0]["url"],
        "provenance_status": "external_research",
        "summary": _clean_text(payload.get("summary")) or _clean_text(research.get("content"))[:1000],
        "confidence": _clean_text(payload.get("confidence")) or "unknown",
        "sources": sources,
        "model": _clean_text(research.get("model")) or None,
        "raw_payload": payload,
    }


def _organization_research_prompt(company: dict[str, Any]) -> str:
    strongest_people = company.get("strongest_people") or []
    people_hint = [
        {
            "name": person.get("name"),
            "title": person.get("title"),
        }
        for person in strongest_people[:5]
    ]
    plan = _clean_text(company.get("research_plan"))
    previous_error = _clean_text(company.get("previous_research_error"))
    retry_guidance = ""
    if plan == "domain_focused_retry":
        retry_guidance = (
            "\nRetry plan: the previous response was unusable. Focus on the supplied domain, "
            "official website pages, company profile pages, and source URLs. Return valid JSON only. "
            "If a field cannot be sourced, use null rather than prose outside JSON.\n"
        )
        if previous_error:
            retry_guidance += f"Previous error: {previous_error[:300]}\n"
    return (
        "Research this organization for a personal relationship intelligence system.\n"
        "Return only a JSON object with these keys: company_name, domain, aliases, "
        "company_type, employee_count_min, employee_count_max, employee_count_label, "
        "consultant_count_estimate, summary, confidence, sources.\n"
        "Use null when a sourced value is unavailable. Include source URLs in sources.\n"
        "Do not infer company size or consultant count without cited evidence.\n\n"
        f"{retry_guidance}"
        f"Organization: {company.get('company_name')}\n"
        f"Domain: {company.get('domain')}\n"
        f"Known interaction counts: email={company.get('email_interaction_count')}, "
        f"calendar={company.get('calendar_interaction_count')}\n"
        f"Sample titles: {company.get('sample_titles') or []}\n"
        f"Known people hints: {people_hint}\n"
    )


def _organization_news_prompt(company: dict[str, Any]) -> str:
    strongest_people = company.get("strongest_people") or []
    people_hint = [
        {
            "name": person.get("name"),
            "title": person.get("title"),
        }
        for person in strongest_people[:5]
    ]
    return (
        "Research recent public news and meaningful current events for this organization "
        "for a personal relationship intelligence system.\n"
        "Return only a JSON object with these keys: summary, confidence, sources.\n"
        "Use null when a sourced value is unavailable. Include source URLs in sources.\n"
        "Do not update or infer static enrichment fields like employee count or company type.\n\n"
        f"Organization: {company.get('company_name')}\n"
        f"Domain: {company.get('domain')}\n"
        f"Known interaction counts: email={company.get('email_interaction_count')}, "
        f"calendar={company.get('calendar_interaction_count')}\n"
        f"Sample titles: {company.get('sample_titles') or []}\n"
        f"Known people hints: {people_hint}\n"
    )


def perplexity_research_organization(
    company: dict[str, Any],
    *,
    api_key: str | None = None,
    model: str | None = None,
    endpoint: str | None = None,
    timeout_seconds: int = 90,
) -> dict[str, Any]:
    api_key = api_key or os.environ.get("PERPLEXITY_API_KEY")
    if not api_key:
        raise RuntimeError("PERPLEXITY_API_KEY is required for organization research")
    model = model or os.environ.get("RELATIONSHIP_SUBSTRATE_PERPLEXITY_MODEL", DEFAULT_PERPLEXITY_MODEL)
    endpoint = endpoint or os.environ.get("RELATIONSHIP_SUBSTRATE_PERPLEXITY_ENDPOINT", DEFAULT_PERPLEXITY_ENDPOINT)
    payload = json.dumps(
        {
            "model": model,
            "messages": [
                {
                    "role": "system",
                    "content": (
                        "You are a source-grounded organization research analyst. "
                        "Return JSON only. Preserve uncertainty as nulls."
                    ),
                },
                {"role": "user", "content": _organization_research_prompt(company)},
            ],
            "temperature": 0.1,
        }
    ).encode("utf-8")
    request = urllib.request.Request(
        endpoint,
        data=payload,
        headers={
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout_seconds) as response:
            raw = response.read()
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"Perplexity research request failed: {exc.code} {detail}") from exc
    except urllib.error.URLError as exc:
        raise RuntimeError(f"Perplexity research request failed: {exc}") from exc
    data = json.loads(raw)
    choice = (data.get("choices") or [{}])[0]
    message = choice.get("message") or {}
    return {
        "content": message.get("content") or "",
        "citations": data.get("citations") or data.get("search_results") or [],
        "model": data.get("model") or model,
        "raw_response": data,
    }


def perplexity_research_organization_news(
    company: dict[str, Any],
    *,
    api_key: str | None = None,
    model: str | None = None,
    endpoint: str | None = None,
    timeout_seconds: int = 90,
) -> dict[str, Any]:
    api_key = api_key or os.environ.get("PERPLEXITY_API_KEY")
    if not api_key:
        raise RuntimeError("PERPLEXITY_API_KEY is required for organization news research")
    model = model or os.environ.get("RELATIONSHIP_SUBSTRATE_PERPLEXITY_NEWS_MODEL", DEFAULT_PERPLEXITY_MODEL)
    endpoint = endpoint or os.environ.get("RELATIONSHIP_SUBSTRATE_PERPLEXITY_ENDPOINT", DEFAULT_PERPLEXITY_ENDPOINT)
    payload = json.dumps(
        {
            "model": model,
            "messages": [
                {
                    "role": "system",
                    "content": (
                        "You are a source-grounded current-news research analyst. "
                        "Return JSON only. Preserve uncertainty as nulls."
                    ),
                },
                {"role": "user", "content": _organization_news_prompt(company)},
            ],
            "temperature": 0.1,
        }
    ).encode("utf-8")
    request = urllib.request.Request(
        endpoint,
        data=payload,
        headers={
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout_seconds) as response:
            raw = response.read()
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"Perplexity organization news request failed: {exc.code} {detail}") from exc
    except urllib.error.URLError as exc:
        raise RuntimeError(f"Perplexity organization news request failed: {exc}") from exc
    data = json.loads(raw)
    choice = (data.get("choices") or [{}])[0]
    message = choice.get("message") or {}
    return {
        "content": message.get("content") or "",
        "citations": data.get("citations") or data.get("search_results") or [],
        "model": data.get("model") or model,
        "raw_response": data,
    }


def run_organization_enrichment_research(
    database_url: str,
    *,
    output_dir: Path,
    limit: int = 5,
    apply: bool = False,
    research_company: ResearchCompany | None = None,
    skipped_domains: set[str] | None = None,
    skipped_system_localparts: set[str] | None = None,
    skipped_system_prefixes: set[str] | None = None,
    recent_research_ttl_hours: int | None = None,
    failure_retry_ttl_hours: int | None = None,
) -> dict[str, Any]:
    research_company = research_company or perplexity_research_organization
    recent_research_ttl_hours = recent_research_ttl_hours or _coerce_positive_int(
        os.environ.get("RELATIONSHIP_SUBSTRATE_ORGANIZATION_RESEARCH_TTL_HOURS"),
        default=DEFAULT_ORGANIZATION_RESEARCH_TTL_HOURS,
    )
    failure_retry_ttl_hours = failure_retry_ttl_hours or _coerce_positive_int(
        os.environ.get("RELATIONSHIP_SUBSTRATE_ORGANIZATION_FAILURE_RETRY_HOURS"),
        default=DEFAULT_ORGANIZATION_FAILURE_RETRY_HOURS,
    )
    run_started_at = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    run_dir = output_dir / run_started_at
    companies = history_backed_organization_worklist(
        database_url,
        limit=limit,
        skipped_domains=skipped_domains,
        skipped_system_localparts=skipped_system_localparts,
        skipped_system_prefixes=skipped_system_prefixes,
        missing_enrichment_only=True,
    )
    records: list[dict[str, Any]] = []
    snapshots: list[dict[str, Any]] = []
    failures: list[dict[str, Any]] = []
    raw_results: list[dict[str, Any]] = []
    skipped: list[dict[str, Any]] = []
    for company in companies:
        if _should_skip_active_failure(
            database_url,
            company=company,
            subject_type="organization_research_failure",
        ):
            skipped.append(
                {
                    "company_name": company.get("company_name"),
                    "domain": company.get("domain"),
                    "reason": "active_organization_research_failure_retry_after",
                }
            )
            continue
        if _should_skip_recent_research(
            database_url,
            company=company,
            subject_type="organization",
            ttl_hours=recent_research_ttl_hours,
        ):
            skipped.append(
                {
                    "company_name": company.get("company_name"),
                    "domain": company.get("domain"),
                    "reason": "recent_organization_research_snapshot",
                }
            )
            continue
        attempts: list[dict[str, Any]] = [company]
        attempt_count = 0
        while attempts:
            current_company = attempts.pop(0)
            attempt_count += 1
            try:
                research = research_company(current_company)
                raw_results.append({"company": current_company, "research": research, "attempt": attempt_count})
                record = organization_enrichment_record_from_research(current_company, research)
                records.append(record)
                if apply:
                    import_organization_enrichments(database_url, [record])
                    snapshot = upsert_research_snapshot(
                        database_url,
                        subject_type="organization",
                        subject=record.get("domain") or record["company_name"],
                        summary=record["summary"],
                        confidence=record["confidence"],
                        sources=record["sources"],
                        metadata={
                            "company_name": record["company_name"],
                            "domain": record.get("domain"),
                            "model": record.get("model"),
                            "enrichment": {
                                key: record.get(key)
                                for key in (
                                    "company_type",
                                    "employee_count_min",
                                    "employee_count_max",
                                    "employee_count_label",
                                    "consultant_count_estimate",
                                )
                            },
                        },
                    )
                    snapshots.append(snapshot)
                break
            except Exception as exc:  # noqa: BLE001 - failures are reported per work item.
                failure_kind = _classify_research_failure(exc)
                if failure_kind == "invalid_response" and attempt_count == 1:
                    attempts.append(_alternate_research_company(company, previous_error=str(exc)))
                    continue
                failure = {
                    "company_name": company.get("company_name"),
                    "domain": company.get("domain"),
                    "error": str(exc),
                    "failure_kind": failure_kind,
                    "attempts": attempt_count,
                }
                if apply:
                    failure["snapshot"] = _record_research_failure(
                        database_url,
                        company=company,
                        subject_type="organization_research_failure",
                        exc=exc,
                        failure_kind=failure_kind,
                        retry_ttl_hours=failure_retry_ttl_hours,
                        attempts=attempt_count,
                    )
                failures.append(failure)
                break
    artifacts = {
        "worklist": _write_json(run_dir / "organization_worklist.json", companies),
        "raw_results": _write_json(run_dir / "raw_results.json", raw_results),
        "records": _write_json(run_dir / "organization_enrichment_records.json", records),
        "skipped": _write_json(run_dir / "skipped.json", skipped),
        "failures": _write_json(run_dir / "failures.json", failures),
    }
    report = {
        "ok": not failures,
        "run_started_at": run_started_at,
        "apply": apply,
        "worklist_count": len(companies),
        "researched": len(records),
        "applied": len(snapshots) if apply else 0,
        "skipped": skipped,
        "skipped_count": len(skipped),
        "failed": len(failures),
        "records": records,
        "snapshots": snapshots,
        "failures": failures,
        "artifacts": artifacts,
        "output_dir": str(run_dir),
    }
    report["artifact"] = _write_json(run_dir / "organization_research_report.json", report)
    return report


def run_organization_news_research(
    database_url: str,
    *,
    output_dir: Path,
    limit: int = 5,
    apply: bool = False,
    research_company_news: ResearchCompany | None = None,
    skipped_domains: set[str] | None = None,
    skipped_system_localparts: set[str] | None = None,
    skipped_system_prefixes: set[str] | None = None,
    recent_research_ttl_hours: int | None = None,
) -> dict[str, Any]:
    research_company_news = research_company_news or perplexity_research_organization_news
    recent_research_ttl_hours = recent_research_ttl_hours or _coerce_positive_int(
        os.environ.get("RELATIONSHIP_SUBSTRATE_ORGANIZATION_NEWS_TTL_HOURS"),
        default=24,
    )
    run_started_at = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    run_dir = output_dir / run_started_at
    companies = history_backed_organization_worklist(
        database_url,
        limit=limit,
        skipped_domains=skipped_domains,
        skipped_system_localparts=skipped_system_localparts,
        skipped_system_prefixes=skipped_system_prefixes,
        missing_enrichment_only=False,
    )
    snapshots: list[dict[str, Any]] = []
    failures: list[dict[str, Any]] = []
    raw_results: list[dict[str, Any]] = []
    skipped: list[dict[str, Any]] = []
    for company in companies:
        if _should_skip_recent_research(
            database_url,
            company=company,
            subject_type="organization_news",
            ttl_hours=recent_research_ttl_hours,
        ):
            skipped.append(
                {
                    "company_name": company.get("company_name"),
                    "domain": company.get("domain"),
                    "reason": "recent_organization_news_snapshot",
                }
            )
            continue
        try:
            research = research_company_news(company)
            raw_results.append({"company": company, "research": research})
            payload = parse_research_json(_clean_text(research.get("content")))
            sources = _normalize_sources(payload.get("sources"), list(research.get("citations") or []))
            if not sources:
                raise ValueError("organization news research requires at least one source URL")
            summary = _clean_text(payload.get("summary")) or _clean_text(research.get("content"))[:1000]
            if not summary:
                raise ValueError("organization news research requires summary")
            if apply:
                snapshot = upsert_research_snapshot(
                    database_url,
                    subject_type="organization_news",
                    subject=company.get("domain") or company["company_name"],
                    summary=summary,
                    confidence=_clean_text(payload.get("confidence")) or "unknown",
                    sources=sources,
                    metadata={
                        "company_name": company.get("company_name"),
                        "domain": company.get("domain"),
                        "model": _clean_text(research.get("model")) or None,
                        "refresh_kind": "current_news",
                    },
                )
                snapshots.append(snapshot)
        except Exception as exc:  # noqa: BLE001 - failures are reported per work item.
            failures.append(
                {
                    "company_name": company.get("company_name"),
                    "domain": company.get("domain"),
                    "error": str(exc),
                }
            )
    artifacts = {
        "worklist": _write_json(run_dir / "organization_news_worklist.json", companies),
        "raw_results": _write_json(run_dir / "raw_results.json", raw_results),
        "snapshots": _write_json(run_dir / "research_snapshots.json", snapshots),
        "skipped": _write_json(run_dir / "skipped.json", skipped),
        "failures": _write_json(run_dir / "failures.json", failures),
    }
    report = {
        "ok": not failures,
        "run_started_at": run_started_at,
        "apply": apply,
        "worklist_count": len(companies),
        "researched": len(raw_results),
        "applied": len(snapshots) if apply else 0,
        "skipped": skipped,
        "skipped_count": len(skipped),
        "failed": len(failures),
        "snapshots": snapshots,
        "failures": failures,
        "artifacts": artifacts,
        "output_dir": str(run_dir),
    }
    report["artifact"] = _write_json(run_dir / "organization_news_report.json", report)
    return report
