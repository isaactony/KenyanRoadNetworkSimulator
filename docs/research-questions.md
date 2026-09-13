# Research Questions & Resilience Metrics

This document defines *what the system needs to be able to answer* before any
schema or code is designed. Everything in `architecture.md` and
`data-model.md` exists to make these questions answerable, reproducibly, at
more than one scale.

## 1. Core questions

| # | Question | Metric family |
|---|----------|----------------|
| 1 | Which roads are most critical to network connectivity? | Criticality |
| 2 | Which areas become isolated after a road closure? | Connectivity |
| 3 | How much does average travel distance increase? | Efficiency |
| 4 | How many alternative routes exist for a given O-D pair? | Redundancy |
| 5 | Which roads have the greatest network-wide impact? | Criticality |
| 6 | Which neighborhoods are most vulnerable to road failures? | Accessibility / Connectivity |
| 7 | What happens if several major roads fail simultaneously? | Multi-edge simulation |
| 8 | Which infrastructure is disproportionately dependent on a small number of roads? | Accessibility + Criticality (compound) |

Questions 1, 5 and 8 all reduce to "criticality" but at different scopes
(edge-level, network-level, destination-level) — the data model keeps them
as separate analytical outputs (`road_criticality`, `network_metrics`,
`destination_impact`) rather than one table, because they answer different
questions for different audiences (a road authority asks #1, a planner asks
#6/#8, an emergency manager asks #7).

## 2. Metric families and why each metric is (or isn't) included

### 2.1 Connectivity — "is the graph still one graph?"

- **Number of connected components** — cheap, exact, always computed.
- **Largest connected component size (% of nodes)** — the single most
  interpretable resilience number: "after this closure, X% of intersections
  can still reach each other."
- **Isolated areas** — components other than the largest, resolved back to
  named regions/neighborhoods via spatial join, not just node counts.

These are computed with a plain BFS/union-find pass — O(V+E) — so they are
run on *every* simulation, at any scale, with no shortcuts needed.

### 2.2 Efficiency — "how much worse is it to get around?"

- **Average shortest-path distance/cost** between a sampled set of O-D pairs
  (not all-pairs at scale — see §3).
- **Network efficiency** (mean of 1/d(i,j) over node pairs, standard
  Latora–Marchiori definition) — handles disconnected pairs gracefully
  (1/∞ = 0) which plain average shortest path does not, so both are reported
  side by side: average shortest path is intuitive but undefined/skewed once
  a disruption creates unreachable pairs, network efficiency is the one that
  actually stays meaningful post-disruption.
- **Δefficiency = (efficiency_baseline − efficiency_disrupted) / efficiency_baseline**
  is the primary "how bad was this" scalar reported for every scenario.

### 2.3 Accessibility — "can people still reach the places that matter?"

Computed to a fixed set of `destinations` (hospitals, schools, markets,
transit, commercial areas — pulled from OSM `amenity`/`shop`/`highway=bus_stop`
tags, see `data-model.md`), not to arbitrary nodes:

- Travel cost from every node (or every populated area centroid) to its
  nearest destination of each category, baseline vs disrupted.
- `became_unreachable` flag when a destination drops out of a node's
  reachable set entirely (component split), reported separately from
  "got more expensive," since these mean different things operationally.

### 2.4 Criticality — "which roads matter most?"

Deliberately **not** every centrality measure available in NetworkX/igraph.
Chosen set, and why:

- **Edge betweenness centrality** — the primary ranking signal. It
  approximates "how much shortest-path traffic depends on this edge," which
  is exactly the criticality question. Expensive (effectively O(V·E) via
  Brandes' algorithm) — see §3 for how this is kept tractable at scale.
- **Bridge edges (cut edges)** — computed exactly and cheaply (Tarjan's
  bridge-finding, O(V+E)) rather than inferred. A bridge is a hard fact
  ("removing this *disconnects* the graph"), so it is never approximated,
  and is used to sanity-check/seed the betweenness ranking (bridges always
  rank at or near the top).
- **Efficiency contribution** — for the top-K candidates surfaced by
  betweenness/bridge detection, actually remove the edge and recompute
  network efficiency. This is the expensive-but-exact confirmation step:
  centrality is a *proxy*, efficiency-drop-on-removal is the *ground truth*,
  and running it exhaustively over every edge is infeasible past a few
  thousand edges, hence "rank by proxy, confirm top-K by simulation."

Explicitly **excluded**, with reasons:

- **Closeness centrality** — requires all-pairs shortest paths, is more
  expensive than betweenness for no added interpretive value here, and is a
  node-level (not edge-level) measure, so it doesn't directly answer "which
  *road*."
- **Plain degree centrality** — a poor proxy for road importance in a road
  network, where the overwhelming majority of nodes have degree 2–4
  regardless of the road's actual traffic role; it does not correlate well
  with criticality here and would be actively misleading if reported.

### 2.5 Redundancy — "how many other ways are there?"

- Number of edge-disjoint (or approximately, k-shortest) alternative paths
  between key O-D pairs, before and after disruption. Reported only for a
  curated set of O-D pairs (e.g., major destination pairs, not all-pairs) —
  see scale note below.

## 3. Scale honesty

All-pairs shortest paths and exhaustive edge betweenness are **not**
feasible to run naively at 1M+ edges on a single machine in reasonable time.
The design commits to:

- Betweenness/efficiency computed on **sampled O-D pairs** (a documented,
  seeded sample size) once graph size crosses a configured threshold, with
  the threshold and sample size recorded alongside every result so numbers
  are never silently approximate.
- Exact, unsampled computation is used for the small/dev extract, so
  correctness of the sampled approach can be validated against ground truth
  at small scale before trusting it at large scale.
- No performance or scale claim in this project's documentation states a
  number that has not actually been measured on the dataset in question
  (see `docs/architecture.md` §"On scale claims").

## 4. Experiments (reproducible, seeded, stored)

1. **Most critical roads** — rank top 100 segments by betweenness, confirm
   top-K by efficiency-contribution simulation.
2. **Random failure sweep** — remove 1/5/10/20% of segments at random;
   *multiple seeded trials per percentage* (random failure has variance —
   a single draw is not a result), report mean ± spread of efficiency drop.
3. **Targeted vs. random** — remove the same percentages, but choosing the
   highest-criticality edges first; compare the degradation curve against
   experiment 2. This is the classic "scale-free networks are robust to
   random failure but fragile to targeted attack" test, run on an actual
   road network instead of asserted from graph theory.
4. **Neighborhood vulnerability** — for each region, hold out its own roads
   and measure the region's own accessibility loss vs. the accessibility
   loss it causes elsewhere; rank regions by vulnerability, not just by
   how much damage they can cause.
5. **Emergency accessibility** — accessibility metric restricted to the
   `hospital` destination category, run against the critical-road and
   geographic-disruption scenarios specifically.

Every experiment run persists: input scenario, graph snapshot id, seed(s),
and full metric output — so "rerun experiment 2" reproduces the same numbers
byte-for-byte given the same snapshot.
