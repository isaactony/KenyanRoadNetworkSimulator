# Implementation Roadmap

Each phase below produces something runnable and testable before the next
phase starts. "Done" criteria are stated so completion is checkable, not
just declared.

| Phase | Builds | Why now | Done when |
|---|---|---|---|
| **1. Architecture & data model** | This document set (`architecture.md`, `data-model.md`, `research-questions.md`, `roadmap.md`), repo skeleton | Every later phase needs a fixed vocabulary (what's a "segment," what's a "run") and a place to put files — deciding this after code exists means rewriting code | This PR — reviewed, no application code yet |
| **2. Ingestion** | Download a small city extract (e.g., via Geofabrik sub-region or `osmium extract` cut from a larger `.osm.pbf`), pyrosm parsing, pandera schema validation, raw + processed Parquet layers, `source_extracts` provenance record | Nothing downstream can be tested against fabricated data — real OSM data surfaces real messiness (missing tags, disconnected islands) that the rest of the design has to actually handle | `scripts/ingest.py <city-config>` runs end-to-end on a small extract; validation report printed; processed Parquet written and inspectable |
| **3. Road graph construction** | `road_classifications` seed data, way→segment explosion, node dedup/snapping, directionality resolution, PostGIS loader, first `graph_snapshot` | This is where most of the real design decisions in `data-model.md` §1 get implemented and become falsifiable | Loading the small extract produces a PostGIS graph whose node/edge counts and component count are sane and spot-checked against a manual OSM inspection of the same area |
| **4. Baseline network metrics** | Connectivity + efficiency metrics module, run against the Phase 3 snapshot with zero disruption | Establishes the "baseline run" (§`data-model.md` 2.3) that every later comparison is measured against | `network_metrics` populated for the baseline run; numbers match a hand-checked sanity case (e.g., a single connected component pre-disruption) |
| **5. Single-road failure simulation** | Simulation engine v1 (single-edge + targeted removal), connectivity/efficiency delta, bridge detection | The simplest scenario type, exercises the whole engine (load snapshot → apply → recompute → diff → persist) before adding complexity | Removing a known bridge edge measurably disconnects the graph in the output; removing a non-bridge edge does not |
| **6. Large-scale failure scenarios** | Random failure (seeded, multi-trial), geographic (polygon) failure, multi-edge failure | Where the sampling/scale strategy from `research-questions.md` §3 actually gets tested, not just designed | Experiments 2–4 (`research-questions.md` §4) run against the small extract and produce reproducible (same seed → same result) output |
| **7. PostGIS analytics + dbt** | `road_criticality`, `affected_areas`, `destination_impact` as dbt models over the simulation output; accessibility metrics against `destinations` | Moves the "gold layer" analytical SQL out of ad hoc Python into tested, documented dbt models | `dbt test` passes; Experiment 1 and 5 produce ranked output |
| **8. API** | FastAPI app implementing the endpoints in `architecture.md`/brief, pydantic request/response models, OpenAPI docs | Nothing outside Python can use the system until there's an API | `POST /simulate` → `GET /simulation/{id}` round-trip works against a running Postgres; integration tests cover it |
| **9. Dashboard** | React + MapLibre app: area selection, baseline map, scenario builder, run, before/after comparison view | The visual, explorable half of the portfolio deliverable | Can run a full scenario (draw a polygon, disable roads in it, run, see before/after) against the local API without touching the DB directly |
| **10. Experiments & benchmarking** | All five experiments in `research-questions.md` §4 run against both the small extract and the Kenya extract, with measured (not estimated) timings recorded | This is where scale claims stop being design-time reasoning and become actual numbers, per `architecture.md` §6 | Experiment outputs + a benchmarking note (real timings, real row counts) committed under `experiments/` |
| **11. Containerization** | Dockerfiles for API/batch, `docker-compose.yml` (Postgres+PostGIS, API, dashboard), CI running tests in containers | Makes local reproducibility real (not "works on my machine") and produces the exact images Phase 12 deploys | `docker-compose up` gives a working stack from a clean checkout; GitHub Actions green |
| **12. AWS deployment** | Terraform/CDK for the architecture in `architecture.md` §7 (S3, RDS, Lambda+API Gateway or Fargate, ECR, EventBridge, CloudWatch, optional Glue/Athena) | Last, because it should deploy something already proven to work locally, not be debugged in the cloud | Deployed stack reachable over the internet, API responds, cost within the estimated range; teardown instructions included |

## Phase 2 status: done, with one caveat

The ingestion pipeline (`src/resilience/ingestion/`, `scripts/ingest.py`) is
built and tested: resolve extract → pyrosm parse → pandera validation →
GeoParquet processed layer → `source_extracts` provenance JSON. 12 unit +
integration tests pass (`pytest tests/`).

**Caveat**: the sandboxed environment this was built in has no outbound
network access to Geofabrik, BBBike, or the Overpass API (its egress
allowlist covers package registries only) — see README.md "Running
ingestion" for what that means and how it was worked around. The pipeline
was therefore validated end-to-end against a small real `.osm.pbf` bundled
with the `pyrosm` package (`configs/cities/sandbox_test.yaml`) rather than
an actual Nairobi/Kenya extract. `configs/cities/nairobi.yaml` and
`kenya.yaml` are written and unit-tested for parsing, but have not
themselves been run — `scripts/ingest.py configs/cities/nairobi.yaml` is
the very next command to run in any environment with normal internet
access (or pointed at a manually-downloaded file via a `local_path`
source). Nothing in the pipeline is Nairobi-specific or fixture-specific;
the config is the only thing that changes.

## Sequencing notes

- Phases 2–4 must happen in order (can't build a graph from unvalidated
  data, can't measure a baseline without a graph). Phases 5–7 can be
  reordered relative to each other with modest rework, but are sequenced
  this way because each validates the previous one's output before adding
  scenario complexity.
- The dashboard (Phase 9) intentionally comes after the API (Phase 8): the
  system is designed to be fully usable via API + scripts/notebooks before
  any frontend exists, so the frontend is a consumer of a stable contract,
  not a co-developed guess.
- Phase 10 (experiments/benchmarking against the Kenya extract) deliberately
  precedes containerization and cloud deployment: if a scale assumption in
  `architecture.md` turns out wrong, it's caught while still cheap to fix —
  before building deployment automation around it.
