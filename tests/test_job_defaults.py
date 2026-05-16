from __future__ import annotations

from pathlib import Path


def test_nightly_worklist_defaults_raise_relationship_analysis_throughput():
    script = Path("ops/jobs/nightly-worklists.sh").read_text(encoding="utf-8")

    assert 'TONE_TENOR_LIMIT="${RELATIONSHIP_SUBSTRATE_TONE_TENOR_LIMIT:-20}"' in script
    assert 'STRENGTH_LIMIT="${RELATIONSHIP_SUBSTRATE_STRENGTH_LIMIT:-20}"' in script
