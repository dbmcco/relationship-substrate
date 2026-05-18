from __future__ import annotations

import json
from pathlib import Path
from uuid import uuid4

import psycopg
from psycopg.types.json import Jsonb

from relationship_substrate.db import run_migrations
from relationship_substrate.research_workers import (
    organization_enrichment_record_from_research,
    parse_research_json,
    run_organization_enrichment_research,
    run_organization_news_research,
)
from relationship_substrate.research import upsert_research_snapshot


def _relationship_person(database_url: str, *, email: str, interaction_count: int = 7) -> None:
    with psycopg.connect(database_url) as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO relationship_substrate.person (
                  display_name, primary_email, source_posture, provenance_status
                )
                VALUES ('Research Target', %s, 'test', 'test')
                RETURNING id
                """,
                (email,),
            )
            person_id = cur.fetchone()[0]
            cur.execute(
                """
                INSERT INTO relationship_substrate.relationship_edge (
                  person_id, interaction_count, metadata
                )
                VALUES (%s, %s, %s)
                """,
                (person_id, interaction_count, Jsonb({"email_message_count": interaction_count})),
            )
        conn.commit()


def _existing_worklist_domains(database_url: str) -> set[str]:
    with psycopg.connect(database_url) as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT DISTINCT split_part(lower(primary_email), '@', 2)
                FROM relationship_substrate.person
                WHERE primary_email IS NOT NULL
                UNION
                SELECT DISTINCT split_part(lower(source_payload->>'email'), '@', 2)
                FROM relationship_substrate.source_event
                WHERE nullif(source_payload->>'email', '') IS NOT NULL
                """
            )
            return {row[0] for row in cur.fetchall() if row[0]}


def test_parse_research_json_extracts_fenced_object():
    parsed = parse_research_json(
        """
        Here is the result:
        ```json
        {"company_type": "medical communications consultancy", "employee_count_min": 10}
        ```
        """
    )

    assert parsed == {
        "company_type": "medical communications consultancy",
        "employee_count_min": 10,
    }


def test_organization_enrichment_record_requires_sources():
    company = {"company_name": "Small Medcoms", "domain": "small-medcoms.example"}
    research = {
        "content": json.dumps(
            {
                "company_type": "medical communications consultancy",
                "employee_count_min": 10,
                "employee_count_max": 20,
                "consultant_count_estimate": 12,
                "summary": "Small cited firm.",
                "confidence": "medium",
            }
        ),
        "citations": ["https://example.com/about"],
        "model": "test-model",
    }

    record = organization_enrichment_record_from_research(company, research)

    assert record["company_name"] == "Small Medcoms"
    assert record["domain"] == "small-medcoms.example"
    assert record["company_type"] == "medical communications consultancy"
    assert record["employee_count_min"] == 10
    assert record["employee_count_max"] == 20
    assert record["consultant_count_estimate"] == 12
    assert record["source_name"] == "perplexity_research"
    assert record["source_url"] == "https://example.com/about"
    assert record["sources"] == [{"id": "citation:1", "url": "https://example.com/about"}]


def test_organization_enrichment_record_accepts_citation_objects():
    company = {"company_name": "Small Medcoms", "domain": "small-medcoms.example"}
    research = {
        "content": json.dumps({"summary": "Small cited firm.", "confidence": "medium"}),
        "citations": [{"url": "https://example.com/about", "title": "About"}],
        "model": "test-model",
    }

    record = organization_enrichment_record_from_research(company, research)

    assert record["source_url"] == "https://example.com/about"
    assert record["sources"] == [{"id": "citation:1", "title": "About", "url": "https://example.com/about"}]


def test_organization_enrichment_record_prefers_payload_source_strings_over_citations():
    company = {"company_name": "Small Medcoms", "domain": "small-medcoms.example"}
    research = {
        "content": json.dumps(
            {
                "company_type": "medical communications consultancy",
                "summary": "Small cited firm.",
                "confidence": "medium",
                "sources": ["https://example.com/team"],
            }
        ),
        "citations": ["https://unrelated.example/search-result"],
        "model": "test-model",
    }

    record = organization_enrichment_record_from_research(company, research)

    assert record["source_url"] == "https://example.com/team"
    assert record["sources"] == [{"id": "source:1", "url": "https://example.com/team"}]


def test_run_organization_enrichment_research_applies_valid_source_backed_records(database_url, tmp_path):
    run_migrations(database_url)
    run_id = uuid4().hex
    domain = f"research-worker-{run_id}.example"
    _relationship_person(database_url, email=f"person@{domain}")
    calls: list[dict] = []

    def fake_researcher(company: dict) -> dict:
        calls.append(company)
        return {
            "content": json.dumps(
                {
                    "company_type": "business consulting firm",
                    "employee_count_min": 10,
                    "employee_count_max": 15,
                    "employee_count_label": "10-15 employees",
                    "consultant_count_estimate": 11,
                    "summary": "Source-backed small consulting firm.",
                    "confidence": "medium",
                    "sources": [{"id": "source:1", "url": "https://example.com/team"}],
                }
            ),
            "citations": [],
            "model": "test-model",
        }

    report = run_organization_enrichment_research(
        database_url,
        output_dir=tmp_path / "research",
        limit=100000,
        apply=True,
        research_company=fake_researcher,
        skipped_domains=set(),
        skipped_system_localparts=set(),
        skipped_system_prefixes=set(),
    )

    assert report["researched"] >= 1
    assert any(call["domain"] == domain for call in calls)
    assert Path(report["artifact"]).exists()
    with psycopg.connect(database_url) as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT metadata->'enrichment'->>'company_type'
                FROM relationship_substrate.organization
                WHERE domain = %s
                """,
                (domain,),
            )
            assert cur.fetchone() == ("business consulting firm",)
            cur.execute(
                """
                SELECT count(*)::int
                FROM relationship_substrate.research_snapshot
                WHERE subject = %s
                AND subject_type = 'organization'
                """,
                (domain,),
            )
            assert cur.fetchone()[0] >= 1


def test_run_organization_enrichment_research_skips_recent_snapshot_before_api_call(database_url, tmp_path):
    run_migrations(database_url)
    run_id = uuid4().hex
    domain = f"recent-research-{run_id}.example"
    _relationship_person(database_url, email=f"person@{domain}", interaction_count=1000)
    upsert_research_snapshot(
        database_url,
        subject_type="organization",
        subject=domain,
        summary="Recent source-backed research already exists.",
        confidence="medium",
        sources=[{"id": "source:1", "url": "https://example.com/recent"}],
        metadata={"domain": domain, "company_name": domain, "model": "sonar-pro"},
    )
    calls: list[dict] = []

    def fake_researcher(company: dict) -> dict:
        calls.append(company)
        return {
            "content": json.dumps(
                {
                    "summary": "This should not be called for a recent snapshot.",
                    "confidence": "low",
                    "sources": [{"id": "source:1", "url": "https://example.com/duplicate"}],
                }
            ),
            "citations": [],
            "model": "test-model",
        }

    report = run_organization_enrichment_research(
        database_url,
        output_dir=tmp_path / "research",
        limit=100000,
        apply=True,
        research_company=fake_researcher,
        skipped_domains=set(),
        skipped_system_localparts=set(),
        skipped_system_prefixes=set(),
    )

    assert all(call["domain"] != domain for call in calls)
    assert any(skipped["domain"] == domain for skipped in report["skipped"])


def test_run_organization_enrichment_research_retries_bad_response_with_alternate_plan(database_url, tmp_path):
    run_migrations(database_url)
    existing_domains = _existing_worklist_domains(database_url)
    run_id = uuid4().hex
    domain = f"alternate-plan-{run_id}.example"
    _relationship_person(database_url, email=f"person@{domain}", interaction_count=1000)
    calls: list[dict] = []

    def fake_researcher(company: dict) -> dict:
        calls.append(company)
        if len(calls) == 1:
            return {"content": "No structured answer available.", "citations": [], "model": "test-model"}
        return {
            "content": json.dumps(
                {
                    "company_name": "Alternate Plan Co",
                    "domain": domain,
                    "company_type": "source-backed consultancy",
                    "summary": "Alternate plan found source-backed organization context.",
                    "confidence": "medium",
                    "sources": [{"id": "source:1", "url": "https://example.com/alternate"}],
                }
            ),
            "citations": [],
            "model": "test-model",
        }

    report = run_organization_enrichment_research(
        database_url,
        output_dir=tmp_path / "research",
        limit=100000,
        apply=True,
        research_company=fake_researcher,
        skipped_domains=existing_domains,
        skipped_system_localparts=set(),
        skipped_system_prefixes=set(),
    )

    current_calls = [call for call in calls if call["domain"] == domain]
    assert len(current_calls) == 2
    assert current_calls[1]["research_plan"] == "domain_focused_retry"
    assert report["failed"] == 0
    assert any(record["domain"] == domain for record in report["records"])


def test_run_organization_enrichment_research_records_retry_after_for_exhausted_failures(
    database_url,
    tmp_path,
):
    run_migrations(database_url)
    existing_domains = _existing_worklist_domains(database_url)
    run_id = uuid4().hex
    domain = f"retry-after-{run_id}.example"
    _relationship_person(database_url, email=f"person@{domain}", interaction_count=1000)
    calls: list[dict] = []

    def bad_researcher(company: dict) -> dict:
        calls.append(company)
        return {"content": "No structured answer available.", "citations": [], "model": "test-model"}

    first_report = run_organization_enrichment_research(
        database_url,
        output_dir=tmp_path / "first",
        limit=100000,
        apply=True,
        research_company=bad_researcher,
        skipped_domains=existing_domains,
        skipped_system_localparts=set(),
        skipped_system_prefixes=set(),
    )

    assert len([call for call in calls if call["domain"] == domain]) == 2
    assert first_report["failed"] >= 1
    with psycopg.connect(database_url) as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT metadata->>'failure_kind', metadata->>'retry_after'
                FROM relationship_substrate.research_snapshot
                WHERE subject_type = 'organization_research_failure'
                AND subject = %s
                ORDER BY retrieved_at DESC
                LIMIT 1
                """,
                (domain,),
            )
            failure_kind, retry_after = cur.fetchone()
    assert failure_kind == "invalid_response"
    assert retry_after

    second_report = run_organization_enrichment_research(
        database_url,
        output_dir=tmp_path / "second",
        limit=100000,
        apply=True,
        research_company=bad_researcher,
        skipped_domains=existing_domains,
        skipped_system_localparts=set(),
        skipped_system_prefixes=set(),
    )

    assert len([call for call in calls if call["domain"] == domain]) == 2
    assert any(skipped["domain"] == domain for skipped in second_report["skipped"])


def test_run_organization_enrichment_research_cli_passes_bounds(database_url, monkeypatch, tmp_path, capsys):
    from relationship_substrate import cli

    captured: dict[str, object] = {}

    def fake_runner(database_url: str, **kwargs: object) -> dict[str, object]:
        captured["database_url"] = database_url
        captured.update(kwargs)
        return {"ok": True, "researched": 1}

    monkeypatch.setattr(cli, "run_organization_enrichment_research", fake_runner)
    monkeypatch.setattr(
        "sys.argv",
        [
            "relationship-substrate",
            "--database-url",
            database_url,
            "run-organization-enrichment-research",
            "--output-dir",
            str(tmp_path / "org-research"),
            "--limit",
            "3",
            "--apply",
        ],
    )

    assert cli.main() == 0
    assert captured["database_url"] == database_url
    assert captured["output_dir"] == tmp_path / "org-research"
    assert captured["limit"] == 3
    assert captured["apply"] is True
    assert '"researched": 1' in capsys.readouterr().out


def test_run_organization_news_research_stores_snapshots_without_enrichment(database_url, tmp_path):
    run_migrations(database_url)
    run_id = uuid4().hex
    domain = f"news-worker-{run_id}.example"
    _relationship_person(database_url, email=f"person@{domain}")
    calls: list[dict] = []

    def fake_researcher(company: dict) -> dict:
        calls.append(company)
        return {
            "content": json.dumps(
                {
                    "summary": "Recent source-backed news summary for this organization.",
                    "confidence": "medium",
                    "sources": [{"id": "source:1", "url": "https://example.com/news"}],
                }
            ),
            "citations": [],
            "model": "test-news-model",
        }

    report = run_organization_news_research(
        database_url,
        output_dir=tmp_path / "news",
        limit=100000,
        apply=True,
        research_company_news=fake_researcher,
        skipped_domains=set(),
        skipped_system_localparts=set(),
        skipped_system_prefixes=set(),
    )

    assert report["researched"] >= 1
    assert any(call["domain"] == domain for call in calls)
    with psycopg.connect(database_url) as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT count(*)::int
                FROM relationship_substrate.research_snapshot
                WHERE subject = %s
                AND subject_type = 'organization_news'
                """,
                (domain,),
            )
            assert cur.fetchone()[0] >= 1
            cur.execute(
                """
                SELECT metadata->'enrichment'
                FROM relationship_substrate.organization
                WHERE domain = %s
                """,
                (domain,),
            )
            row = cur.fetchone()
            assert row is None or row[0] is None


def test_run_organization_news_research_cli_passes_bounds(database_url, monkeypatch, tmp_path, capsys):
    from relationship_substrate import cli

    captured: dict[str, object] = {}

    def fake_runner(database_url: str, **kwargs: object) -> dict[str, object]:
        captured["database_url"] = database_url
        captured.update(kwargs)
        return {"ok": True, "researched": 1}

    monkeypatch.setattr(cli, "run_organization_news_research", fake_runner)
    monkeypatch.setattr(
        "sys.argv",
        [
            "relationship-substrate",
            "--database-url",
            database_url,
            "run-organization-news-research",
            "--output-dir",
            str(tmp_path / "org-news"),
            "--limit",
            "3",
            "--apply",
        ],
    )

    assert cli.main() == 0
    assert captured["database_url"] == database_url
    assert captured["output_dir"] == tmp_path / "org-news"
    assert captured["limit"] == 3
    assert captured["apply"] is True
    assert '"researched": 1' in capsys.readouterr().out
