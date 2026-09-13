"""Resolve a city's configured extract source to a local .osm.pbf file.

Handles all three `ExtractSource.type` values behind one function so the
rest of the pipeline never has to know whether the file was downloaded,
already local, or a bundled test fixture (docs/architecture.md §2, "raw
layer").
"""

from __future__ import annotations

import hashlib
import shutil
import time
from datetime import datetime, timezone
from pathlib import Path

import requests

from resilience.common.config import CityConfig
from resilience.common.logging import get_logger
from resilience.models.provenance import SourceExtractMetadata

logger = get_logger(__name__)

_MAX_RETRIES = 4
_BACKOFF_SECONDS = (2, 4, 8, 16)
_CHUNK_SIZE = 1024 * 1024


class ExtractDownloadError(RuntimeError):
    pass


def _sha256(path: Path) -> tuple[str, int]:
    h = hashlib.sha256()
    size = 0
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(_CHUNK_SIZE), b""):
            h.update(chunk)
            size += len(chunk)
    return h.hexdigest(), size


def _download_url(url: str, dest: Path) -> None:
    last_error: Exception | None = None
    for attempt, delay in enumerate((0,) + _BACKOFF_SECONDS[: _MAX_RETRIES], start=1):
        if delay:
            time.sleep(delay)
        try:
            with requests.get(url, stream=True, timeout=60) as resp:
                resp.raise_for_status()
                tmp = dest.with_suffix(dest.suffix + ".part")
                with tmp.open("wb") as f:
                    for chunk in resp.iter_content(chunk_size=_CHUNK_SIZE):
                        f.write(chunk)
                tmp.replace(dest)
            return
        except (requests.RequestException, OSError) as exc:
            last_error = exc
            logger.warning("download attempt failed", context={"attempt": attempt, "url": url, "error": str(exc)})
    raise ExtractDownloadError(f"failed to download {url} after {_MAX_RETRIES + 1} attempts") from last_error


def resolve_extract(config: CityConfig, raw_dir: Path) -> tuple[Path, SourceExtractMetadata]:
    """Fetch/locate the region's .osm.pbf and return (local_path, provenance metadata)."""
    raw_dir.mkdir(parents=True, exist_ok=True)
    dest = raw_dir / f"{config.name}.osm.pbf"
    source = config.source

    if source.type == "url":
        logger.info("downloading extract", context={"region": config.name, "url": source.url})
        _download_url(source.url, dest)
        source_location = source.url

    elif source.type == "local_path":
        src_path = Path(source.path)
        if not src_path.exists():
            raise FileNotFoundError(f"configured local_path does not exist: {src_path}")
        shutil.copyfile(src_path, dest)
        source_location = str(src_path)

    elif source.type == "pyrosm_test_fixture":
        from pyrosm.data import get_data

        fixture_path = Path(get_data(source.dataset))
        shutil.copyfile(fixture_path, dest)
        source_location = f"pyrosm bundled test fixture: {source.dataset} ({fixture_path.name})"
        logger.warning(
            "using a bundled pyrosm test fixture, NOT real regional data",
            context={"region": config.name, "dataset": source.dataset},
        )

    else:  # pragma: no cover - pydantic Literal already constrains this
        raise ValueError(f"unknown source type: {source.type}")

    checksum, size = _sha256(dest)
    if source.sha256 and source.sha256 != checksum:
        raise ExtractDownloadError(
            f"checksum mismatch for {dest}: expected {source.sha256}, got {checksum}"
        )

    metadata = SourceExtractMetadata(
        region_name=config.name,
        source_type=source.type,
        source_location=source_location,
        downloaded_at=datetime.now(timezone.utc),
        file_sha256=checksum,
        file_size_bytes=size,
        license_notice=config.license_notice,
    )
    logger.info(
        "extract resolved",
        context={"region": config.name, "path": str(dest), "sha256": checksum, "size_bytes": size},
    )
    return dest, metadata
