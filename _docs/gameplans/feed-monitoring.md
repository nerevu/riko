# Feed monitoring gameplan

## 1. Mission

Add first-class primitives for repeatedly observing finite sources and consuming resumable
change feeds while emitting useful new, changed, deleted, threshold, or anomaly events
without turning Riko into a scheduler, daemon, or workflow orchestrator.

Target shape:

```text
observe finite source or resumable change feed
→ identify new / changed / deleted records
→ evaluate threshold/change/anomaly rules
→ explicit fan-out of interesting events
→ commit observation/source state through StateStore
→ repeat or resume
```

This plan owns **recurring source observation, resumable change-feed semantics, and
monitoring policy**. It does not define a second persistence/checkpoint abstraction.

Related authoritative plans:

* `execution-semantics.md` — `Pipeline`, `FeedResult`, `FeedState`, `StateStore`, checkpoints,
  identity/generation, retry, timeout, cancellation, error/disposition policy;
* `orchestration.md` — deployment schedules, durable run boundaries, external workers;
* `rest-incremental.md` — REST cursor extraction/encoding and source-side filter pushdown;
* `provider-integrations.md` — `OperationHandle` and waiting for an already-started provider
  operation;
* `fanout-topology.md` — delivery/fan-out topology;
* `connectors.md` — source/sink transport and credential lifecycle.

## 2. Inspiration integrated by this plan

Relevant precedents:

* **Chakula** — RSS `tail -f`, interval, bounded iteration count, initial/backfill control,
  persisted cache, uniqueness, time lower bounds, explicit failure behavior;
* **email-sub-api** — feed-monitor process with file/Redis state and notification action;
* **AMS** — named threshold rules, enable/disable/restore, firing history;
* **Meetup** — new-versus-changed detection and dry-run;
* **CKAN tooling** — change fingerprints used to avoid unnecessary remote writes;
* **Huginn / Streamz / Bytewax / dlt** — periodic sources, source-position state, windows,
  and explicit incremental cursors;
* **resumable database/API change feeds** — opaque resume positions, explicit deletion
  tombstones, replay-tolerant consumption, and declared history/ordering guarantees.

These are design inputs, not compatibility targets. Do not copy provider-specific endpoint
shapes, revision models, pickle state files, platform-specific notification systems, or a
permanent scheduler into core.

## 3. Ownership boundary

Keep these concepts distinct:

```text
source observation cadence
    when should another finite source observation occur?

source position
    where should acquisition resume?

change-feed semantics
    what does one source-emitted change mean and what history/order/replay guarantees exist?

observation history
    which logical entities were seen and what values were previously observed?

analysis
    is this a change/anomaly/threshold event?

alert state
    did a rule already fire, transition, or enter cooldown?
```

All persisted forms use the common `FeedState[T]` / `StateStore` infrastructure; the
logical payload type and stateful owner distinguish source position, monitoring history,
and alert state.

This plan does **not** own generic provider-operation waiting:

```text
feed monitoring / change feed
    observe or resume a data source and emit records/changes

provider operation wait
    track one OperationHandle until terminal status
```

The latter belongs to `provider-integrations.md`.

## 4. Non-goals

Do not add to core:

* a cron parser or durable scheduler daemon;
* distributed worker ownership/leases;
* exactly-once delivery claims;
* mandatory Redis/database dependencies;
* a monitoring dashboard;
* a general complex-event-processing engine;
* ML anomaly models;
* provider-specific notification clients;
* provider-specific revision-tree/change-feed models;
* another generic retry, checkpoint store, state store, or operation-wait implementation.

## 5. M0 — finite observation contract

One observation is bounded and returns a rich result:

```python
result: FeedResult[AsyncIterable[Item]] = await poll_once(source, context)
```

The result exposes items, source metadata, and optional `FeedState`. Finite source resources
close on exhaustion, error, cancellation, or explicit early close.

For finite results, final source state becomes committable only after `result.items`
completes successfully. A downstream failure before that point must not commit final source
position.

A recurring monitor composes those observations:

```text
load owner state from StateStore
→ poll once
→ process records
→ successful required handoff
→ CAS-commit observation/source state
→ cancellation-aware recurrence delay
→ repeat
```

The same finite observation can be invoked by an in-process service, cron, an orchestrator
sensor, or an agent worker.

A resumable change-feed source may instead keep emitting changes during one source
iteration. It still uses the same `FeedState` / `StateStore` commit rule and does not create
a second state model.

## 6. M1 — periodic source and bounded iterations

Applications that own a long-lived process use the common polling vocabulary:

```python
flow = Pipeline.poll(source, interval=60)
```

A subscription can use the same concept:

```python
flow = subscription.poll(interval=5)
```

A finite iteration limit may be exposed for deterministic tests/CLI without defining an
`AsyncPipe.poll`-only API.

Requirements:

* cancellation-aware delay;
* no private event loop;
* fixed-delay cadence initially;
* known unboundedness when recurrence is unlimited;
* deterministic bounded iteration for tests/CLI;
* clean close on cancellation;
* retries **within one observation attempt** use `RetryPolicy` from
  `execution-semantics.md`.

`interval` controls recurrence between completed observations; it is not a retry policy.
The same `Pipeline` definition remains executable in sync or async mode through the common
execution bridge.

Change-feed delivery cadence is source-specific. A source that can wait for changes does not
need an artificial fixed polling interval merely to fit this API.

## 7. M2 — bootstrap and backfill policy

First observation behavior is explicit:

```python
bootstrap: Literal["all", "latest", "none", "count"] = "all"
bootstrap_count: int | None = None
```

Semantics:

```text
all      emit all current items, then establish state
latest   emit only newest current item
none     establish state without emitting current items
count    emit newest N current items
```

Sources with meaningful timestamps may also accept a lower bound such as:

```python
after = "2026-08-01T00:00:00Z"
```

Source-specific timestamp/cursor interpretation remains inside the source/connector.

Change feeds may additionally expose a source-defined "current position" bootstrap that
establishes state without replaying prior changes. The source owns how that position is
obtained; the shared `FeedState` / `StateStore` lifecycle owns when it becomes committed.

## 8. M3 — source position is a FeedState payload

The previous standalone `SourceCheckpoint` type is superseded by the shared state model.
Source position answers **where should acquisition resume?**, but the source owns the
payload semantics:

```python
@dataclass(frozen=True)
class FeedState[T]:
    checkpoint: T | MissingType = MISSING
    observation: Metadata | None = None
```

Representative checkpoint payloads:

```text
RSS/Atom    item id/guid + publication position
REST API    timestamp/id/continuation cursor
change feed opaque source-issued resume token
IMAP        UIDVALIDITY + UID
Kafka       partition offsets
file tail   file identity + byte offset
```

A source may use an owner-level `StateKey[T]` (`item_key=None`, `generation=None`) for
intrinsic source progress. Explicit incremental recovery boundaries use `.checkpoint()` and
the enclosing stateful owner's identity rules from `execution-semantics.md`.

An opaque cursor is treated as an uninterpreted source token. When a checkpoint payload is
opaque, generic monitoring/state code must:

* serialize and persist it through `FeedState` / `StateStore` without semantic
  transformation;
* return it to the same source contract when resuming;
* never increment it;
* never numerically or lexicographically compare it;
* never infer ordering from its textual/JSON representation.

A source adapter may understand its own cursor format, but that knowledge does not leak into
generic state logic.

## 9. M3a — resumable change-feed contract

A change feed is a source that emits source-observed changes together with a resumable
position. It is not assumed to be a complete event log. Its resume position is an ordinary
`FeedState` checkpoint payload; this section adds the change envelope and semantics, not a
second state model.

Use a provider-neutral envelope:

```python
@dataclass(frozen=True, slots=True, kw_only=True)
class Change:
    entity_id: JsonValue
    cursor: JsonValue
    version: JsonValue | None = None
    operation: Literal["upsert", "delete"] = "upsert"
    record: Item | None = None
    metadata: Mapping[str, JsonValue] = field(default_factory=dict)
```

Field meanings:

```text
entity_id
    stable identity of the logical entity

cursor
    source position associated with this observation/change

version
    source-issued change/version identity when available

operation
    upsert or delete/tombstone

record
    current/associated entity value when the source provides or the plan requests it

metadata
    source-specific non-secret details, namespaced by the adapter
```

`version` is optional because some sources expose only an entity identity and resume cursor.
When a source exposes a stable version/revision/event identifier, that value should be
preserved rather than synthesized from mutable record content.

### 9.1 Change-feed semantics

Every reusable change-feed adapter declares semantic guarantees:

```python
@dataclass(frozen=True, slots=True, kw_only=True)
class ChangeFeedSemantics:
    history: Literal["event_log", "latest_state", "snapshot_delta"]
    ordering: Literal["total", "partial", "none"]
    replay: Literal["possible", "not_expected"]
    deletion: Literal["tombstone", "absent", "unsupported"]
    payload: Literal["reference", "inline"]
```

Definitions:

```text
event_log
    source intends to expose each committed event/change in sequence

latest_state
    source reports that an entity changed, but intermediate states may be collapsed

snapshot_delta
    changes are derived by comparing observations/snapshots rather than a source event log

total ordering
    source contract defines one total order for emitted changes

partial ordering
    some order exists but consumers cannot rely on a global order across all observations

none
    no meaningful cross-record ordering guarantee

replay possible
    a previously emitted logical change may appear again after resume/retry/failover

tombstone
    source can explicitly represent deletion

absent
    deletion is inferred from snapshot membership and is not emitted directly

reference
    notification carries identity/version metadata; hydration is a separate read

inline
    notification carries the associated/current record value
```

These declarations are source characteristics, not promises manufactured by Riko. A
connector may expose stricter guarantees only when the upstream source actually provides
them.

### 9.2 Change identity versus entity identity

Keep two identities separate:

```text
entity identity
    identifies the logical thing over time
    example: customer-42

change identity
    identifies one source-observed version/change of that entity
    example: (customer-42, version-17)
```

When a stable `version` exists, the default logical change identity is `(entity_id,
version)`. If no stable version exists, an adapter may expose a source-native event ID in
metadata or the application must configure a dedupe key appropriate to that source.

Do not use `entity_id` alone for change-feed dedupe when multiple versions of the entity are
expected.

### 9.3 Tombstones

Deletion is a first-class change when the source can provide it:

```python
Change(
    entity_id="customer-42",
    cursor=cursor,
    version=version,
    operation="delete",
    record=None,
)
```

Downstream policy may ignore, archive, propagate, alert on, or materialize the deletion. The
monitoring layer must not silently convert an explicit tombstone into ordinary absence.

Snapshot sources that cannot emit tombstones may still derive deletions through completed
snapshot comparison; those feeds declare `deletion="absent"`.

### 9.4 Replay and idempotency

A committed checkpoint does not imply exactly-once delivery. Sources may replay a prior
change after retries, source failover, overlap windows, or resume behavior.

Therefore:

```text
committed FeedState
    where acquisition resumes

dedupe
    whether this logical change identity has already been processed

sink idempotency
    whether replaying downstream side effects is safe
```

These remain separate contracts. A source with `replay="possible"` should make that fact
visible in plan/introspection metadata so planners and operators can require dedupe or
idempotent sinks where appropriate. Sink idempotency reuses the execution-derived
idempotency key from `execution-semantics.md`.

### 9.5 Notification versus hydration

A change feed may emit lightweight references or inline records. Do not require every
notification to carry a full entity body.

```text
reference change
→ audit/route directly
→ optionally hydrate current entity
→ transform/enrich

inline change
→ transform/enrich directly
```

Hydration is an ordinary connector/source capability and may fail independently of receiving
the change notification. Its retry/caching behavior follows the normal connector/runtime
contracts.

## 10. M4 — one StateStore, heterogeneous state

Do not define separate `CheckpointStore` and monitoring `StateStore` protocols. One
non-generic store holds heterogeneous typed records through phantom-generic keys:

```python
class StateStore(Protocol):
    def load[T](self, key: StateKey[T]) -> StateRecord[T] | None: ...
    def save[T](
        self,
        key: StateKey[T],
        state: FeedState[T],
        *,
        boundary_id: str | None = None,
        expected_version: StateVersion | MissingType = MISSING,
    ) -> StateVersion: ...
    def delete[T](
        self, key: StateKey[T], *, expected_version: StateVersion
    ) -> None: ...
```

`AsyncStateStore` uses the same method names with awaitable operations. Execution resolves
one mode-specific adapter per run.

Initial implementations may be memory and file/SQLite stores; optional packages may
provide Redis, databases, or object storage. Backend physical serialization is backend-owned.
Configured stores expose coarse `StateStoreCapabilities` plus `validate_state(state)` so
monitoring payload compatibility can be checked without a second codec/type registry.

All writes are CAS-only. A conflict raises `CheckpointConflictError`; monitoring does not
automatically reload and rerun the observation.

Commit rule:

```text
acquire
→ required downstream handoff succeeds
→ CAS-commit source/observation state
```

A serialization or CAS failure is non-mutating.

For a batch/change-feed response that contains a source-issued terminal cursor, that cursor
is only a **candidate** until all required records/changes through that boundary complete
the configured durable handoff.

## 11. M5 — exact deduplication

Deduplication answers: **has this logical record/change already been observed?**

```python
flow.dedupe(key="guid", retention=1000)
flow.dedupe(key=["source", "external_id"], retention="30d")
```

Requirements:

* first observation emits;
* repeats suppress;
* order is preserved;
* missing-key policy is explicit;
* retention is bounded by count and/or duration;
* identity/fingerprints reuse the canonical freezing/digest contract in
  `execution-semantics.md`;
* persisted history uses `StateStore`, with an explicit stateful owner/scope.

For change feeds, prefer a stable **change identity** rather than entity identity alone:

```text
(entity_id, version)
source event ID
another source-native stable change identifier
```

A repeated entity with a new version is not a duplicate merely because the entity ID is the
same.

`uniq` remains the finite-stream deterministic operator. Monitored dedupe owns cross-poll or
cross-resume history.

## 12. M6 — approximate membership

Approximate duplicate suppression is optional and explicit:

```python
flow.dedupe(key="guid", backend="bloom", capacity=1_000_000, false_positive_rate=0.001)
```

Rules:

* never silently substitute approximate for exact state;
* report configured capacity/error rate;
* document that false positives may suppress genuinely new records;
* use exact state when missed records are unacceptable;
* persistence still uses the configured `StateStore` rather than a backend-specific
  monitoring state API.

Near-duplicate content similarity such as Simhash/Nilsimsa belongs to
`enrichment-modules.md`, not exact logical identity.

## 13. M7 — change detection

Change detection answers: **has a known entity changed in selected business fields?**

```python
flow.changed(key="product_id", fields=["price", "availability"], first="emit")
```

Optional metadata may report previous/current selected values and changed fields. Metadata
uses the common `Metadata` model and is namespaced/opt-in.

This is independent of both source cursor advancement and source-emitted change identity. A
change feed may emit a new source version even when the business fields selected by
`changed()` are identical; conversely, a snapshot source may derive a business change without
any source-native change event.

## 14. M8 — write-if-changed composition

Source/observation state is not remote sink state.

For a provider write:

```text
records
→ transform/canonicalize
→ provider/artifact fingerprint
→ provider sink write_policy="if_changed"
```

Provider write semantics belong to `provider-integrations.md`; artifact fingerprint/lineage
belongs to `artifact-conversion.md`. Monitoring may produce the changed event but does not
own the remote-write contract. Side-effecting writes use the execution-derived idempotency
key where the destination can honor it.

## 15. M9 — bounded windows and anomaly vocabulary

Small local windows support lightweight anomaly detection:

```python
flow.window(count=100)
flow.window(duration="5m", timestamp="observed_at")
```

Initial methods:

```text
absolute threshold
percentage change
rolling mean deviation
z-score
rate/count threshold
```

Example:

```python
flow.anomaly(
    conf={"field": "latency_ms", "method": "zscore", "window": 100, "threshold": 3.0}
)
```

Do not add distributed watermarks, late-data correction, or ML model hosting to core.

A change feed with `ordering="partial"` or `"none"` does not become globally ordered merely
because it passes through a local window. Event-time/watermark semantics would require a
separate explicit contract.

Window/alert persistence uses the same stateful-owner and `StateStore` rules when state
must survive executions.

## 16. M10 — alert rule and firing state

Monitoring needs rule identity/history, not only a threshold function:

```python
@dataclass(frozen=True, slots=True, kw_only=True)
class AlertRule:
    id: str
    condition: Mapping[str, JsonValue]
    scope: Mapping[str, JsonValue]
    enabled: bool = True
    firing: Literal["every_match", "transition", "cooldown"] = "transition"
    cooldown_seconds: float | None = None
```

Semantics:

```text
every_match   emit every matching observation
transition    emit only non-match -> match
cooldown      re-emit only after configured quiet period
```

State payload may record:

```text
last_evaluated_at
last_match
last_fired_at
fire_count
last_event_id
```

Disable/re-enable preserves rule history. Persistent rule state is a typed `FeedState`
payload under the rule/stateful owner's `StateKey`, not a separate store schema.

## 17. M11 — actions are ordinary sinks/fan-out

Do not hard-code notification clients into anomaly operators:

```python
alerts = Pipeline.subscribe("alerts")

flow = monitor.publish(alerts)
email = alerts.write(...)
webhook = alerts.write(...)
audit = alerts.write(...)
```

Low-level compatibility modules may remain `send`/`receive`, but monitoring documentation
uses the public `publish`/`subscribe` vocabulary. Attached local branches are execution-owned
and do not require user drains for cleanup.

Monitoring decides **what happened**; delivery adapters decide **how to notify**.

Deletion changes are also ordinary records/events for routing purposes; there is no special
hard-coded deletion sink.

## 18. M12 — dry-run and explainability

Monitoring/rule testing supports no-side-effect execution:

```python
monitor(..., dry_run=True)
```

Dry-run may acquire/evaluate, but must not:

* advance persistent source/checkpoint state unless explicitly requested;
* mutate external observation state;
* invoke side-effecting notification sinks.

It should emit an explanation containing rule identity, observed value, baseline, and whether
an alert would have fired.

## 19. Feed-aware identity defaults

Recommended RSS/Atom logical identity precedence:

```text
entry id/guid
→ canonical link
→ configured composite key
→ stable record hash only when explicitly enabled
```

These values seed the private per-item `_FeedItem` identity/provenance model. Root identity
is automatically namespaced by source node identity, and generation remains stable across
retries.

A convenience helper may compose the generic primitives, but it must return an ordinary
`Pipeline` and must not create a second monitoring runtime.

## 20. Retry, failed observations, and recurrence

Separate three things:

```text
RetryPolicy
    retry an operation inside one finite observation/source read
    owner: execution-semantics.md

failed-observation policy
    after RetryPolicy is exhausted, decide whether the monitor stops or records/continues
    owner: this plan

recurrence delay
    delay before the next independent source observation
    owner: this plan
```

Example monitoring policy:

```python
monitor = {
    "on_poll_failure": "raise",  # raise | record_and_continue
    "failure_delay": 60,
}
```

The underlying source/pipeline uses the normal `RetryPolicy`; this plan does not introduce
a second `retry={...}` schema.

Cancellation interrupts both retries and recurrence delays. A failed observation, failed
change-feed read, or failed required handoff never advances source/observation state.

Notification/provider delivery has its own provider idempotency and may use the same generic
`RetryPolicy`; it must not cause source state to commit prematurely. A state-store CAS
conflict propagates; it is not treated as an instruction to reload/rerun automatically.

## 21. Deployment styles

### In-process periodic monitor

```text
application/service
→ Pipeline.poll(...)
→ dedupe/changed/window/anomaly
→ publish/sink
```

### In-process resumable change feed

```text
application/service
→ open source from committed FeedState
→ Change stream
→ dedupe/changed/routing
→ durable handoff
→ CAS-commit source state
```

### Orchestrated finite observations

```text
cron / Prefect / Airflow / sensor
→ finite poll_once or bounded change-feed batch
→ stateful monitoring operators
→ durable handoff
→ StateStore commit
→ exit
```

`orchestration.md` owns scheduling and run retries; all deployment styles reuse the same
core state/change contracts.

## 22. Observability

Emit normalized events/metrics for:

* observation/change-feed start/finish/duration;
* records/changes acquired, emitted, replay-suppressed, suppressed, and deleted;
* bootstrap policy/count;
* cursor before/candidate/committed after;
* declared change-feed history/ordering/replay/deletion/payload semantics;
* configured state backend/capabilities;
* changed entities;
* anomaly/rule evaluations/firings;
* RetryPolicy activity through runtime events;
* failed-observation policy/recurrence delay;
* checkpoint/state commits and CAS conflicts;
* sink delivery outcome;
* dry-run decisions;
* cancellation.

Never log credentials or sensitive payloads by default.

## 23. Testing strategy

Required tests include:

1. periodic source emits multiple finite observations;
2. finite recurrence stops deterministically;
3. bootstrap `all/latest/none/count` behavior;
4. timestamp lower-bound behavior where supported;
5. cancellation closes resources and interrupts recurrence delay;
6. `FeedState` resumes after restart simulation with a persistent store;
7. opaque checkpoint payload round-trips exactly without comparison/coercion;
8. failed handoff does not advance source state;
9. source retries use the shared `RetryPolicy` rather than a monitoring-specific retry type;
10. CAS conflict propagates and leaves state unchanged;
11. failed-observation `raise`/`record_and_continue` behavior;
12. change feed exposes entity identity separately from change/version identity;
13. repeated `(entity_id, version)` may be deduped while a new version of the same entity emits;
14. tombstone/delete change survives normalization and routing;
15. `event_log`/`latest_state`/`snapshot_delta` semantics are inspectable;
16. `total`/`partial`/`none` ordering semantics are inspectable and never strengthened implicitly;
17. `replay="possible"` survives workflow serialization/introspection;
18. reference and inline payload modes preserve the same change identity;
19. exact dedupe remains bounded;
20. approximate dedupe reports its error semantics;
21. `changed` reports selected-field changes only;
22. count/duration windows remain bounded;
23. deterministic threshold/z-score fixtures;
24. transition/cooldown firing semantics;
25. dry-run performs no external mutation;
26. in-process and orchestrated finite observation produce equivalent logical deltas.

## 24. Phases

```text
M0   finite FeedResult observation contract
M1   Pipeline.poll + bounded recurrence
M2   bootstrap/backfill policy
M3   source-position FeedState payloads + opaque cursor rule
M3a  Change + ChangeFeedSemantics + tombstones/replay identity
M4   StateStore integration/capability validation
M5   exact dedupe with change-identity guidance
M6   optional approximate membership
M7   changed
M8   write-if-changed composition boundary
M9   bounded windows + anomaly vocabulary
M10  alert rule/firing state
M11  publish/subscription action composition
M12  dry-run/explainability
M13  RSS/Atom monitoring helper
```

## 25. Definition of done

1. Riko can repeatedly observe finite sources without a private event loop.
2. Riko can represent a resumable source change without adopting a provider-specific event
   model.
3. Source observation/change feeds are clearly distinct from provider operation waiting.
4. First-observation/backfill semantics are explicit.
5. Source position, observation history, and alert state are distinct logical payloads but
   reuse one `FeedState` / `StateStore` infrastructure.
6. Opaque cursors round-trip through `FeedState` / `StateStore` without generic
   interpretation or comparison.
7. Change feeds declare history, ordering, replay, deletion, and payload guarantees.
8. Entity identity and change identity are separate concepts.
9. Explicit source deletions are preserved as tombstones rather than converted to absence.
10. State can persist without a mandatory service dependency, and configured store
    capabilities are inspectable/validatable.
11. Exact and approximate dedupe have explicit, distinct semantics.
12. Change detection and lightweight anomaly rules are configuration-friendly.
13. Monitoring reuses generic `RetryPolicy` instead of defining another retry contract.
14. Alert transition/cooldown behavior prevents accidental notification spam.
15. Actions remain ordinary provider/sink/`publish` operations.
16. Dry-run explains behavior without external mutation.
17. Scheduling/restart policy remains outside the monitoring core.
