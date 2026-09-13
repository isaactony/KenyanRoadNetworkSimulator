# Architecture

## 1. What this system is

A data platform that turns OpenStreetMap road-network extracts into a graph,
runs disruption simulations against that graph, and serves the resulting
resilience/accessibility metrics through an API and dashboard. The city or
region is a **configuration input**, never a code branch — the same
pipeline runs on a small city extract for development and the full Kenya
extract for production-scale experiments (see `configs/cities/`).

## 2. Data flow

```
OpenStreetMap (.osm.pbf extract, Geofabrik)
   │  immutable download, checksummed, license notice attached
   ▼
Raw layer (bronze)                      [S3 / data/raw/]
   │  pyrosm/pyosmium parse → schema validation (pandera)
   ▼
Processed layer (silver) — partitioned Parquet   [S3 / data/processed/]
   │  raw_nodes, raw_ways, raw_relations, normalized + validated
   ▼
Spatial processing (GeoPandas/Shapely)
   │  filter to drivable ways, explode ways into segments at graph nodes,
   │  compute directionality, dedup/snap nodes, project for metric calcs
   ▼
PostGIS                                  [source of truth, queryable]
   │  intersections, road_segments, ways, destinations, regions
   ▼
Graph construction (NetworkX / igraph)
   │  build MultiDiGraph, freeze as a versioned "graph snapshot"
   ▼
Resilience analysis (simulation + analytics modules)
   │  connectivity / efficiency / accessibility / criticality
   ▼
Analytical tables (gold) — Postgres + dbt models
   │  network_metrics, road_criticality, affected_areas, destination_impact
   ▼
API (FastAPI)
   ▼
Web dashboard
```

Three storage tiers, deliberately:

- **Raw** — exactly what OSM gave us, never mutated. Reprocessing always
  starts here; this is what makes ingestion reproducible and what ODbL
  attribution/provenance is anchored to.
- **Processed** — validated, normalized, still close to OSM's own model
  (nodes/ways), but schema-checked and columnar. This is the layer other
  tools (DuckDB, Spark-if-ever-needed) can read directly without touching a
  database.
- **Analytics (gold)** — the opinionated, application-specific model
  (segments as graph edges, metrics, rankings) that the API actually serves.

## 3. Technology choices, and why

| Layer | Choice | Why this, not something else |
|---|---|---|
| Raw parsing | **pyrosm** (Cython-backed) | Fastest common way to get an `.osm.pbf` into (Geo)DataFrames without hand-rolling protobuf parsing. `osmium`/`pyosmium` is the fallback for streaming a file too large to fit in memory — a real, named scaling step, not used up front because it isn't needed at Kenya-extract scale. |
| Reference-only tool | **OSMnx** | Used only to cross-check graph construction during development (it has its own opinionated OSM→graph pipeline). Not used as the production parser because it bundles filtering, projection, and graph-building decisions we need to own and make explicit (drivability rules, weighting, directedness) — see `data-model.md`. |
| Validation | **pandera** (schema) | Declarative schema/contract checks between pipeline stages; fails fast and loud instead of letting a malformed extract silently produce a broken graph. |
| Interchange format | **Parquet**, partitioned by region | Columnar, compresses well, readable by pandas/GeoPandas/DuckDB/Spark alike without a database round-trip. This is what makes "processed" a real layer instead of just an implementation detail of the database loader. |
| Spatial processing | **GeoPandas + Shapely** | The standard, well-understood tool for vectorized geometry ops (projection, length, snapping, spatial joins) at the row counts this project actually has (10K–~1M segments). |
| Spatial database | **PostgreSQL + PostGIS** | The only entry in the list that is a hard requirement, not a preference: GIST-indexed geometry queries (nearest destination, roads-in-polygon for geographic disruptions, area rollups) are what a spatial database is *for*, and re-implementing them over flat files would be worse engineering, not more impressive engineering. |
| Graph engine | **NetworkX** (dev), **igraph** (scale) | NetworkX for development ergonomics and readability up to roughly 10^5 edges. Betweenness centrality (the main criticality metric) is O(V·E) — at Kenya-extract scale that is the actual bottleneck, and igraph's C backend is 10-50x faster for the same algorithm with near-identical semantics. Both read/write the same graph-snapshot format, so switching is a backend swap, not a redesign. |
| Analytical SQL | **dbt** (dbt-postgres) | The `analytics` layer (network_metrics rollups, criticality rankings, area vulnerability) is exactly what dbt is for: tested, documented, versioned SQL transformations over the PostGIS tables. Used only for this layer — not for ingestion, not for graph construction, because those aren't SQL-shaped problems. |
| Local analytics | **DuckDB** | Ad hoc/local querying of the Parquet processed layer (and of experiment outputs) without needing Postgres running — useful for development and for the "how would this change at 1M+ rows" story (§5), not a replacement for PostGIS in production. |
| API | **FastAPI** | Typed request/response models (pydantic), automatic OpenAPI schema, async-friendly for I/O-bound endpoints. Directly maps to the requirement that responses are clean DTOs, not raw graph/DB internals. |
| Dashboard | **React + MapLibre GL** | Needs real spatial interaction (select an area, draw a disruption polygon, compare two network states on a map) which a notebook-style dashboard (Streamlit/Dash) does not comfortably support. The tradeoff is accepted: more frontend surface area, in exchange for the map actually being the primary interface rather than an embedded image. |
| Containerization | **Docker / docker-compose** | Local reproducibility (Postgres+PostGIS, API, dashboard as one `docker-compose up`) and the deployable unit for ECS/Fargate later — same images, no rewrite between phases 11 and 12. |
| CI | **GitHub Actions** | Runs lint/type-check/unit+integration tests against a Postgres+PostGIS service container on every push; nothing exotic needed. |
| **Not used, and why** | **Apache Spark** | Included in the brief as a candidate, deliberately not adopted: the largest realistic dataset here (all of Kenya, ~1–2M road segments) fits comfortably in memory on a single reasonably sized machine for both GeoPandas processing and PostGIS storage. Spark would add distributed-systems overhead (cluster management, shuffle costs, a second execution model to test and deploy) with no corresponding data volume to justify it. It becomes justified only if scope expanded to multi-country/continental OSM processing — documented here as the honest answer to "where's the ceiling," not implemented speculatively. |

## 4. Repository structure

```
├── README.md
├── docs/                    # architecture, data model, methodology, roadmap
├── configs/
│   ├── cities/              # per-region config: bbox/polygon, extract URL, CRS, name — no hardcoded city logic
│   └── graph_profiles/      # drivability rules, weighting profiles (data-driven, versionable)
├── data/                    # raw/processed/analytics — gitignored except small fixtures
├── src/resilience/
│   ├── common/              # config loading, structured logging, seeding
│   ├── models/              # pydantic schemas shared across layers (the DTOs the API returns)
│   ├── ingestion/            # OSM download + raw parsing + validation
│   ├── geospatial/           # cleaning, projection, segment construction, PostGIS loaders
│   ├── graph/                # graph construction, snapshotting, node identity/dedup
│   ├── simulation/           # scenario definitions + the simulation engine
│   ├── analytics/            # connectivity/efficiency/accessibility/criticality metrics
│   ├── api/                  # FastAPI app
│   └── cli/                  # pipeline stage entry points (ingest, build-graph, run-experiment, ...)
├── sql/
│   ├── schema/               # PostGIS DDL / migrations
│   └── analytics/            # dbt project (gold-layer models)
├── experiments/              # reproducible experiment scripts + their stored outputs
├── dashboard/                # React app — separate toolchain, deliberately outside src/
├── tests/{unit,integration,fixtures}/
├── scripts/                  # operational one-offs (download an extract, seed a dev DB)
├── infra/{docker,aws}/
└── .github/workflows/
```

Deviations from the structure sketched in the brief, explained:

- **`sql/` and `dashboard/` live at the repo root, not under `src/`.** They
  are different toolchains with different dependency managers (dbt/SQL,
  npm) — nesting them inside a Python package tree would make both worse to
  work with (packaging tools would need to ignore them; editors would apply
  the wrong linting) for no organizational benefit.
- **`experiments/` is a top-level directory, not a subfolder of `analytics/`.**
  Experiments are reproducible *research* artifacts (a script plus its
  stored, versioned output) consumed by a person, distinct from
  `analytics/`, which is library code consumed by the simulation engine and
  API at runtime. Conflating them would make it unclear which code is
  "production" and which is "a report."
- **`configs/` is data, not code**, specifically so that adding a new city
  or region never means touching `src/`. This is the direct mechanism
  behind "do not hard-code Nairobi-specific assumptions."

## 5. Scaling: 10,000 → 1,000,000+ road segments

Called out explicitly, with the honest boundary for each layer:

- **Ingestion/parsing**: pyrosm holds up fine at 1M+ ways; the fallback is
  streaming with pyosmium if a future extract doesn't fit in memory. Not
  needed at Kenya scale on a normal machine, so not built preemptively.
- **Cleaning/segmentation (GeoPandas)**: vectorized operations scale roughly
  linearly and remain single-machine-feasible at 1M rows; the place this
  *would* start to hurt is row-wise Python loops (e.g., per-way node
  splitting logic written naively) — those are written as vectorized
  GeoPandas/NumPy operations from the start, not optimized later.
- **Storage/querying**: PostGIS with GIST indexes handles 1M+ geometries
  routinely; this is well inside its normal operating range, not a stretch.
- **Graph construction & connectivity/efficiency metrics**: NetworkX is
  adequate for development-scale extracts; igraph is the swap-in for
  country scale, same as noted in §3.
- **Criticality (betweenness centrality)**: this is the actual bottleneck at
  scale, addressed by (a) igraph's C backend, (b) sampling O-D pairs above a
  documented size threshold, (c) confirming only a top-K candidate set by
  exact removal-and-recompute rather than exhaustively testing every edge
  (see `research-questions.md` §2.4/§3).
- **Where DuckDB earns its place**: ad hoc analytical queries over the
  processed Parquet layer or experiment outputs, without spinning up
  Postgres — a development/analysis convenience, not a production
  dependency.
- **Where Spark would start to make sense**: only past single-machine
  memory/compute limits for the *raw parsing* stage itself — i.e.
  multi-country/planet-scale OSM, which is out of scope here. See §3.

## 6. On scale claims

This project reports only numbers it has actually measured (row counts,
wall-clock times for real pipeline runs, actual betweenness computation
times at the dev-extract size). Where a technique (sampling, igraph) is
adopted *because* it would be needed at a larger scale than has been tested
locally, that is stated as reasoning about complexity (e.g., "betweenness
is O(V·E), and the Kenya extract has ~N edges"), never as a fabricated
benchmark. Any benchmark quoted in later phases is reproducible from a
committed script.

## 7. Cloud architecture (AWS) — cheapest sensible version, and how it scales

Built only after the local system works end-to-end (Phase 12). Two
configurations, not one:

**Cheapest sensible (portfolio) architecture**

- **S3**: three prefixes/buckets (raw/processed/analytics), mirroring the
  local `data/` layout exactly — no logic changes when moving from local
  disk to S3, only paths.
- **RDS for PostgreSQL (PostGIS extension)**, single small instance
  (`db.t4g.micro`/`small`), no Multi-AZ. This is the one component kept
  running continuously (it holds state); everything else is designed to
  scale to zero when not being demoed.
- **API on Lambda + API Gateway** (FastAPI via Mangum) — pay-per-request,
  genuinely free/near-free between demos, which matters for a portfolio
  project that isn't serving sustained traffic.
- **Batch/graph-build as a scheduled Fargate task** (via EventBridge), not
  Lambda — OSM parsing and full graph construction for a country-size
  extract can exceed Lambda's memory/time limits; this is a real
  architectural boundary, stated honestly rather than forced onto Lambda.
- **ECR** for the batch/API container images.
- **CloudWatch** for logs and a small number of basic alarms (job failure,
  API 5xx rate).
- **S3 + CloudFront** for the static dashboard build.
- **Glue crawler + Athena**, included but explicitly optional/lightweight:
  useful for ad hoc SQL directly over the analytics Parquet without
  touching RDS, demonstrates the lake-query pattern, but is not load-bearing
  for the application itself at this project's actual data volume.

Estimated cost: low tens of USD/month if left running continuously (RDS is
the dominant cost), near-zero when the RDS instance is stopped/snapshotted
between portfolio demos — an estimate, not a billed measurement, and stated
as such.

**How it scales past portfolio size** (for discussion, not built here): RDS
→ a larger instance or read replica once query concurrency grows; the
Fargate batch job is already the right shape for larger extracts (raise
task memory/CPU rather than redesigning); Lambda API would move to
long-running ECS/Fargate once traffic is sustained rather than spiky, which
is also the point at which Lambda's per-invocation cost model stops being
the cheaper option.
