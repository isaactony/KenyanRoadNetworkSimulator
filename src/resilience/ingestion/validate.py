"""Validate raw OSM tables against the contracts in models/osm_raw.py.

Philosophy (docs/architecture.md §3): structural problems — a missing
highway tag, a null geometry, a duplicate id — fail the run immediately
rather than silently propagating into a broken graph downstream. Everything
else (tag coverage, geometry-type distribution) is reported as data-quality
information, not treated as an error, since the graph-construction stage
that actually needs those attributes handles missing values by design (see
docs/data-model.md §1.6).
"""

from __future__ import annotations

from typing import Any

import pandera.errors

from resilience.common.logging import get_logger
from resilience.ingestion.parse import RawOsmTables
from resilience.models.osm_raw import (
    raw_nodes_schema,
    raw_ways_schema,
    validate_way_geometry_types,
)

logger = get_logger(__name__)


class RawDataValidationError(RuntimeError):
    pass


def validate_raw_tables(tables: RawOsmTables, region_name: str) -> dict[str, Any]:
    errors: list[str] = []

    try:
        raw_ways_schema.validate(tables.ways, lazy=True)
    except pandera.errors.SchemaErrors as exc:
        errors.append(f"raw_ways schema violations:\n{exc.failure_cases}")

    try:
        raw_nodes_schema.validate(tables.nodes, lazy=True)
    except pandera.errors.SchemaErrors as exc:
        errors.append(f"raw_nodes schema violations:\n{exc.failure_cases}")

    if errors:
        message = "\n\n".join(errors)
        logger.error("raw data validation failed", context={"region": region_name})
        raise RawDataValidationError(message)

    bad_geom_ids = validate_way_geometry_types(tables.ways)
    highway_counts = tables.ways["highway"].value_counts().to_dict()
    oneway_coverage = (
        float(tables.ways["oneway"].notna().mean()) if "oneway" in tables.ways.columns else 0.0
    )

    report = {
        "region_name": region_name,
        "raw_way_count": int(len(tables.ways)),
        "raw_node_count": int(len(tables.nodes)),
        "way_highway_tag_counts": highway_counts,
        "ways_with_unexpected_geometry_type": bad_geom_ids,
        "oneway_tag_coverage_pct": round(oneway_coverage * 100, 1),
        "schema_valid": True,
    }
    logger.info("raw data validation passed", context=report)
    return report
