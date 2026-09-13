# Data Model

This is a design document. The DDL below is illustrative of the schema being
committed to; the actual migration files are created in Phase 2/7 of
`roadmap.md`, not here.

## 1. Foundational decisions

### 1.1 Coordinate systems

- All geometry is **stored** in EPSG:4326 (WGS84 lat/lon) — the natural
  storage/interchange CRS for OSM data and for serving GeoJSON to a web map.
- All **metric calculations** (length, area, distance-based weights) are
  done in a **projected CRS chosen per region**, never in degrees. The
  projected CRS is a field on the region's config (`configs/cities/*.yaml`),
  e.g. UTM zone 37S (EPSG:32737) for Kenya — this is what "no hardcoded
  Nairobi assumptions" means concretely for geometry: the projection is a
  config value resolved from the region being processed, not a constant in
  code.
- PostGIS geometry columns carry an explicit SRID (4326); a generated/derived
  projected geometry is computed at query or ETL time from that config, not
  stored as a second permanent geometry column, to avoid two sources of
  truth for the same shape.

### 1.2 Graph node identity

- OSM node ids are the starting identity, but are **not** used directly as
  the graph's canonical node id, because:
  - Multiple raw OSM nodes can represent the same real intersection to
    within survey/import tolerance (duplicate mapping, disconnected
    imports) and need to be snapped/merged.
  - A node id must be stable across re-ingestion of an updated extract even
    if OSM ids for some features shift (rare, but the model doesn't assume
    it can't happen).
- `intersections.node_id` is a **surrogate key**; `intersections.osm_ids`
  (array) retains every original OSM node id folded into that canonical
  node, so provenance is never lost even after deduplication.
- A node only becomes an `intersections` row if it is graph-relevant: shared
  by ≥2 drivable ways, a dead end, or tagged with something graph-relevant
  (barrier, traffic signal, roundabout node). Plain shape-defining points
  along a single way are **not** materialized as graph nodes — they remain
  as intermediate vertices of the `road_segments.geom` LineString. This is
  the mechanism by which "a road segment ≠ an OSM way": a single long OSM
  way is cut into one segment per pair of consecutive graph-relevant nodes.

### 1.3 Directed vs. undirected, one-way roads

- The graph's source of truth is a **directed multigraph** (NetworkX
  `MultiDiGraph` / igraph directed graph with parallel edges allowed).
  Directed, because one-way streets are common and directionally asymmetric
  travel cost is a real feature, not an edge case. Multigraph, because two
  distinct OSM ways can legitimately connect the same node pair (e.g. a
  divided carriageway modeled as two separate one-way ways, or a service
  road running parallel to a main road).
- `oneway=yes/true/1` → single forward edge. `oneway=-1` → single edge in
  the reverse of the way's node order. `oneway` absent/`no` → two directed
  edges (there and back) sharing the same geometry/segment id, with
  `oneway_direction = 'both'` recorded on the segment.
- `junction=roundabout` implies one-way in the direction of the way's node
  sequence even when `oneway` is not explicitly tagged (per OSM convention),
  handled as an explicit rule in `road_classifications`/ingestion logic
  rather than a silent default.
- Undirected connectivity metrics (connected components, largest component)
  are computed on an **undirected projection** derived from the directed
  graph at analysis time — never a second persisted graph — since it is
  always exactly derivable from the directed one and keeping it separate
  would risk drift.

### 1.4 Road segments vs. OSM ways

Kept as two related-but-distinct tables (`ways`, `road_segments`), not one:

- `ways` = one row per raw OSM way, full tag bag preserved, `is_drivable`
  and related flags computed once per way.
- `road_segments` = one row per graph edge, i.e. one row per (way, sub-span
  between two consecutive graph-relevant nodes). A single way normally
  produces multiple segments.

This split is what makes the "not every OSM way becomes a drivable edge, and
not every OSM node becomes a graph node" requirement explicit and queryable,
rather than an implicit side effect of the ETL code.

### 1.5 What becomes a drivable edge (and what doesn't)

Drivability is **data-driven**, not hardcoded in Python: `road_classifications`
maps every `highway=*` tag value to `is_drivable_default`, a `road_class`,
and default attributes. Ingestion logic looks up this table rather than
containing an if/else chain, so refining the rules is a data change, not a
code change.

| `highway` value | Drivable? | Notes |
|---|---|---|
| motorway, trunk, primary, secondary, tertiary, unclassified, residential | yes | core network |
| motorway_link, trunk_link, primary_link, ... | yes | `road_class = 'link'`, lower default speed |
| service | yes, but flagged | drivable by default, `is_service = true` so analyses can optionally exclude it for a "core network only" view |
| living_street | yes | low default speed |
| track | configurable | off by default for the urban Kenya use case, exposed as a config flag since rural extracts may want it |
| pedestrian, footway, path, steps, cycleway | **no** | excluded from the vehicle graph; `is_pedestrian_only = true` retained for a possible future pedestrian-accessibility graph, not built now |
| construction, proposed, abandoned | no | not currently drivable by definition |

Roundabouts (`junction=roundabout`) are **not** split into multiple segments
beyond normal intersection-node rules — they are treated as an ordinary
(directed, per §1.3) way/segment sequence, since splitting them further adds
no analytical value and would just multiply row count.

### 1.6 Disconnected components, duplicates, missing data

- **Disconnected components are expected**, not treated as a bug: real OSM
  extracts contain them (mapping gaps, genuinely separate islands/areas
  reachable only by ferry/unmapped roads). The ingestion pipeline reports
  component count/size distribution as a **data-quality metric** at load
  time. Whether resilience analysis restricts itself to the largest
  component or works on the full (possibly disconnected) graph is a
  parameter of the analysis, not a decision silently made during ingestion.
- **Duplicate/overlapping geometries** (common from multipolygon relations
  or double-digitized ways) are resolved by node snapping within a
  configured tolerance (meters, in the projected CRS) followed by merging
  nodes that snap together; the tolerance value lives in
  `configs/graph_profiles/`, not in code.
- **Missing attributes** (no `maxspeed`, no `lanes`, etc.) are filled from
  `road_classifications` defaults **and explicitly flagged** — a
  `data_quality_flags` JSONB column on `road_segments` records which fields
  were imputed vs. sourced from OSM, so "we guessed the speed limit" is
  always distinguishable from "OSM told us the speed limit," which matters
  once these attributes become simulation weights.

### 1.7 Bridges, tunnels

Stored as boolean flags (`is_bridge`, `is_tunnel`) from OSM tags. Currently
informational (surfaced in results, not yet a weight factor) — the
documented next step is using them as a fragility multiplier in
flood/disaster-specific geographic scenarios, deliberately not built in
Phase 1–6 since it isn't needed to answer the core questions in
`research-questions.md` yet.

## 2. Schema (illustrative DDL)

### 2.1 Raw / provenance

```sql
CREATE TABLE source_extracts (
    extract_id          UUID PRIMARY KEY,
    region_id           UUID REFERENCES regions(region_id),
    source_url          TEXT NOT NULL,
    downloaded_at        TIMESTAMPTZ NOT NULL,
    pbf_checksum_sha256  TEXT NOT NULL,
    osm_license_notice   TEXT NOT NULL DEFAULT
        '(C) OpenStreetMap contributors, ODbL 1.0',
    bbox_or_polygon      GEOMETRY(GEOMETRY, 4326)
);
```

`raw_nodes` / `raw_ways` / `raw_relations` live in the **processed Parquet
layer**, not PostGIS (see `architecture.md` §2) — they are the validated but
still OSM-shaped normalization of the `.osm.pbf`, partitioned by
`region_id`. Their columns mirror OSM's own model (id, version, timestamp,
changeset, tags, node refs) plus `source_extract_id`.

### 2.2 Core PostGIS entities

```sql
CREATE TABLE regions (
    region_id     UUID PRIMARY KEY,
    name          TEXT NOT NULL,
    region_type   TEXT NOT NULL CHECK (region_type IN
                     ('country','city','neighborhood','custom_polygon')),
    parent_region_id UUID REFERENCES regions(region_id),
    projected_crs_epsg INTEGER NOT NULL,   -- e.g. 32737 for Kenya (UTM 37S)
    geom          GEOMETRY(MULTIPOLYGON, 4326) NOT NULL
);

CREATE TABLE road_classifications (
    highway_tag         TEXT PRIMARY KEY,   -- raw OSM highway=* value
    road_class          TEXT NOT NULL,      -- motorway|trunk|primary|...|link|service
    is_drivable_default BOOLEAN NOT NULL,
    default_speed_kph   NUMERIC,
    default_lanes       INTEGER
);

CREATE TABLE ways (
    way_id          BIGINT PRIMARY KEY,       -- OSM way id
    region_id       UUID NOT NULL REFERENCES regions(region_id),
    highway_tag     TEXT,
    name            TEXT,
    tags            JSONB NOT NULL DEFAULT '{}',
    is_drivable     BOOLEAN NOT NULL,
    is_pedestrian_only BOOLEAN NOT NULL DEFAULT false,
    is_service      BOOLEAN NOT NULL DEFAULT false,
    is_link         BOOLEAN NOT NULL DEFAULT false,
    source_extract_id UUID REFERENCES source_extracts(extract_id)
);

CREATE TABLE intersections (
    node_id       UUID PRIMARY KEY,           -- surrogate canonical id
    osm_ids       BIGINT[] NOT NULL,          -- provenance: original OSM node ids merged here
    region_id     UUID NOT NULL REFERENCES regions(region_id),
    node_type     TEXT NOT NULL CHECK (node_type IN
                     ('intersection','dead_end','roundabout_node',
                      'barrier','traffic_signal','other')),
    geom          GEOMETRY(POINT, 4326) NOT NULL,
    source_extract_id UUID REFERENCES source_extracts(extract_id)
);
CREATE INDEX idx_intersections_geom ON intersections USING GIST (geom);

CREATE TABLE road_segments (
    segment_id      UUID PRIMARY KEY,
    way_id          BIGINT NOT NULL REFERENCES ways(way_id),
    from_node_id    UUID NOT NULL REFERENCES intersections(node_id),
    to_node_id      UUID NOT NULL REFERENCES intersections(node_id),
    region_id       UUID NOT NULL REFERENCES regions(region_id),
    geom            GEOMETRY(LINESTRING, 4326) NOT NULL,
    length_m        NUMERIC NOT NULL,          -- computed in region's projected CRS
    oneway_direction TEXT NOT NULL CHECK (oneway_direction IN
                        ('forward','backward','both')),
    road_class      TEXT NOT NULL,
    surface         TEXT,
    lanes           INTEGER,
    maxspeed_kph    NUMERIC,
    is_bridge       BOOLEAN NOT NULL DEFAULT false,
    is_tunnel       BOOLEAN NOT NULL DEFAULT false,
    is_roundabout   BOOLEAN NOT NULL DEFAULT false,
    data_quality_flags JSONB NOT NULL DEFAULT '{}',  -- which fields were imputed
    source_extract_id UUID REFERENCES source_extracts(extract_id)
);
CREATE INDEX idx_road_segments_geom ON road_segments USING GIST (geom);
CREATE INDEX idx_road_segments_from ON road_segments (from_node_id);
CREATE INDEX idx_road_segments_to   ON road_segments (to_node_id);

CREATE TABLE destinations (
    destination_id  UUID PRIMARY KEY,
    region_id       UUID NOT NULL REFERENCES regions(region_id),
    name            TEXT,
    category        TEXT NOT NULL CHECK (category IN
                       ('hospital','school','market','transit','commercial','other')),
    geom            GEOMETRY(POINT, 4326) NOT NULL,
    nearest_node_id UUID REFERENCES intersections(node_id),
    tags            JSONB NOT NULL DEFAULT '{}',
    source_extract_id UUID REFERENCES source_extracts(extract_id)
);
CREATE INDEX idx_destinations_geom ON destinations USING GIST (geom);
```

### 2.3 Graph, simulation, and analytics (gold layer)

```sql
CREATE TABLE graph_snapshots (
    snapshot_id   UUID PRIMARY KEY,
    region_id     UUID NOT NULL REFERENCES regions(region_id),
    node_count    INTEGER NOT NULL,
    edge_count    INTEGER NOT NULL,
    storage_path  TEXT NOT NULL,     -- serialized graph artifact (S3/local path)
    created_at    TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE disruption_scenarios (
    scenario_id   UUID PRIMARY KEY,
    region_id     UUID NOT NULL REFERENCES regions(region_id),
    name          TEXT NOT NULL,
    scenario_type TEXT NOT NULL CHECK (scenario_type IN
                     ('single_edge','targeted','random','geographic','multi_edge')),
    parameters    JSONB NOT NULL,    -- e.g. {"failure_pct":0.1,"seed":42} or {"polygon":"..."} 
    created_at    TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE simulation_runs (
    run_id              UUID PRIMARY KEY,
    scenario_id         UUID REFERENCES disruption_scenarios(scenario_id),  -- null for the baseline run
    graph_snapshot_id   UUID NOT NULL REFERENCES graph_snapshots(snapshot_id),
    seed                INTEGER,
    removed_node_ids     UUID[] NOT NULL DEFAULT '{}',
    removed_segment_ids  UUID[] NOT NULL DEFAULT '{}',  -- concrete resolved removal set
    status              TEXT NOT NULL CHECK (status IN
                           ('pending','running','completed','failed')),
    started_at          TIMESTAMPTZ,
    completed_at        TIMESTAMPTZ,
    runtime_ms          INTEGER
);

CREATE TABLE network_metrics (
    metric_id         UUID PRIMARY KEY,
    run_id            UUID NOT NULL REFERENCES simulation_runs(run_id),
    scope_type        TEXT NOT NULL CHECK (scope_type IN ('network','region','component')),
    scope_id          UUID,             -- region_id when scope_type='region', null for 'network'
    num_nodes         INTEGER NOT NULL,
    num_edges         INTEGER NOT NULL,
    num_components    INTEGER NOT NULL,
    largest_component_pct NUMERIC NOT NULL,
    avg_shortest_path_cost NUMERIC,
    network_efficiency NUMERIC NOT NULL,
    computed_at       TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE affected_areas (
    run_id                UUID NOT NULL REFERENCES simulation_runs(run_id),
    region_id             UUID NOT NULL REFERENCES regions(region_id),
    isolated              BOOLEAN NOT NULL,
    accessibility_before  NUMERIC,
    accessibility_after   NUMERIC,
    pct_change            NUMERIC,
    rank                  INTEGER,
    PRIMARY KEY (run_id, region_id)
);

CREATE TABLE destination_impact (
    run_id                  UUID NOT NULL REFERENCES simulation_runs(run_id),
    destination_id          UUID NOT NULL REFERENCES destinations(destination_id),
    baseline_travel_cost    NUMERIC,
    disrupted_travel_cost   NUMERIC,
    pct_increase            NUMERIC,
    became_unreachable      BOOLEAN NOT NULL DEFAULT false,
    PRIMARY KEY (run_id, destination_id)
);

CREATE TABLE road_criticality (
    segment_id              UUID NOT NULL REFERENCES road_segments(segment_id),
    graph_snapshot_id       UUID NOT NULL REFERENCES graph_snapshots(snapshot_id),
    betweenness_centrality  NUMERIC,
    is_bridge               BOOLEAN NOT NULL,
    efficiency_contribution NUMERIC,   -- measured Δefficiency when removed alone
    composite_rank          INTEGER,
    computed_at             TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (segment_id, graph_snapshot_id)
);
```

Notes on this layer:

- `simulation_runs` models the **baseline** as a run with `scenario_id NULL`
  and empty removal sets, so `network_metrics` has one consistent shape for
  both baseline and disrupted state instead of a special-cased "baseline"
  table — comparisons are just "join two runs against the same
  `graph_snapshot_id`."
- `disruption_scenarios` (reusable template/definition, e.g. "remove 10% of
  edges at random") is separate from `simulation_runs` (one concrete
  execution, with the actual resolved node/edge ids and a seed) because a
  random or targeted scenario resolves differently each execution — the
  scenario is the recipe, the run is the reproducible, persisted result of
  following it once.
- `road_criticality` is keyed by `graph_snapshot_id`, not recomputed
  per-simulation-run — it's a periodic analytics refresh (Experiment 1),
  not something every disruption run redoes.

## 3. Indexing / partitioning notes

- GIST indexes on every geometry column (shown above) — required for the
  spatial queries the whole system depends on (roads-in-polygon for
  geographic disruptions, nearest-destination lookups, area rollups).
- `region_id` is denormalized onto `intersections` and `road_segments`
  (rather than requiring a spatial join to filter by region) because
  "filter to this region" is the single most common query pattern (every
  simulation scopes to a region).
- No table partitioning at the sizes this project actually targets
  (10K–~1M rows) — PostGIS with proper indexes handles that directly.
  Partitioning `road_segments`/`network_metrics` by `region_id` is a
  documented option if the project ever ingests many regions at once
  simultaneously, not a decision made preemptively here.
