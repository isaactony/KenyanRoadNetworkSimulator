import geopandas as gpd
import pandas as pd
import pytest
from shapely.geometry import LineString, Point

from resilience.ingestion.parse import RawOsmTables
from resilience.ingestion.validate import RawDataValidationError, validate_raw_tables


def _make_tables(ways_overrides=None, nodes_overrides=None) -> RawOsmTables:
    ways = gpd.GeoDataFrame(
        {
            "id": [1, 2],
            "highway": ["residential", "primary"],
            "oneway": ["yes", None],
            "osm_type": ["way", "way"],
            "geometry": [LineString([(0, 0), (1, 1)]), LineString([(1, 1), (2, 2)])],
        },
        crs="EPSG:4326",
    )
    if ways_overrides:
        ways = ways_overrides(ways)

    nodes = gpd.GeoDataFrame(
        {
            "id": [10, 11],
            "lat": [1.0, 2.0],
            "lon": [36.0, 37.0],
            "osm_type": ["node", "node"],
            "geometry": [Point(36.0, 1.0), Point(37.0, 2.0)],
        },
        crs="EPSG:4326",
    )
    if nodes_overrides:
        nodes = nodes_overrides(nodes)

    return RawOsmTables(nodes=nodes, ways=ways)


def test_valid_tables_pass_and_report_stats():
    tables = _make_tables()
    report = validate_raw_tables(tables, region_name="test_region")
    assert report["raw_way_count"] == 2
    assert report["raw_node_count"] == 2
    assert report["way_highway_tag_counts"] == {"residential": 1, "primary": 1}
    assert report["oneway_tag_coverage_pct"] == 50.0
    assert report["ways_with_unexpected_geometry_type"] == []


def test_duplicate_way_id_fails():
    tables = _make_tables(ways_overrides=lambda w: w.assign(id=[1, 1]))
    with pytest.raises(RawDataValidationError):
        validate_raw_tables(tables, region_name="test_region")


def test_missing_highway_tag_fails():
    tables = _make_tables(ways_overrides=lambda w: w.assign(highway=[None, "primary"]))
    with pytest.raises(RawDataValidationError):
        validate_raw_tables(tables, region_name="test_region")


def test_node_lat_out_of_range_fails():
    tables = _make_tables(nodes_overrides=lambda n: n.assign(lat=[91.0, 2.0]))
    with pytest.raises(RawDataValidationError):
        validate_raw_tables(tables, region_name="test_region")


def test_null_geometry_fails():
    tables = _make_tables(ways_overrides=lambda w: w.assign(geometry=[None, w.geometry.iloc[1]]))
    with pytest.raises(RawDataValidationError):
        validate_raw_tables(tables, region_name="test_region")
