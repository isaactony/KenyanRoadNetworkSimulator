import pytest
from pydantic import ValidationError

from resilience.common.config import CityConfig, ExtractSource, load_city_config


def test_url_source_requires_url():
    with pytest.raises(ValidationError):
        ExtractSource(type="url")


def test_local_path_source_requires_path():
    with pytest.raises(ValidationError):
        ExtractSource(type="local_path")


def test_pyrosm_fixture_source_requires_dataset():
    with pytest.raises(ValidationError):
        ExtractSource(type="pyrosm_test_fixture")


def test_valid_url_source():
    source = ExtractSource(type="url", url="https://example.com/extract.osm.pbf")
    assert source.url.endswith(".osm.pbf")


def test_load_real_city_configs_parse(tmp_path):
    # The three shipped configs must always parse; this is the config
    # surface every phase after ingestion depends on.
    for name in ("nairobi.yaml", "kenya.yaml", "sandbox_test.yaml"):
        config = load_city_config(f"configs/cities/{name}")
        assert isinstance(config, CityConfig)
        assert config.projected_crs_epsg > 0
