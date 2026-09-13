"""End-to-end ingestion pipeline test.

Runs against configs/cities/sandbox_test.yaml, which resolves to a small
.osm.pbf bundled inside the installed `pyrosm` package — no network access
required, so this test runs the same in CI as it does in a network-
restricted sandbox. It is not Kenya data (see the config file for why);
it exists to prove the pipeline mechanics (download/resolve -> parse ->
validate -> write) work end to end against a real .osm.pbf file.
"""

from pathlib import Path

import geopandas as gpd

from resilience.common.config import load_city_config
from resilience.ingestion.pipeline import run_ingestion
from resilience.models.provenance import SourceExtractMetadata


def test_full_pipeline_runs_end_to_end(tmp_path: Path):
    config = load_city_config("configs/cities/sandbox_test.yaml")

    result = run_ingestion(config, tmp_path)

    assert result.extract_path.exists()
    assert result.source_extract_metadata_path.exists()
    assert result.validation_report_path.exists()

    metadata = SourceExtractMetadata.from_json_file(str(result.source_extract_metadata_path))
    assert metadata.region_name == "sandbox_test_fixture"
    assert metadata.file_size_bytes == result.extract_path.stat().st_size

    assert result.validation_report["raw_way_count"] > 0
    assert result.validation_report["raw_node_count"] > 0
    assert result.validation_report["schema_valid"] is True

    ways = gpd.read_parquet(result.processed_paths["raw_ways"])
    nodes = gpd.read_parquet(result.processed_paths["raw_nodes"])
    assert len(ways) == result.validation_report["raw_way_count"]
    assert len(nodes) == result.validation_report["raw_node_count"]
    assert ways.crs is not None
    assert nodes.crs is not None
    assert ways["geometry"].notna().all()


def test_pipeline_is_idempotent_across_runs(tmp_path: Path):
    config = load_city_config("configs/cities/sandbox_test.yaml")

    first = run_ingestion(config, tmp_path)
    second = run_ingestion(config, tmp_path)

    assert first.validation_report["raw_way_count"] == second.validation_report["raw_way_count"]
    assert first.validation_report["raw_node_count"] == second.validation_report["raw_node_count"]
