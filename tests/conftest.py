from __future__ import annotations

import os

import pytest


@pytest.fixture
def database_url() -> str:
    return os.environ.get(
        "RELATIONSHIP_SUBSTRATE_TEST_DATABASE_URL",
        "postgresql://localhost:5432/relationship_substrate_test",
    )
