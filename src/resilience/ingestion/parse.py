"""Parse a raw .osm.pbf extract into raw_nodes / raw_ways GeoDataFrames.

Scope is deliberately narrow: everything tagged `highway=*` (any value),
plus the standalone nodes that carry their own tags (barriers, traffic
signals, crossings, ...). This is the raw, road-relevant layer described in
docs/data-model.md §2.1 — classification into drivable/non-drivable
road_class, and resolving which nodes are graph-relevant intersections, are
Phase 3 (geospatial/graph construction) concerns, not done here.

Uses pyrosm (Cython-backed .pbf reader) as the parser, per
docs/architecture.md §3. osmium/pyosmium remains the documented fallback
for a file too large to parse in memory in one pass — not needed at the
scale this project actually ingests, so not implemented speculatively.
"""

from __future__ import annotations

from pathlib import Path

import geopandas as gpd
from pyrosm import OSM

from resilience.common.logging import get_logger

logger = get_logger(__name__)


class RawOsmTables:
    def __init__(self, nodes: gpd.GeoDataFrame, ways: gpd.GeoDataFrame):
        self.nodes = nodes
        self.ways = ways


def parse_osm_pbf(path: str | Path) -> RawOsmTables:
    path = Path(path)
    osm = OSM(str(path))

    combined = osm.get_data_by_custom_criteria(
        custom_filter={"highway": True},
        filter_type="keep",
        keep_nodes=True,
        keep_ways=True,
        keep_relations=False,
    )

    if combined is None or len(combined) == 0:
        raise ValueError(f"no highway-tagged elements found in {path}")

    ways = combined[combined["osm_type"] == "way"].copy().reset_index(drop=True)
    nodes = combined[combined["osm_type"] == "node"].copy().reset_index(drop=True)

    logger.info(
        "parsed raw OSM extract",
        context={"path": str(path), "raw_way_count": len(ways), "raw_node_count": len(nodes)},
    )
    return RawOsmTables(nodes=nodes, ways=ways)
