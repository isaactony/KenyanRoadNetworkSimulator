#!/usr/bin/env python3
"""CLI entry point for Phase 2: ingest one region's OSM extract.

Usage:
    python scripts/ingest.py configs/cities/<region>.yaml [--data-dir data]
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from resilience.common.config import load_city_config
from resilience.common.logging import configure_logging
from resilience.ingestion.pipeline import run_ingestion


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("config", help="Path to a city config YAML file (see configs/cities/)")
    parser.add_argument("--data-dir", default="data", help="Root data directory (default: ./data)")
    args = parser.parse_args()

    configure_logging()

    config = load_city_config(args.config)
    result = run_ingestion(config, Path(args.data_dir))

    print(f"\n=== Ingestion summary: {result.region_name} ===")
    print(f"extract:            {result.extract_path}")
    print(f"source metadata:     {result.source_extract_metadata_path}")
    print(f"validation report:   {result.validation_report_path}")
    print(f"processed raw_ways:  {result.processed_paths['raw_ways']}")
    print(f"processed raw_nodes: {result.processed_paths['raw_nodes']}")
    print(f"raw way count:       {result.validation_report['raw_way_count']}")
    print(f"raw node count:      {result.validation_report['raw_node_count']}")
    print(f"oneway tag coverage: {result.validation_report['oneway_tag_coverage_pct']}%")
    print("highway tag distribution:")
    print(json.dumps(result.validation_report["way_highway_tag_counts"], indent=2))
    if result.validation_report["ways_with_unexpected_geometry_type"]:
        print(
            f"WARNING: {len(result.validation_report['ways_with_unexpected_geometry_type'])} "
            "ways have an unexpected geometry type (see validation report)"
        )
    return 0


if __name__ == "__main__":
    sys.exit(main())
