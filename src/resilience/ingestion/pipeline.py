"""Ingestion pipeline orchestration: resolve -> parse -> validate -> write.

This is the Phase 2 slice of docs/architecture.md's data flow diagram:
OpenStreetMap -> raw layer -> ingestion/validation -> processed Parquet.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

from resilience.common.config import CityConfig
from resilience.common.logging import get_logger
from resilience.ingestion.download import resolve_extract
from resilience.ingestion.parse import parse_osm_pbf
from resilience.ingestion.validate import validate_raw_tables
from resilience.ingestion.write_processed import write_processed_tables

logger = get_logger(__name__)


@dataclass
class IngestionResult:
    region_name: str
    extract_path: Path
    source_extract_metadata_path: Path
    validation_report_path: Path
    processed_paths: dict[str, Path]
    validation_report: dict


def run_ingestion(config: CityConfig, data_dir: Path) -> IngestionResult:
    raw_dir = data_dir / "raw" / config.name
    processed_dir = data_dir / "processed"

    extract_path, metadata = resolve_extract(config, raw_dir)
    metadata_path = raw_dir / "source_extract.json"
    metadata.to_json_file(str(metadata_path))

    tables = parse_osm_pbf(extract_path)
    report = validate_raw_tables(tables, config.name)

    report_path = raw_dir / "validation_report.json"
    with report_path.open("w", encoding="utf-8") as f:
        json.dump(report, f, indent=2, default=str)

    processed_paths = write_processed_tables(tables, config.name, processed_dir)

    logger.info("ingestion complete", context={"region": config.name})
    return IngestionResult(
        region_name=config.name,
        extract_path=extract_path,
        source_extract_metadata_path=metadata_path,
        validation_report_path=report_path,
        processed_paths=processed_paths,
        validation_report=report,
    )
