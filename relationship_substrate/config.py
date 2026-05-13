from __future__ import annotations

import os
from dataclasses import dataclass


@dataclass(frozen=True)
class Settings:
    database_url: str = os.environ.get(
        "RELATIONSHIP_SUBSTRATE_DATABASE_URL",
        "postgresql://localhost:5432/relationship_substrate",
    )
    msgvault_binary: str = os.environ.get(
        "MSGVAULT_BIN",
        "/Users/braydon/.local/bin/msgvault",
    )
    msgvault_home: str = os.environ.get(
        "MSGVAULT_HOME",
        "/Volumes/data2/msgvault",
    )
    msgvault_config: str = os.environ.get(
        "MSGVAULT_CONFIG",
        "/Volumes/data2/msgvault/config.toml",
    )
