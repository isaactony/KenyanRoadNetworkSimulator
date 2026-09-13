"""Provenance metadata for a single ingested extract.

Mirrors the `source_extracts` table design in docs/data-model.md §2.1. In
Phase 2 this is persisted as a JSON sidecar next to the raw/processed data
(no Postgres yet — that lands in Phase 3); the fields are the same ones
that table will hold, so loading this into Postgres later is a straight
copy, not a redesign.
"""

from __future__ import annotations

from datetime import datetime
from typing import Optional
from uuid import UUID, uuid4

from pydantic import BaseModel, Field


class SourceExtractMetadata(BaseModel):
    extract_id: UUID = Field(default_factory=uuid4)
    region_name: str
    source_type: str
    source_location: str
    downloaded_at: datetime
    file_sha256: str
    file_size_bytes: int
    license_notice: str

    def to_json_file(self, path: str) -> None:
        with open(path, "w", encoding="utf-8") as f:
            f.write(self.model_dump_json(indent=2))

    @classmethod
    def from_json_file(cls, path: str) -> "SourceExtractMetadata":
        with open(path, "r", encoding="utf-8") as f:
            return cls.model_validate_json(f.read())
