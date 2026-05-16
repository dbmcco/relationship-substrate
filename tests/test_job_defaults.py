from __future__ import annotations

from pathlib import Path


def test_nightly_worklist_defaults_disable_local_model_relationship_analysis():
    script = Path("ops/jobs/nightly-worklists.sh").read_text(encoding="utf-8")

    assert 'TONE_TENOR_LIMIT="${RELATIONSHIP_SUBSTRATE_TONE_TENOR_LIMIT:-0}"' in script
    assert 'STRENGTH_LIMIT="${RELATIONSHIP_SUBSTRATE_STRENGTH_LIMIT:-0}"' in script
    assert 'TONE_TENOR_ENABLED="${RELATIONSHIP_SUBSTRATE_TONE_TENOR_ENABLED:-0}"' in script
    assert 'STRENGTH_ENABLED="${RELATIONSHIP_SUBSTRATE_STRENGTH_ENABLED:-0}"' in script
    assert 'RELATIONSHIP_SUBSTRATE_TONE_TENOR_ENABLED=0' in script
    assert 'RELATIONSHIP_SUBSTRATE_STRENGTH_ENABLED=0' in script


def test_catchup_uses_remaining_queue_counts_before_steady_refresh():
    script = Path("ops/jobs/catchup-refresh-loop.sh").read_text(encoding="utf-8")

    assert 'TONE_TENOR_ENABLED="${RELATIONSHIP_SUBSTRATE_TONE_TENOR_ENABLED:-0}"' in script
    assert 'STRENGTH_ENABLED="${RELATIONSHIP_SUBSTRATE_STRENGTH_ENABLED:-0}"' in script
    assert "organization_remaining=" in script
    assert "tone_remaining=" in script
    assert "strength_remaining=" in script
    assert '.actionable_queues.organization_enrichment.count // 0' in script
    assert '.actionable_queues.relationship_tone_tenor_state.count // 0' in script
    assert '.actionable_queues.relationship_strength_state.count // 0' in script
    assert (
        'if [[ "$organization_remaining" == "0" && "$tone_remaining" == "0" '
        '&& "$strength_remaining" == "0" && "$failed_count" == "0" ]]; then'
    ) in script


def test_catchup_sleeps_when_only_disabled_local_model_queues_remain():
    script = Path("ops/jobs/catchup-refresh-loop.sh").read_text(encoding="utf-8")

    assert "local_model_backlog_suspended=0" in script
    assert (
        'if [[ "$TONE_TENOR_ENABLED" != "1" && "$TONE_TENOR_ENABLED" != "true" '
        '&& "$tone_remaining" != "0" ]]; then'
    ) in script
    assert (
        'if [[ "$STRENGTH_ENABLED" != "1" && "$STRENGTH_ENABLED" != "true" '
        '&& "$strength_remaining" != "0" ]]; then'
    ) in script
    assert (
        'elif [[ "$organization_remaining" == "0" && "$failed_count" == "0" '
        '&& "$local_model_backlog_suspended" == "1" ]]; then'
    ) in script


def test_substrate_cycle_disables_autonomous_ollama_embeddings_by_default():
    script = Path("ops/jobs/substrate-cycle.sh").read_text(encoding="utf-8")

    assert 'AUTONOMOUS_EMBEDDINGS_ENABLED="${RELATIONSHIP_SUBSTRATE_AUTONOMOUS_EMBEDDINGS_ENABLED:-0}"' in script
    assert 'EMBED_PROVIDER="${RELATIONSHIP_SUBSTRATE_EMBED_PROVIDER:-ollama}"' in script
    assert 'if [[ "$AUTONOMOUS_EMBEDDINGS_ENABLED" != "1" && "$AUTONOMOUS_EMBEDDINGS_ENABLED" != "true" ]]; then' in script
    assert "autonomous_cmd+=(--skip-embeddings)" in script
    assert '"${autonomous_cmd[@]}" > "${REPORT_DIR}/autonomous_backfill_stdout.json"' in script
