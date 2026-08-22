# Riko Persistent Feed Monitoring and Change Detection Gameplan

## 1. Mission

Add first-class primitives for repeatedly observing finite sources and consuming resumable
change feeds while emitting useful new, changed, deleted, threshold, or anomaly events
without turning Riko into a scheduler, daemon, or workflow orchestrator.

Target shape:

```text
observe finite source or resumable change feed
→ identify new / changed / deleted records
→ evaluate threshold/change/anomaly rules
→ fan out interesting events
→ commit source/observation state
→ repeat or resume
```

This plan owns **recurring source observation, resumable change-feed semantics, and
monitoring state**.

Related authoritative plans:

* `orchestration.md` — deployment schedules, durable run boundaries, external workers;
* `execution-semantics.md` — `RetryPolicy`, timeout, cancellation, error/disposition policy;
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
* another generic retry or operation-wait implementation.

## 5. M0 — finite observation contract

One observation is bounded:

```python
result = await poll_once(source, context)
```

It returns records plus source metadata and closes finite source resources before returning.

A recurring monitor composes those observations:

```text
load committed checkpoint/state
→ poll once
→ process records
→ successful required handoff
→ commit checkpoint/state
→ cancellation-aware recurrence delay
→ repeat
```

The same finite observation can be invoked by an in-process service, cron, an orchestrator
sensor, or an agent worker.

A resumable change-feed source may instead keep emitting changes during one source
iteration. It still uses the same checkpoint commit rule and does not create a second state
model.

## 6. M1 — periodic source and bounded iterations

Applications that own a long-lived process may use an async-native periodic source:

```python
flow = AsyncPipe.poll(
    "fetch",
    interval=60,
    iterations=None,
    conf={"url": "https://example.com/feed.xml"},
)
```

Requirements:

* AnyIO cancellation-aware delay;
* no private event loop;
* fixed-delay cadence initially;
* known unboundedness when `iterations=None`;
* deterministic finite `iterations` for tests/CLI;
* clean close on cancellation;
* retries **within one observation attempt** use `RetryPolicy` from
  `execution-semantics.md`.

`interval` controls recurrence between completed observations; it is not a retry policy.

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
all      emit all current items, then checkpoint
latest   emit only newest current item
none     establish checkpoint without emitting current items
count    emit newest N current items
```

Sources with meaningful timestamps may also accept a lower bound such as:

```python
after="2026-08-01T00:00:00Z"
```

Source-specific timestamp/cursor interpretation remains inside the source/connector.

Change feeds may additionally expose a source-defined "current position" bootstrap that
establishes a checkpoint without replaying prior changes. The source owns how that position
is obtained; the shared checkpoint lifecycle owns when it becomes committed.

## 8. M3 — SourceCheckpoint

Source position answers: **where should acquisition resume?**

```python
@dataclass(frozen=True, slots=True, kw_only=True)
class SourceCheckpoint:
    source_id: str
    cursor: JsonValue
    observed_at: datetime
    metadata: Mapping[str, JsonValue]
```

Examples:

```text
RSS/Atom    item id/guid + publication metadata
REST API    timestamp/id/continuation cursor
change feed opaque source-issued resume token
IMAP        UIDVALIDITY + UID
Kafka       partition offsets
file tail   file identity + byte offset
```

The connector/source owns cursor meaning. This plan owns checkpoint lifecycle,
serialization, and commit ordering.

An opaque cursor is treated as an uninterpreted source token. Generic monitoring code must:

* serialize and persist it without semantic transformation;
* return it to the same source contract when resuming;
* never increment it;
* never numerically or lexicographically compare it;
* never infer ordering from its textual/JSON representation.

A source adapter may understand its own cursor format, but that knowledge does not leak into
generic checkpoint logic.

## 9. M3a — resumable change-feed contract

A change feed is a source that emits source-observed changes together with a resumable
position. It is not assumed to be a complete event log.

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
    history: Literal[
        "event_log",
        "latest_state",
        "snapshot_delta",
    ]
    ordering: Literal[
        "total",
        "partial",
        "none",
    ]
    replay: Literal[
        "possible",
        "not_expected",
    ]
    deletion: Literal[
        "tombstone",
        "absent",
        "unsupported",
    ]
    payload: Literal[
        "reference",
        "inline",
    ]
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
checkpoint
    where acquisition resumes

dedupe
    whether this logical change identity has already been processed

sink idempotency
    whether replaying downstream side effects is safe
```

These remain separate contracts. A source with `replay="possible"` should make that fact
visible in plan/introspection metadata so planners and operators can require dedupe or
idempotent sinks where appropriate.

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

## 10. M4 — checkpoint and observation stores

Source position and observation history are separate:

```python
class CheckpointStore(Protocol):
    async def load(self, source_id: str) -> SourceCheckpoint | None: ...
    async def save(self, source_id: str, checkpoint: SourceCheckpoint) -> None: ...


class StateStore(Protocol):
    async def get(self, namespace: str, key: str) -> JsonValue | None: ...
    async def set(self, namespace: str, key: str, value: JsonValue) -> None: ...
    async def delete(self, namespace: str, key: str) -> None: ...
```

Initial implementations may be memory and JSON-file stores. Optional packages may provide
Redis, SQLite, databases, or object storage.

Commit rule:

```text
acquire
→ required downstream handoff succeeds
→ commit checkpoint and observation state
```

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
* hashing uses stable canonical serialization;
* state scope is explicit.

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
flow.dedupe(
    key="guid",
    backend="bloom",
    capacity=1_000_000,
    false_positive_rate=0.001,
)
```

Rules:

* never silently substitute approximate for exact state;
* report configured capacity/error rate;
* document that false positives may suppress genuinely new records;
* use exact state when missed records are unacceptable.

Near-duplicate content similarity such as Simhash/Nilsimsa belongs to
`enrichment-modules.md`, not exact logical identity.

## 13. M7 — change detection

Change detection answers: **has a known entity changed in selected business fields?**

```python
flow.changed(
    key="product_id",
    fields=["price", "availability"],
    first="emit",
)
```

Optional metadata may report previous/current selected values and changed fields. Metadata
is namespaced and opt-in.

This is independent of both source cursor advancement and source-emitted change identity. A
change feed may emit a new source version even when the business fields selected by
`changed()` are identical; conversely, a snapshot source may derive a business change
without any source-native change event.

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
own the remote-write contract.

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
    conf={
        "field": "latency_ms",
        "method": "zscore",
        "window": 100,
        "threshold": 3.0,
    }
)
```

Do not add distributed watermarks, late-data correction, or ML model hosting to core.

A change feed with `ordering="partial"` or `"none"` does not become globally ordered merely
because it passes through a local window. Event-time/watermark semantics would require a
separate explicit contract.

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
transition    emit only non-match → match
cooldown      re-emit only after configured quiet period
```

State may record:

```text
last_evaluated_at
last_match
last_fired_at
fire_count
last_event_id
```

Disable/re-enable preserves rule history.

## 17. M11 — actions are ordinary sinks/fan-out

Do not hard-code notification clients into anomaly operators:

```text
monitor
→ changed/anomaly
→ send("alerts")
      ├── email provider
      ├── webhook provider
      └── audit/archive sink
```

Monitoring decides **what happened**; delivery adapters decide **how to notify**.

Deletion changes are also ordinary records/events for routing purposes; there is no special
hard-coded deletion sink.

## 18. M12 — dry-run and explainability

Monitoring/rule testing supports no-side-effect execution:

```python
monitor(..., dry_run=True)
```

Dry-run may acquire/evaluate, but must not:

* advance durable checkpoints unless explicitly requested;
* mutate external observation state;
* invoke side-effecting notification sinks.

It should emit an explanation containing rule identity, observed value, baseline, and whether
an alert would have fired.

## 19. Feed-aware identity defaults

Recommended RSS/Atom identity precedence:

```text
entry id/guid
→ canonical link
→ configured composite key
→ stable record hash only when explicitly enabled
```

A convenience helper may compose the generic primitives:

```python
flow = AsyncPipe.monitor_feed(
    url,
    interval=300,
    bootstrap="none",
    checkpoint="feed:example",
)
```

It must not create a second monitoring runtime.

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
monitor={
    "on_poll_failure": "raise",  # raise | record_and_continue
    "failure_delay": 60,
}
```

The underlying source/pipe uses the normal `RetryPolicy`; this plan does not introduce a
second `retry={...}` schema.

Cancellation interrupts both retries (through execution semantics) and recurrence delays.
A failed observation, failed change-feed read, or failed required handoff never advances the
committed source checkpoint.

Notification/provider delivery has its own provider idempotency and may use the same generic
`RetryPolicy`; it must not cause source state to commit prematurely.

## 21. Deployment styles

### In-process periodic monitor

```text
application/service
→ AsyncPipe.poll(...)
→ dedupe/changed/window/anomaly
→ sink/fan-out
```

### In-process resumable change feed

```text
application/service
→ open source from committed cursor
→ Change stream
→ dedupe/changed/routing
→ durable handoff
→ checkpoint advancement
```

### Orchestrated finite observations

```text
cron / Prefect / Airflow / sensor
→ finite poll_once or bounded change-feed batch
→ stateful monitoring operators
→ durable handoff
→ checkpoint commit
→ exit
```

`orchestration.md` owns scheduling and run retries; all deployment styles reuse the same
checkpoint/state/change semantics defined here.

## 22. Observability

Emit normalized events/metrics for:

* observation/change-feed start/finish/duration;
* records/changes acquired, emitted, replay-suppressed, and deleted;
* bootstrap policy/count;
* cursor before/candidate/committed after;
* declared change-feed history/ordering/replay/deletion/payload semantics;
* checkpoint/state backend;
* changed entities;
* anomaly/rule evaluations/firings;
* RetryPolicy activity through runtime events;
* failed-observation policy/recurrence delay;
* checkpoint commits;
* sink delivery outcome;
* dry-run decisions;
* cancellation.

Never log credentials or sensitive payloads by default.

## 23. Testing strategy

Required tests include:

1. periodic source emits multiple finite observations;
2. finite `iterations` stops deterministically;
3. bootstrap `all/latest/none/count` behavior;
4. timestamp lower-bound behavior where supported;
5. cancellation closes resources and interrupts recurrence delay;
6. checkpoint resumes after restart simulation;
7. opaque checkpoint cursor round-trips exactly without comparison/coercion;
8. failed handoff does not advance checkpoint;
9. source retries use the shared `RetryPolicy` rather than a monitoring-specific retry type;
10. failed-observation `raise`/`record_and_continue` behavior;
11. change feed exposes entity identity separately from change/version identity;
12. repeated `(entity_id, version)` may be deduped while a new version of the same entity emits;
13. tombstone/delete change survives normalization and routing;
14. `event_log`/`latest_state`/`snapshot_delta` semantics are inspectable;
15. `total`/`partial`/`none` ordering semantics are inspectable and never strengthened implicitly;
16. `replay="possible"` survives workflow serialization/introspection;
17. reference and inline payload modes preserve the same change identity;
18. exact dedupe remains bounded;
19. approximate dedupe reports its error semantics;
20. `changed` reports selected-field changes only;
21. count/duration windows remain bounded;
22. deterministic threshold/z-score fixtures;
23. transition/cooldown firing semantics;
24. dry-run performs no external mutation;
25. in-process and orchestrated finite observation produce equivalent logical deltas.

## 24. Phases

```text
M0   finite observation contract
M1   periodic source + bounded iterations
M2   bootstrap/backfill policy
M3   SourceCheckpoint + opaque cursor rule
M3a  Change + ChangeFeedSemantics + tombstones/replay identity
M4   checkpoint/state stores
M5   exact dedupe with change-identity guidance
M6   optional approximate membership
M7   changed
M8   write-if-changed composition boundary
M9   bounded windows + anomaly vocabulary
M10  alert rule/firing state
M11  action/sink composition
M12  dry-run/explainability
M13  RSS/Atom monitoring helper
```

## 25. Definition of done

1. Riko can repeatedly observe finite sources without a private event loop.
2. Riko can represent a resumable source change without adopting a provider-specific event model.
3. Source observation/change feeds are clearly distinct from provider operation waiting.
4. First-observation/backfill semantics are explicit.
5. Source position is separate from observation/alert state.
6. Opaque cursors round-trip without generic interpretation or comparison.
7. Change feeds declare history, ordering, replay, deletion, and payload guarantees.
8. Entity identity and change identity are separate concepts.
9. Explicit source deletions are preserved as tombstones rather than converted to absence.
10. State can persist without a mandatory service dependency.
11. Exact and approximate dedupe have explicit, distinct semantics.
12. Change detection and lightweight anomaly rules are configuration-friendly.
13. Monitoring reuses generic `RetryPolicy` instead of defining another retry contract.
14. Alert transition/cooldown behavior prevents accidental notification spam.
15. Actions remain ordinary provider/sink/fan-out operations.
16. Dry-run explains behavior without external mutation.
17. Scheduling/restart policy remains outside the monitoring core.
