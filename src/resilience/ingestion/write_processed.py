"""Write validated raw tables to the processed (Parquet) layer.

Partitioned by region at the directory level (`data/processed/<region>/...`)
— per docs/architecture.md §2, this is the layer other tools (DuckDB, a
notebook, a future Spark job) can read directly without touching a
database. Written with GeoParquet (geopandas' `to_parquet`) so geometry and
CRS survive the round trip, not as WKT strings in a plain column.
"""

from __future__ import annotations

from pathlib import Path

from resilience.common.logging import get_logger
from resilience.ingestion.parse import RawOsmTables

logger = get_logger(__name__)


def write_processed_tables(tables: RawOsmTables, region_name: str, processed_dir: Path) -> dict[str, Path]:
    region_dir = processed_dir / region_name
    region_dir.mkdir(parents=True, exist_ok=True)

    ways_path = region_dir / "raw_ways.parquet"
    nodes_path = region_dir / "raw_nodes.parquet"

    tables.ways.to_parquet(ways_path)
    tables.nodes.to_parquet(nodes_path)

    logger.info(
        "wrote processed layer",
        context={"region": region_name, "raw_ways_path": str(ways_path), "raw_nodes_path": str(nodes_path)},
    )
    return {"raw_ways": ways_path, "raw_nodes": nodes_path}
