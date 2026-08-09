# Riko Data Protocol (RDP) & Connect Gameplan

> **Provenance.** Extracted from `docs/ROADMAP.md` so the roadmap stays a high-level overview. This gameplan is the authoritative detail for the RDP/Connect end-state contract — lineage/acknowledgements, the Riko Data Protocol, state, schema, batch transports, manifest durability, and the RDP/Connect implementation milestones (ROADMAP §14, §17–§21, §26). The active near-term work is tracked in [../PHASE_CHECKLISTS.md](../PHASE_CHECKLISTS.md) and [../MILESTONES.md](../MILESTONES.md). Section references like §N point back to [RUNTIME_CONTRACT.md](../RUNTIME_CONTRACT.md) (the runtime contract); the numbered `## N.` headings are preserved so those references resolve.

## 14. Lineage and acknowledgements

> **Status: Planned.** no lineage envelope, positions, or acknowledgements.

### 14.1 Position envelope

Business records remain clean. Execution metadata is carried separately:

```python
@dataclass(frozen=True)
class PositionedItem:
    value: Item
    position: Position
```

```python
@dataclass(frozen=True)
class Position:
    source_id: str
    sequence: int
    expansion_path: tuple[int, ...] = ()
```

Simple one-to-one stages use the compact position. Expanding stages append lineage paths.

### 14.2 Unordered processing

For unordered stages, the checkpoint tracker advances only the largest contiguous completed prefix.

```text
completed: 1, 2, 3, 5, 6
checkpoint: 3
```

Once 4 completes:

```text
checkpoint: 6
```

### 14.3 Flat-map lineage

Children inherit the parent lineage through an expansion path.

A zero-output `flat_map` applies the configured `drop_policy`.

### 14.4 Reducer lineage

Ordinary reducers use conservative lineage: all consumed positions remain pending until every output is durable.

Advanced reducers may return:

```python
@dataclass(frozen=True)
class ReducerOutput:
    value: Item
    lineage: Lineage
```

or:

```python
@dataclass(frozen=True)
class ReducerDisposition:
    lineage: Lineage
    disposition: Literal[
        "dropped",
        "dead_lettered",
    ]
```

Validation requires:

```text
declared lineage ⊆ consumed lineage
consumed lineage ⊆ output lineage ∪ disposition lineage
```

Every consumed position must appear in at least one output lineage or explicit disposition. Fabricated and orphaned positions are lineage errors.

#### Overlapping lineage

When one source position contributes to multiple outputs, it completes only after every dependent output is durable.

#### Lineage commit

```python
lineage_commit: Literal[
    "on_complete",
    "per_output",
] = "per_output"
```

**Per output** — each durable output may advance its independent lineage immediately.

**On complete** — no consumed lineage advances until the reducer invocation finishes successfully and all outputs are durable.

### 14.5 Reducer lineage representation

Use compact contiguous ranges by source:

```python
@dataclass(frozen=True)
class SourceRange:
    source_id: str
    start: int
    end: int
```

Sparse exceptions may be stored separately.

### 14.6 Joins

Built-in joins track exact left/right lineage.

Custom joins use conservative whole-stage lineage unless they explicitly return finer-grained lineage.

Unmatched behavior is explicit:

```python
unmatched_policy: Literal[
    "complete",
    "external",
    "error",
]
```

Defaults depend on join type.

---

## 17. Riko Data Protocol

> **Status: Planned.** no RDP protocol/enums/plan types in code.

### 17.1 Compatibility position

RDP is an input superset of Singer and defines a strict Singer-compatible profile.

Every valid Singer stream is accepted by RDP.

Native RDP extensions are enabled only through a resolved execution plan and may require RDP-aware actors or explicit compatibility projections.

### 17.2 Profiles

**Singer-compatible profile** supports:

* `SCHEMA`
* `RECORD`
* `STATE`

**Native RDP profile** may additionally support:

* `BATCH`
* `SCHEMA_CHANGE`
* `ACTIVATE_VERSION`
* typed stream/global/legacy state
* manifests
* checkpoint metadata
* operation metadata

### 17.3 Unknown capabilities

* unknown required capability → fail
* unknown optional capability → ignore or warn

### 17.4 Safe degradation

* performance difference → automatic fallback
* representation difference → explicit projection
* correctness difference → fail unless explicitly authorized

### 17.5 Execution plan

There is one resolved execution plan with actor-specific projections.

The plan records:

* protocol profile
* Opts
* Opts overrides
* schema capabilities
* state behavior
* transport
* batch ownership
* retry policies
* error policies
* compatibility projections
* warnings
* run ID
* plan version

---

## 18. State

> **Status: Planned.** no state store / `Checkpoint`.

### 18.1 State types

Support typed:

* stream state
* global state
* legacy opaque state

Source state remains authoritative and opaque to the runtime except where typed state semantics are explicitly defined.

### 18.2 State store

The state store supports:

* compare-and-swap
* optional exclusive lease
* atomic file backend initially
* SQLite as the first structured backend

### 18.3 Checkpoint

```python
@dataclass(frozen=True)
class Checkpoint:
    run_id: str
    plan_version: int
    source_states: Mapping[str, object]
    acknowledged_positions: Mapping[str, int]
    stage_states: Mapping[str, object]
    schema_versions: Mapping[str, str]
```

Commit sequence:

```text
write output
→ sink acknowledgement
→ checkpoint CAS
```

A crash after output acknowledgement but before CAS causes replay. Stable batch IDs allow idempotent sinks to deduplicate that replay. No general two-phase commit is required.

---

## 19. Schema

> **Status: Planned.** no `RikoSchema` / registry.

### 19.1 Canonical representation

The original Draft-07 JSON Schema remains authoritative.

Riko stores:

* original unresolved schema
* immutable execution-time registry
* cached resolved view
* typed tabular projection
* unsupported-feature metadata
* lossiness metadata

```python
@dataclass(frozen=True)
class RikoSchema:
    source: Mapping[str, object] | bool
    registry: SchemaRegistry
    tabular: TabularSchema | None
    unsupported_features: frozenset[str]
    projection_is_lossy: bool
```

`python-jsonschema` validates the raw schema and handles references. It does not replace the typed Riko tabular projection.

### 19.2 Compatibility matrix

| Change                   | Default              |
| ------------------------ | -------------------- |
| add optional property    | compatible           |
| add required property    | incompatible         |
| integer → number         | compatible widening  |
| number → integer         | incompatible         |
| add null                 | compatible widening  |
| remove null              | incompatible         |
| remove property          | incompatible         |
| rename property          | remove plus add      |
| widen enum               | compatible           |
| narrow enum              | incompatible         |
| array element change     | recursive comparison |
| nested object change     | recursive comparison |
| unsupported or uncertain | incompatible         |

### 19.3 Schema evolution

Native profile:

```text
SCHEMA v1
BATCH schema_id=v1
SCHEMA_CHANGE v1→v2
SCHEMA v2
BATCH schema_id=v2
```

Every batch carries `schema_id`.

Fixed-schema batch pipelines freeze the initial schema and reject later widening.

---

## 20. Batch transports

> **Status: Planned.** no batch-transport selection.

```python
batch_transport: Literal[
    "manifest",
    "ipc-stream",
    "auto",
]
```

### 20.1 Manifest

General Native RDP transport.

Use for:

* incremental runs
* CDC
* checkpointed execution
* schema evolution
* object storage
* multi-stream execution

### 20.2 IPC stream

Restricted fast path.

Allowed only for:

* one logical stream
* full-table execution
* stable fixed schema
* no CDC
* no intermediate checkpoints

Schema drift terminates the run. The transport never switches after execution begins.

### 20.3 Auto

The planner selects IPC only when every restriction is satisfied. Otherwise, it selects manifests.

---

## 21. Manifest durability

> **Status: Planned.** no `Manifest` / commit protocol.

The manifest is the commit marker.

Commit sequence:

```text
1. Write immutable data object
2. Verify checksum and size
3. Atomically publish manifest
4. Sink acknowledges manifest
5. Checkpoint advances
```

Manifest fields include:

```python
Manifest(
    run_id=...,
    stream_id=...,
    batch_id=...,
    schema_id=...,
    object_uri=...,
    record_count=...,
    size_bytes=...,
    checksum=...,
    lineage=...,
)
```

Use run-scoped immutable object names initially. Objects without committed manifests are orphans. Cleanup is best-effort and does not affect correctness.

---

## 26. Implementation roadmap

The architectural milestones below describe the eventual RDP/Connect end state. The
**HigherGov-first critical path** in [highergov-feed.md](highergov-feed.md)
is the order in which this work is actually delivered: RDP remains the eventual
architecture, but it no longer blocks Riko's first production use.

### Milestone 0 — Protocol and execution contracts

Deliver before major runtime work:

* RDP specification
* Singer-compatible profile
* Native profile
* execution-plan schema
* capability negotiation
* error/disposition contracts
* schema model
* state and checkpoint model
* transport selection rules
* batch ownership rules

### Milestone 1 — Runtime correctness

* fix falsey `initial` handling in async and cooperative reductions
* correct async ordering documentation and behavior
* add bounded task submission
* add bounded reorder buffering
* add cancellation and cleanup
* add explicit error policies
* add aggregate stage counters
* preserve current sync behavior

### Milestone 2 — Callable stages and Opts

* add `map`
* add `flat_map`
* add strict inheritance
* add new options
    - extend Opts with execution characteristics
    - declare defaults in each pipe module
    - allow ordinary pipe kwargs to override defaults
    - include declared and resolved Opts in execution plans
* add execution-plan provenance

### Milestone 3 — Lazy Feed runtime

* define `Feed`
* widen `AsyncSource`
* normalize to one async iterator per execution
* remove `_await_stream()` from internal chaining
* adapt `AsyncCollection.async_pipe()`
* convert composer operators to lazy Feed processing
* add compatibility materialization adapters for legacy modules
* mark materializing stages in execution plans

### Milestone 4 — Async concurrency

* AnyIO task groups
* bounded channels
* ordered and unordered map
* fair and ready merge scheduling
* concurrent cleanup
* worker cancellation
* source-specific sequence tracking
* dependency-group barriers

### Milestone 5 — Disposition and lineage runtime

* positioned envelopes
* contiguous acknowledgement tracking
* drop policies
* disposition sink
* dead-letter acknowledgement
* reducer lineage
* advanced reducer output protocol
* join lineage
* checkpoint barriers

### Milestone 6 — Schema and batches

* raw Draft-07 schema storage
* immutable registry
* resolved schema view
* tabular projection
* compatibility matrix
* logical Batch
* batch policy
* schema-change handling
* fixed-schema rejection

### Milestone 7 — State and manifests

* atomic-file state store
* CAS
* leases
* SQLite state store
* manifest object writer
* checksum verification
* manifest commit marker
* orphan cleanup
* stable batch IDs

### Milestone 8 — RDP Connect runtime

* Singer reader and writer
* configured Riko catalog
* Singer adapters
* source and destination actor projections
* presets backed by orthogonal load/delete modes
* CDC fallback
* merge dependency groups
* partial status
* CLI exit codes

### Milestone 9 — Fast paths and optimization

* direct Arrow IPC restricted path
* automatic transport planning
* Arrow/Parquet batch execution
* byte-aware buffers
* sync bounded pool submission
* optimized dataframe execution
* benchmarks

### Milestone 10 — Compatibility cleanup

* ~~review / remove Twisted~~ — **done** (no Twisted anywhere; the runtime is AnyIO-only)
* **swap the ``mezmorize`` memoization dependency** — ``mezmorize.memoize`` + ``get_cache_type``
  are used only in ``riko/_io.py::get_opener`` (memoized URL/file fetch). Replace with a
  stdlib/dependency-free cache. Optional modernization (not legacy cleanup); the Flask concern is
  moot (current ``mezmorize`` depends on ``cachelib``, not Flask). Also drops the ``manage``
  console-script collision with ``mezmorize`` (see root ``CLAUDE.md``).
* add entry-point plugin discovery if needed
* upstream temporary Meza adapters
* remove compatibility materialization stages where possible

---


---

> **Salvaged from the retired `productionizing.md` §8.** Draft RDP wire specification (intended as `docs/RDP.md`). RDP is beyond P14, so the P-track does not own it.

# RDP specification (draft, salvaged)

## 8.1 Add `docs/RDP.md`

Use one authoritative specification file initially.

Do not split it into many documents until the wire protocol stabilizes.

Required sections:

### 1. Scope

Define RDP as:

* an input superset of Singer;
* a strict Singer-compatible profile;
* a native profile for batches, manifests, schema changes, and richer state.

### 2. Message framing

Define JSONL framing and required `type` discrimination.

Singer-compatible messages:

```text
SCHEMA
RECORD
STATE
```

Native messages:

```text
BATCH
SCHEMA_CHANGE
ACTIVATE_VERSION
```

### 3. Catalog

Specify:

```text
ConfiguredRikoCatalog
```

as canonical, with Singer catalog adapters.

### 4. Schema

State:

* Draft-07 is authoritative;
* the original unresolved schema is retained;
* references resolve through an immutable registry;
* tabular projections may be lossy;
* projection loss must be reported.

### 5. State

Define:

* `STREAM`
* `GLOBAL`
* `LEGACY`

State values remain source-authoritative.

Singer `STATE.value` must be preserved exactly.

### 6. Capabilities

Define required and optional capabilities.

* unknown required capability → fail
* unknown optional capability → ignore or warn

### 7. Batches and manifests

Specify:

* logical batch envelope;
* schema ID;
* lineage envelope;
* manifest commit sequence;
* stable batch ID;
* object checksum and size.

### 8. Transport

Define:

```text
manifest
ipc-stream
auto
```

with the restricted direct IPC fast path.

### 9. CDC

Specify:

* insert
* update
* delete
* delete projection rules
* native versus Singer compatibility behavior

### 10. Delivery guarantee

State that Riko Connect is at-least-once by default.

Do not claim global exactly-once behavior.

### 11. Safe degradation

Codify:

```text
performance difference
→ automatic fallback

representation difference
→ explicit projection

correctness difference
→ fail unless explicitly authorized
```

### 12. Run status

Define:

```text
COMPLETED
PARTIAL
FAILED
CANCELLED
```

and CLI exit codes:

```text
0 completed
1 failed
2 usage/configuration
3 partial
```

### 13. Conformance examples

Include examples for:

* Singer schema/record/state
* native batch
* schema change
* stream state
* global state
* delete record
* manifest acknowledgement
* unsupported required capability

## 8.2 Add examples after prose stabilizes

Later add:

```text
docs/rdp/examples/singer.jsonl
docs/rdp/examples/native-batch.jsonl
docs/rdp/examples/schema-change.jsonl
docs/rdp/examples/cdc.jsonl
```

## 8.3 Add machine-readable schemas later

After at least one reader and writer implementation agree:

```text
docs/rdp/schema/message.schema.json
docs/rdp/schema/catalog.schema.json
docs/rdp/schema/manifest.schema.json
docs/rdp/schema/checkpoint.schema.json
```

Do not make machine-readable protocol schemas the first deliverable. Otherwise the project will encode unsettled details too early.

---


---

> **Runtime-contract section extracted from RUNTIME_CONTRACT §27** (initial-implementation non-goals; pairs with §26 above). `§N` refs point to [RUNTIME_CONTRACT.md](../RUNTIME_CONTRACT.md).

## 27. Explicit non-goals for the initial implementation

The first implementation does not require:

* global exactly-once delivery
* two-phase commit
* dynamic top-level merge registration
* universal byte-perfect memory measurement
* full custom JSON Schema AST
* automatic source-type detection everywhere
* full Twisted and AnyIO feature parity
* automatic transport switching during a run
* generic `Pipe[T, U]`
* automatic Feed restartability
* process serialization of arbitrary runtime objects
* persistent stage state without an explicit codec
