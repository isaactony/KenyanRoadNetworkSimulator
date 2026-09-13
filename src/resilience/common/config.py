"""Per-region configuration.

This is the mechanism that keeps the pipeline region-agnostic: which city or
country to ingest, its source extract, and its projected CRS for metric
calculations (docs/data-model.md §1.1) are all read from a YAML file under
`configs/cities/`, never branched on in code.
"""

from __future__ import annotations

from pathlib import Path
from typing import Literal, Optional

import yaml
from pydantic import BaseModel, Field, model_validator

DEFAULT_OSM_LICENSE_NOTICE = "(C) OpenStreetMap contributors, ODbL 1.0"


class ExtractSource(BaseModel):
    """Where the raw .osm.pbf for this region comes from.

    Three source types, deliberately kept distinct rather than collapsed
    into "a path":

    - "url": the real path for local dev / production (Geofabrik, BBBike).
    - "local_path": a user already has an extract on disk (offline use, or
      a file that couldn't be fetched automatically in a network-restricted
      environment).
    - "pyrosm_test_fixture": a small, non-regional OSM extract bundled with
      the `pyrosm` package itself, used only to exercise the ingestion
      pipeline in environments without egress to OSM mirrors. Never a
      substitute for real regional data in an actual experiment.
    """

    type: Literal["url", "local_path", "pyrosm_test_fixture"]
    url: Optional[str] = None
    path: Optional[str] = None
    dataset: Optional[str] = None
    sha256: Optional[str] = Field(
        default=None,
        description="Pin an expected checksum for a 'url' source; recorded either way in provenance metadata.",
    )

    @model_validator(mode="after")
    def _require_matching_field(self) -> "ExtractSource":
        required = {"url": "url", "local_path": "path", "pyrosm_test_fixture": "dataset"}[self.type]
        if getattr(self, required) is None:
            raise ValueError(f"source.type='{self.type}' requires a '{required}' field")
        return self


class CityConfig(BaseModel):
    name: str
    region_type: Literal["country", "city", "neighborhood", "custom_polygon"]
    projected_crs_epsg: int = Field(
        description="EPSG code for the projected CRS used for length/area calculations in this region "
        "(e.g. 32737 = UTM 37S for Kenya). Never assumed globally — see docs/data-model.md §1.1."
    )
    source: ExtractSource
    license_notice: str = DEFAULT_OSM_LICENSE_NOTICE
    notes: Optional[str] = None


def load_city_config(path: str | Path) -> CityConfig:
    path = Path(path)
    with path.open("r", encoding="utf-8") as f:
        raw = yaml.safe_load(f)
    return CityConfig.model_validate(raw)
