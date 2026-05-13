from __future__ import annotations

from enum import StrEnum
from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class SourcePosture(StrEnum):
    DIRECT_INTERACTION = "direct_interaction"
    CURATED_EXPORT = "curated_export"
    ENRICHMENT = "enrichment"
    DERIVED_INTERPRETATION = "derived_interpretation"


class SourceEventIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    source_name: str = Field(min_length=1)
    source_event_type: str = Field(min_length=1)
    source_event_key: str = Field(min_length=1)
    source_payload: dict[str, Any]
    source_posture: SourcePosture
    provenance_status: str = Field(min_length=1)
    trust_role: str = Field(min_length=1)
