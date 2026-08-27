# RDP & Connect gameplan

> **Provenance.** Extracted from the roadmap as the RDP/Connect end-state plan. This file owns
> the protocol/schema/manifest/actor projection in ROADMAP §14 and §17–§21 plus the RDP-specific
> implementation roadmap/non-goals (§26–§27).
>
> **Ownership correction.** Generic Pipeline execution, per-item provenance, canonical identity,
> idempotency, `FeedState` / `StateKey` / `StateRecord` / `StateStore`, checkpoint ownership/CAS,
> and Pipeline batch semantics are owned by
> [execution-semantics.md](execution-semantics.md). RDP projects those contracts onto an
> interoperable protocol; it does not define competing runtime state/lineage/batch abstractions.

## 14. Lineage and acknowledgements

> **Current gap:** there is no durable cross-process RDP acknowledgement/lineage protocol yet.

### 14.1 Core provenance source

Business records remain clean. Core execution tracks item provenance privately through the
canonical item wrapper/identity model from `execution-semantics.md`:

```text
source node namespace
item_key
generation
contributor identity where combined
stateful owner / checkpoint boundary where relevant
```

RDP serialization may project that provenance into transport-visible lineage metadata when a
remote actor needs it. It must not introduce a second authoritative `Position(sequence,
expansion_path)` identity system.

A generated source-node id is sufficient inside one compiled definition; explicit node ids are
used when identity must survive structural revisions.

### 14.2 Unordered completion

Unordered execution may complete items out of order, but durable progress is governed by the
stateful owner's valid recovery frontier and CAS state rather than a universal contiguous integer
sequence.

A source/protocol that genuinely has ordered offsets may project its native offset into the
source's `FeedState` checkpoint payload. That is source-specific state, not the universal Riko
item identity.

### 14.3 Expansion and combination

RDP lineage follows the common generation rules:

```text
1 -> 1   preserve when truthful
1 -> N   deterministically derive child generation
N -> 1   combine exact contributor generations + operator/group identity
N -> N   derive from the exact contributors for each output
```

Semantic child identity is preferred to position; positional fallback is valid only with a
stable semantic ordering guarantee.

Reducers/joins that combine inputs therefore project exact contributor provenance when it is
required for downstream acknowledgement/inspection. `union()` preserves each input item's
provenance and does not combine identities merely because streams reconverge.

### 14.4 Acknowledgement and disposition

A remote sink/actor acknowledgement is one kind of successful required handoff. The generic
ordering remains:

```text
perform required durable side effect
-> receive destination acknowledgement when the protocol has one
-> advance the owning recovery/source state by CAS
```

Failure/disposition rules are owned by `execution-semantics.md`. A dead-letter or external
disposition advances state only after the required sink acknowledges it. A filtered item under
the normal completion-style drop policy may be considered intentionally disposed.

No generic exactly-once claim follows from RDP acknowledgements. Stable execution-derived
idempotency keys are used where the destination genuinely supports them.

---

## 17. Riko Data Protocol

> **Current gap:** no RDP protocol/enums/plan types ship yet.

### 17.1 Compatibility position

RDP is an input superset of Singer and defines a strict Singer-compatible profile.

Singer-compatible profile:

```text
SCHEMA
RECORD
STATE
```

Native RDP may add:

```text
BATCH
SCHEMA_CHANGE
ACTIVATE_VERSION
typed stream/global/legacy state projections
manifest references
checkpoint/provenance metadata
operation metadata
```

Unknown required capability -> fail. Unknown optional capability -> ignore/warn according to
resolved policy. Performance-only differences may fall back automatically; representation
changes require an explicit projection; correctness changes fail unless explicitly authorized.

### 17.2 Resolved protocol plan

RDP may compile an actor-specific protocol projection containing:

```text
protocol profile
resolved Pipeline semantic characteristics
schema capabilities
state projection behavior
transport / representation
retry/disposition policy references
compatibility projections
warnings
run id / plan version
```

This is not a second Riko execution object. The ordinary Pipeline definition and private
SyncExecution/AsyncExecution remain the runtime owners.

---

## 18. State

> **Core owner:** [execution-semantics.md](execution-semantics.md#stateful-execution-and-checkpoints).

RDP does **not** define a generic `Checkpoint` dataclass or a separate lease-capable state store.
It serializes/projects the common semantic state model:

```python
FeedState[T]
StateKey[T]
StateRecord[T]
StateStore / AsyncStateStore
```

All core mutations are CAS-only. `CheckpointConflictError` propagates; Riko does not automatically
reload/rerun a conflicting operation. Generic leases/locks are not part of the core state
contract.

### 18.1 RDP state categories

Protocol messages may distinguish transport-level categories such as:

```text
stream state
global state
legacy opaque state
```

but each category is a serialization/projection of a source/stateful-owner payload rather than a
parallel persistence API. Source-specific opaque state remains opaque to Riko except for the
owner-defined semantics needed for resume.

### 18.2 Physical serialization

The configured `StateStore` owns physical state serialization. Store instances expose:

```python
store.capabilities
store.validate_state(state)
```

RDP may validate that protocol-specific payloads are persistable, but does not prescribe one
universal Python state codec.

### 18.3 Commit ordering

For a required durable RDP handoff:

```text
write/publish durable output
-> destination acknowledgement (if applicable)
-> StateStore CAS commit at the valid owner boundary
```

A crash after an idempotent output succeeds but before the state CAS may replay that work. The same
execution-derived idempotency key/generation is reused; exactly-once is not claimed generically.

---

## 19. Schema

> **Current gap:** no `RikoSchema` / registry ships yet.

The original JSON Schema remains authoritative. A future RDP schema model may retain:

```python
@dataclass(frozen=True)
class RikoSchema:
    source: Mapping[str, object] | bool
    registry: SchemaRegistry
    tabular: TabularSchema | None
    unsupported_features: frozenset[str]
    projection_is_lossy: bool
```

The schema subsystem stores the unresolved source, immutable execution-time registry, cached
resolved view, typed tabular projection, unsupported-feature metadata, and lossiness metadata.

Compatibility remains conservative: optional additions/widening may be compatible; required
additions, narrowing/removal, or uncertain unsupported changes are incompatible unless an explicit
policy says otherwise.

Native profile schema evolution may be represented as:

```text
SCHEMA v1
BATCH schema_id=v1
SCHEMA_CHANGE v1 -> v2
SCHEMA v2
BATCH schema_id=v2
```

Fixed-schema consumers reject incompatible drift rather than silently switching semantics.

---

## 20. Batch transports

> **Core batch owner:** `execution-semantics.md` / `tabular-interop.md`.

RDP transport selection is distinct from the logical Pipeline batch mode. A Pipeline batch is an
ordinary value whose in-memory representation is negotiated using the common capability order.
RDP decides how such values cross a durable/process boundary.

Possible RDP transports:

```python
batch_transport: Literal["manifest", "ipc-stream", "auto"]
```

### Manifest

Use for incremental/CDC/checkpointed/schema-evolving/object-store/multi-stream execution.

### IPC stream

A restricted fast path for one logical stream, full-table/fixed-schema execution with no
intermediate durable recovery boundary requiring manifests. Schema drift terminates rather than
silently switching transport.

### Auto

Select IPC only when every correctness restriction holds; otherwise use manifests.

The transport selection does not create a `BatchPipe`, `BatchPolicy`, or alternate map semantics.

---

## 21. Manifest durability

A manifest is an RDP durable-object commit marker, not the generic Riko checkpoint record.

Typical publication sequence:

```text
1. write immutable data object
2. verify checksum/size
3. atomically publish manifest
4. destination acknowledges manifest
5. owning source/recovery state advances by StateStore CAS
```

A manifest may contain:

```text
run_id
stream_id
batch_id
schema_id
object_uri
record_count
size_bytes
checksum
projected provenance/lineage metadata
```

Use run-scoped immutable object names initially. Objects without committed manifests are orphans;
best-effort cleanup does not determine correctness.

Artifact/manifest content hashes are content identities and are distinct from the common canonical
semantic identity/fingerprint digest unless explicitly defined otherwise.

---

## 26. Implementation roadmap

The P-track remains authoritative for current phase status. This RDP sequence describes only the
protocol/Connect work that remains after or alongside the core runtime contracts.

### R0 — Protocol projection contracts

* Singer-compatible and Native RDP profiles;
* actor capability negotiation;
* state/provenance projection from core `FeedState` / `_FeedItem` semantics;
* schema model;
* transport-selection rules;
* manifest protocol.

### R1 — Core prerequisites (owned elsewhere)

Consume rather than duplicate:

* immutable `Pipeline` + private executions;
* common Context/Resource lifecycle;
* canonical identity/generation/idempotency;
* `FeedResult` / `FeedState` / `StateStore` CAS;
* explicit checkpoints/stateful owners;
* bounded async execution/fan-out;
* Pipeline batch mode/backend negotiation;
* retry/error/disposition policy.

### R2 — Schema projection

* raw schema storage/registry/resolution;
* compatibility checks;
* tabular projection;
* schema-change protocol events.

### R3 — Manifest transport

* immutable object writer;
* checksum verification;
* manifest commit marker;
* orphan cleanup;
* stable protocol batch/artifact IDs tied to semantic provenance/idempotency where applicable.

### R4 — Connect actors

* Singer reader/writer;
* configured catalog;
* source/destination actor projections;
* compatibility profiles/fallback;
* partial run result integration.

### R5 — Fast paths and optimization

* restricted Arrow IPC path;
* automatic safe transport planning;
* Arrow/Parquet representation optimization;
* byte-aware buffers/benchmarks.

### R6 — Compatibility cleanup

* remove legacy whole-source/materialization bridges where Feed-native ports permit;
* upstream/finalize temporary conversion adapters;
* keep plugin discovery behind the common module registry.

---

## 27. Explicit non-goals for the initial implementation

The first RDP/Connect implementation does not require:

* generic/global exactly-once delivery;
* two-phase commit;
* a second generic state/checkpoint/lease system;
* a second item lineage/position identity system;
* a second public batch Pipeline type or BatchPolicy;
* dynamic top-level merge registration;
* universal byte-perfect deep-object memory measurement;
* a full custom JSON Schema AST;
* automatic source-type detection everywhere;
* automatic transport switching during a run;
* arbitrary runtime-object process serialization;
* automatic Feed/source restartability;
* protocol-specific retries that duplicate the core `RetryPolicy`.

RDP/Connect should remain a projection/integration layer over the core Pipeline execution contracts,
not a competing runtime.
