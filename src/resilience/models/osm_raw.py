"""Validation contracts for the raw OSM layer (docs/data-model.md §2.1).

These are deliberately narrow: they check that the raw layer is
structurally sound (ids present and unique, coordinates in range, a
geometry exists, a highway tag exists on every way) — not that the data is
"good" in some subjective sense. Classification, drivability, and
attribute imputation are Phase 3 (geospatial/graph) concerns and are not
enforced here.
"""

from __future__ import annotations

import pandera.pandas as pa
from pandera.pandas import Check, Column, DataFrameSchema

VALID_WAY_GEOM_TYPES = {"LineString", "MultiLineString"}

raw_ways_schema = DataFrameSchema(
    {
        "id": Column(pa.Int64, unique=True, nullable=False),
        "highway": Column(str, nullable=False),
        "geometry": Column(
            "geometry",
            checks=Check(lambda s: s.notna().all(), error="geometry must not be null"),
            nullable=False,
        ),
        "osm_type": Column(str, checks=Check.isin(["way"])),
    },
    strict=False,  # extra OSM tag columns (oneway, bridge, lanes, ...) pass through unvalidated here
    coerce=False,
)

raw_nodes_schema = DataFrameSchema(
    {
        "id": Column(pa.Int64, unique=True, nullable=False),
        "lat": Column(float, checks=Check.in_range(-90.0, 90.0), nullable=False),
        "lon": Column(float, checks=Check.in_range(-180.0, 180.0), nullable=False),
        "geometry": Column(
            "geometry",
            checks=Check(lambda s: s.notna().all(), error="geometry must not be null"),
            nullable=False,
        ),
        "osm_type": Column(str, checks=Check.isin(["node"])),
    },
    strict=False,
    coerce=False,
)


def validate_way_geometry_types(ways) -> list[str]:
    """Return way ids whose geometry type is outside VALID_WAY_GEOM_TYPES (a warning, not a hard failure)."""
    bad = ways[~ways.geometry.geom_type.isin(VALID_WAY_GEOM_TYPES)]
    return bad["id"].tolist()
