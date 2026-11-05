# Duckstring versus Riko — architectural evaluation

> Research/ADR notebook. A static review of Duckstring's documentation and source
> repository against `nerevu/riko` branch `next` at commit `ca75bf0`, kept for rationale
> and traceability, not as a task list. The gameplans it informed cite "Duckstring"
> inline: [feed-monitoring.md](../gameplans/feed-monitoring.md),
> [effects.md](../gameplans/effects.md), [events.md](../gameplans/events.md),
> [orchestration.md](../gameplans/orchestration.md),
> [database-transforms.md](../gameplans/database-transforms.md),
> [rest-incremental.md](../gameplans/rest-incremental.md), and
> [testing.md](../gameplans/testing.md). Triaged 2026-11-05.

## 1. Executive assessment

Duckstring is worth studying, but Riko should borrow its architectural principles
rather than its overall architecture.

Duckstring is a DuckDB-centered data-engineering platform. Riko is a general-purpose
Python stream-processing engine. They solve overlapping problems, but at different
layers.

Duckstring is particularly strong at organizing independently deployed transformations,
minimizing unnecessary computation, preserving consistent data products, and making
pipelines operationally observable.

Riko should remain more flexible, lightweight, and embeddable. It should not require
DuckDB, a persistent catalog, or a server to execute a workflow.

The most consequential distinction is that Duckstring's pull orchestration is not the
same as Riko's pull-based iteration:

- Riko pulls individual items through an executable pipeline, enforcing bounded
  execution and backpressure.
- Duckstring propagates demand backward through a network of persisted data products,
  deciding which transformations need to run and how fresh their results must be.

Those mechanisms are complementary. Duckstring's approach would be valuable in a future
Riko orchestration layer, without changing Riko's core execution model.

## 2. Current architectural comparison

An important correction to older Riko documentation: the current `next` branch has
already completed the clean-break transition away from `SyncPipe` and `AsyncPipe`.

Riko now has a reusable, immutable `Pipeline` definition, a `Workflow` graph, and
separate one-shot `SyncExecution` and `AsyncExecution` runtimes. That puts Riko closer
to some of Duckstring's architectural ideas than its older API suggests.

| Dimension | Duckstring | Riko `next` |
| --- | --- | --- |
| Primary abstraction | Versioned Pond, containing Ripples | Immutable `Pipeline` over a `Workflow` |
| Processing unit | Table, change set, or named object | Individual item or stream |
| Execution engine | DuckDB plus Python | Python generators, AnyIO, worker pools |
| Graph composition | Dependencies between Ponds and Ripples | Explicit nodes, edges, ports, and outputs |
| Scheduling | Downstream-driven freshness requests | Consumer-driven iteration; external orchestration planned |
| Parallelism | Independent Ripples, worker processes, cloud workers | Bounded sync/async execution |
| State | Persisted tables, changes, and run history | Execution-local state; durable state and checkpointing planned |
| Isolation | Per-Pond Python environments and processes | Library execution with explicitly owned resources |
| Data interchange | DuckDB, SQL, Arrow, Parquet | Python items; additional tabular integration planned |
| Extensibility | Python Ripples, SQL, dbt, external compute | Module registry, extension API, workflow definitions |
| Observability | Built-in catalog, lineage, run history, UI | Event sink foundation; fuller observability planned |

The key strength Riko should preserve is its separation of immutable definitions from
execution-owned state. Duckstring reinforces that direction, but its deployment and
data-management abstractions should sit above it rather than inside it.

## 3. What Riko should borrow

Ranked by architectural value and fit with the existing roadmap:

| Priority | Duckstring idea | Recommendation for Riko | Roadmap fit |
| --- | --- | --- | --- |
| High | Atomic publication and last-good results | Stage durable writes, expose completed outputs only, and advance checkpoints after successful publication | R5C writes, R6 state, cache |
| High | Separate freshness from actual change | Record when a source was checked independently of when its data changed; avoid unnecessary downstream work | REST incremental, feed monitoring |
| High | Puddles: reproducible local test inputs | Add a consistent fixture pattern for testing workflows with recorded source data and injected resources | R4C/R4D, testing |
| High | Output schema contracts and version pinning | Validate published schemas and let consumers bind to a compatible, versioned data product | R2B identity, extensibility, SQL |
| Medium | Built-in lineage and failure attribution | Derive dependency lineage from `Workflow` and execution events; distinguish original failures from blocked consumers | Events, RDP |
| Medium | Declarative SQL and incremental relational processing | Support through optional SQL adapters with pushdown and native batch representations | `riko-sql`, tabular interop |
| Later | Demand-driven scheduling | Offer consumer freshness policies in an external orchestration service | Orchestration |
| Later | Per-deployment execution environments | Isolate conflicting dependency sets when deploying independent reusable workflows | Deployment/extension ecosystem |

### A. Atomic output publication is the strongest immediate lesson

Duckstring only publishes a Pond's results after its run succeeds. A downstream
consumer sees a complete published version or the previous successful version, not
half-finished output. Its Postgres and DuckLake delivery adapters can additionally
achieve exactly-once delivery where destination writes and delivery progress share a
transaction.

Riko should enforce the equivalent at durable output boundaries, not at every item a
node yields.

Proposed Riko durable-run lifecycle:

```text
observe source and load committed state
    cursor, watermark, run identity, input version
execute bounded Pipeline
    item or batch transformations, owned resources
stage output and validate
    schema, integrity, completeness, effect policy
publish completed output; commit recovery state
    atomic within the supported storage/transaction boundary
```

This already resembles Riko's proposed `CacheNode` chunk-and-manifest publication
design. Don't build another persistence hierarchy. Reuse the existing `Target`,
`StateStore`, and artifact contracts, with tests demonstrating that interrupted runs
cannot expose completed output or advance a source checkpoint incorrectly.

The important limit: this cannot promise exactly-once behavior for arbitrary external
actions such as sending emails or making SaaS API changes. Those require their own
idempotency or reconciliation guarantees.

### B. Borrow Duckstring's freshness versus change distinction

Duckstring distinguishes a run that successfully checked the upstream source from a run
that produced changed data. Its orchestration engine can propagate freshness without
rerunning a downstream transformation when its inputs are unchanged. Its source adapters
can also use ETags, modification timestamps, or content fingerprints to avoid redundant
work.

For Riko, the useful state is conceptually:

| Information | Purpose |
| --- | --- |
| Last observed/checked | Establish when the source was inspected |
| Last changed | Establish when its contents actually changed |
| Source cursor/version | Resume extraction correctly |
| Output identity | Determine whether a durable result must be replaced |
| Snapshot completeness | Establish whether absent records can safely be treated as deletions |

This is particularly valuable for asset inventory and API reconciliation pipelines. A
daily check might observe no changes and avoid repeating an expensive downstream
calculation.

The HDX age API (`inspiration/hdx-age-api.md`) is the in-house precedent for the first
two rows: each dataset record stores `last_updated` (when the data last changed) and
`age` is the number of days between it and the update run (when the source was last
observed), so the two timestamps are already separate inputs to its freshness status.

One caution from Duckstring's implementation: its `merge_table` treats missing keys in a
supplied full snapshot as deletions. It also documents that duplicate primary keys are
not checked by that operation. Riko's SQL/record-store adapters should require an
explicit complete-snapshot contract and validate key uniqueness before destructive
reconciliation. A partial paginated REST response must never be mistaken for a complete
inventory.

### C. Borrow the testing experience, not another test runtime

Duckstring's Puddles are deterministic sample source datasets. Developers can hydrate
fixtures, execute transformations locally, inspect outputs, and test first-run versus
subsequent incremental behavior without deploying a Catchment.

Riko can achieve the same result more simply through its existing immutable definitions
and resource injection:

- Substitute recorded API responses, files, and database adapters via
  `Context`/`Resource`.
- Exercise the same `Workflow` against normal and failure fixtures.
- Cover bootstrap, unchanged source, changed source, expired cursor, retry, and
  incomplete output.
- Keep tests executable with the ordinary Python runtime rather than building a second
  workflow simulator.

This is useful for the existing connector roadmap and shouldn't become a competing
`Puddle` abstraction.

### D. Adopt versioned data products, not versioned everythings

Duckstring's ability to deploy two major Pond versions simultaneously is useful when
downstream consumers cannot migrate together. It validates published schema
compatibility and keeps the earlier version available.

For Riko, that belongs to deployed workflows and their durable outputs, not every
processor or graph node.

The current `Workflow` version describes the workflow document format. A future
deployed workflow version should describe a different concern: the compatibility of the
operation or output contract. Keep those identities separate. The gameplans already do:
R2B makes an explicit `version=` the authoritative durable semantic identity,
`extensibility.md` keeps graph ids distinct from semantic fingerprint/version identity
and `format_version` distinct from both, and `artifact-conversion.md` § 19 owns
published-output fingerprints and versions.

### E. Borrow Duckstring's pure state-machine approach

One of the better implementation details is outside its marketing material.

Duckstring separates orchestration rules in `engine/catchment.py` from much of the
persistent service implementation. Its orchestration transitions take state, apply a
deterministic event, and return updated state. That model can be tested with simulated
time and completion events.

If Riko eventually supports consumer-driven scheduling, use a similar deterministic
decision layer:

```text
current published state + requested freshness + dependency graph → required runs
```

The orchestration adapter would then schedule and persist the results. The decision
layer would not own worker pools, HTTP clients, or resource lifetimes.

This is consistent with Riko's existing orchestration gameplan.

## 4. What Riko should avoid

| Duckstring architectural choice | Why Riko shouldn't copy it |
| --- | --- |
| Catchment as scheduler, catalog, API server and runtime coordinator | Riko deliberately targets embedded execution and external orchestrator integration. Requiring a server would significantly increase its operational footprint. |
| DuckDB as the universal execution substrate | Ideal for many relational workloads, but inappropriate for arbitrary Python streams, API operations, mixed async I/O and non-tabular values. Keep it optional. |
| Z-sets and relational incremental-view maintenance in Core | Their algebra works for relational operations with durable state. It does not automatically apply to arbitrary Python processors or side effects. |
| Materializing every transformation boundary | Would defeat Riko's lightweight lazy execution and introduce extra disk, serialization and recovery requirements. Materialize only at explicit durable boundaries. |
| Per-node or per-workflow mandatory dependency environments | Useful for independently deployed services, but excessive for an embedded library. Reserve isolation for deployment boundaries that actually need it. |
| Implicit data dependencies through shared database access | Makes ordering and lineage harder to validate. Preserve Riko's explicit nodes, ports and resource contracts. |
| Built-in cloud executors and scheduling daemon | Duplicates Airflow, Prefect, Dagster, serverless and managed worker platforms. Use adapters. |

Each rejection restates a standing rule (`orchestration.md` § 2 and § 4, the
`inspiration-coverage.md` decision rules, the ROADMAP tie-breakers), so no gameplan was
changed for this table.

There is also a concrete maintainability warning. Duckstring's `catchment/driver.py` is
roughly 4,400 lines, coordinating many platform functions. Although the scheduling
state machine is separated, its surrounding service has accumulated substantial
responsibility.

Riko's enforceable package dependency layers, distinct
`definitions`/`execution`/`runtime` responsibilities, and smaller public facades are a
better foundation for the library it is trying to be.

Duckstring's recent DuckDB performance results are worth benchmarking against, but they
are not a reason to replace Riko's engine. They measure particular batch SQL and
incremental workloads, rather than the broader Python-stream and API-processing
workload Riko supports.

## 5. What to change in Riko's roadmap

Targeted refinements, not another architectural workstream. The forward order in
`implementation-sequence.md` already matches, so it was left untouched; the owning
topical gameplans took the refinements.

| When | Concrete change | Owner |
| --- | --- | --- |
| Now, during existing contract design | Specify complete-snapshot and unique-key requirements for reconciliation; distinguish source observation from content change | REST incremental / SQL connector plans |
| With write execution | Test staged publication, last-good output preservation, failure cleanup, and checkpoint ordering | R5C / R6 |
| With callable and input declarations | Establish simple, deterministic source-fixture substitution for workflow tests | R4C / R4D / testing |
| With durable state and outputs | Record source/output versions, schema fingerprints, and whether a delivered batch is full or incremental | R2B / R6 / RDP |
| With execution observability | Surface the node that failed, affected downstream nodes, input/output counts, and lineage without per-item logging overhead | Events |
| When optional SQL support lands | Benchmark DuckDB and Ibis-backed pushdown against ordinary Python execution for representative transformations | `riko-sql` / tabular interop |
| Only after durable boundaries are established | Consider demand-driven freshness as an opt-in orchestrator policy | Orchestration |

The order matters. Freshness-driven scheduling is only reliable when Riko can identify
what data was published, what changed, what state was committed, and what a downstream
consumer is allowed to reuse.

## 6. Final recommendation

Duckstring is ahead of Riko in operational data-pipeline functionality: durable
publication, incremental relational computation, deployment versioning, source
freshness, catalog access, and failure recovery.

Riko's stronger architectural position is its general-purpose composability: explicit
immutable workflow graphs, a reusable Pipeline definition, separate execution
lifetimes, native bounded async processing, and extensibility without requiring an
infrastructure platform.

The three highest-value ideas to carry forward are:

1. Completed-output publication with recovery-state correctness, strengthening work
   already planned around writes, caches and checkpoints.
2. Explicit change and freshness semantics, so incremental sources and downstream
   workflows can avoid wasted work safely.
3. Reproducible local workflow testing, borrowing the usability of Puddles without
   introducing a new execution model.

Consumer-driven orchestration is the most interesting longer-term opportunity, but it
should remain outside Core.

The architectural principle worth taking from Duckstring is that a pipeline should be
able to explain what data it used, what changed, and why work needs to run. Riko should
deliver that capability while retaining the option to execute a simple Python stream
with no database, server, or scheduler.

Sources reviewed: Duckstring's site navigation, concept pages, guides, Python/CLI/HTTP
references, implementation files and project design notes, alongside Riko's live `next`
source and current gameplans. This was a static source review, not an execution
benchmark or runtime audit.
