# Road Network Resilience Simulator

A geospatial data platform that ingests OpenStreetMap road-network data,
builds a graph representation of a road network, simulates disruptions
(road/intersection closures, random and targeted failures, geographic
disruptions), computes network resilience and accessibility metrics, and
exposes the results through an API and an interactive dashboard.

Designed to run identically on a small city extract (local development) or
a full Kenya extract (production-scale experiments) — region is a
configuration input, never a hardcoded assumption.

## Status: Phase 2 — Ingestion

Phase 1 (architecture/data model/roadmap, no code) is complete. Phase 2
(OSM ingestion) is built and tested. Start with the design docs, then see
"Running ingestion" below to actually use it.

- **[docs/architecture.md](docs/architecture.md)** — data flow, every
  technology choice and why, repository structure rationale, scaling
  strategy from 10K to 1M+ road segments, and the cloud (AWS) architecture.
- **[docs/data-model.md](docs/data-model.md)** — schema for roads,
  segments, intersections, classifications, disruption scenarios,
  simulation runs, and metrics; coordinate systems, graph node identity,
  directed/one-way handling, and how ambiguous OSM data (bridges, links,
  service roads, roundabouts, pedestrian-only ways) is resolved.
- **[docs/research-questions.md](docs/research-questions.md)** — the
  questions the system has to answer, which resilience metrics were chosen
  (and which were deliberately excluded) to answer them, and the five
  reproducible experiments the project runs.
- **[docs/roadmap.md](docs/roadmap.md)** — the 12-phase build plan and the
  "done" criteria for each phase.

## Running ingestion

```bash
pip install -r requirements.txt
pip install -e .

# Real regional data (needs normal internet access to BBBike/Geofabrik):
python scripts/ingest.py configs/cities/nairobi.yaml   # small city, local dev
python scripts/ingest.py configs/cities/kenya.yaml     # full country, production-scale

# Network-restricted environment (e.g. this project's own sandbox, which
# cannot reach Geofabrik/BBBike/Overpass at all — only package registries):
python scripts/ingest.py configs/cities/sandbox_test.yaml
```

The `sandbox_test.yaml` config resolves to a small `.osm.pbf` bundled
inside the `pyrosm` package itself, so it needs no network access — it
proves the pipeline (download/resolve → parse → validate → write
GeoParquet) works, but it is **not** Kenyan data (see the file for
details). `nairobi.yaml` and `kenya.yaml` run the identical pipeline
against real extracts; nothing in the code differs between them. Run
`pytest tests/` to execute the same pipeline as an automated test.

Each run writes, under `data/` (gitignored):
- `data/raw/<region>/` — the extract itself, `source_extract.json`
  (provenance: source, checksum, download time, ODbL notice), and a
  `validation_report.json`.
- `data/processed/<region>/` — `raw_ways.parquet` / `raw_nodes.parquet`
  (GeoParquet, CRS-aware).

## Repository layout

See `docs/architecture.md` §4 for the full structure and the reasoning
behind it. At a glance:

```
docs/           architecture, data model, methodology, roadmap
configs/        per-region config (bbox, CRS, extract source) — data, not code
src/resilience/ ingestion, geospatial, graph, simulation, analytics, api
sql/            PostGIS DDL + dbt project
experiments/    reproducible experiment scripts and their stored outputs
dashboard/      React + MapLibre frontend
tests/          unit, integration, fixtures
scripts/        operational one-offs
infra/          Docker, AWS (Terraform/CDK)
```

## Data source & attribution

Road network data is sourced from [OpenStreetMap](https://www.openstreetmap.org)
via [Geofabrik](https://download.geofabrik.de/) extracts.

> © OpenStreetMap contributors. Data available under the
> [Open Database License (ODbL) 1.0](https://opendatacommons.org/licenses/odbl/1.0/).

Every ingested extract's source URL, download date, and this notice are
recorded alongside the data itself (`source_extracts` table, see
`docs/data-model.md` §2.1) so attribution and provenance travel with every
derived dataset.

## Portfolio scope

This project reports only measured numbers — no fabricated scale or
performance claims. See `docs/architecture.md` §6 for how that's enforced
as the project grows past Phase 1.
