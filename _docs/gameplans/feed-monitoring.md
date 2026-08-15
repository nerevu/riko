# Riko Persistent Feed Monitoring and Change Detection Gameplan

## 1. Mission

Add first-class primitives for repeatedly observing finite sources and emitting useful new,
changed, threshold, or anomaly events without turning Riko into a scheduler, daemon, or
workflow orchestrator.

Target shape:

```text
observe RSS/API/page
→ identify new or changed records
→ evaluate threshold/change/anomaly rules
→ fan out interesting events
→ commit source/observation state
→ repeat
```

This plan owns **recurring source observation and monitoring state**.

Related authoritative plans:

* `orchestration.md` — deployment schedules, durable run boundaries, external workers;
* `execution-semantics.md` — `RetryPolicy`, timeout, cancellation, error/disposition policy;
* `rest-incremental.md` — REST cursor extraction/encoding;
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
  and explicit incremental cursors.

These are design inputs, not compatibility targets. Do not copy pickle state files,
platform-specific notification systems, or a permanent scheduler into core.

## 3. Ownership boundary

Keep these concepts distinct:

```text
source observation cadence
    when should another finite source observation occur?

source position
    where should acquisition resume?

observation history
    which logical entities were seen and what values were previously observed?

analysis
    is this a change/anomaly/threshold event?

alert state
    did a rule already fire, transition, or enter cooldown?
```

This plan does **not** own generic provider-operation waiting:

```text
feed monitoring
    repeat independent source observations and emit records

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
IMAP        UIDVALIDITY + UID
Kafka       partition offsets
file tail   file identity + byte offset
```

The connector/source owns cursor meaning. This plan owns checkpoint lifecycle,
serialization, and commit ordering.

## 9. M4 — checkpoint and observation stores

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

## 10. M5 — exact deduplication

Deduplication answers: **has this logical record already been observed?**

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

`uniq` remains the finite-stream deterministic operator. Monitored dedupe owns cross-poll
history.

## 11. M6 — approximate membership

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

## 12. M7 — change detection

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

This is independent of source cursor advancement: an API may advance its cursor while the
selected business fields remain unchanged.

## 13. M8 — write-if-changed composition

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

## 14. M9 — bounded windows and anomaly vocabulary

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

## 15. M10 — alert rule and firing state

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

## 16. M11 — actions are ordinary sinks/fan-out

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

## 17. M12 — dry-run and explainability

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

## 18. Feed-aware identity defaults

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

## 19. Retry, failed observations, and recurrence

Separate three things:

```text
RetryPolicy
    retry an operation inside one finite observation
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
A failed observation or failed required handoff never advances the source checkpoint.

Notification/provider delivery has its own provider idempotency and may use the same generic
`RetryPolicy`; it must not cause source state to commit prematurely.

## 20. Deployment styles

### In-process

```text
application/service
→ AsyncPipe.poll(...)
→ dedupe/changed/window/anomaly
→ sink/fan-out
```

### Orchestrated finite observations

```text
cron / Prefect / Airflow / sensor
→ finite poll_once
→ stateful monitoring operators
→ durable handoff
→ checkpoint commit
→ exit
```

`orchestration.md` owns scheduling and run retries; both deployment styles reuse the same
checkpoint/state contracts defined here.

## 21. Observability

Emit normalized events/metrics for:

* observation start/finish/duration;
* records acquired/emitted/suppressed;
* bootstrap policy/count;
* cursor before/after;
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

## 22. Testing strategy

Required tests include:

1. periodic source emits multiple finite observations;
2. finite `iterations` stops deterministically;
3. bootstrap `all/latest/none/count` behavior;
4. timestamp lower-bound behavior where supported;
5. cancellation closes resources and interrupts recurrence delay;
6. checkpoint resumes after restart simulation;
7. failed handoff does not advance checkpoint;
8. source retries use the shared `RetryPolicy` rather than a monitoring-specific retry type;
9. failed-observation `raise`/`record_and_continue` behavior;
10. exact dedupe remains bounded;
11. approximate dedupe reports its error semantics;
12. `changed` reports selected-field changes only;
13. count/duration windows remain bounded;
14. deterministic threshold/z-score fixtures;
15. transition/cooldown firing semantics;
16. dry-run performs no external mutation;
17. in-process and orchestrated finite observation produce equivalent logical deltas.

## 23. Phases

```text
M0   finite observation contract
M1   periodic source + bounded iterations
M2   bootstrap/backfill policy
M3   SourceCheckpoint
M4   checkpoint/state stores
M5   exact dedupe
M6   optional approximate membership
M7   changed
M8   write-if-changed composition boundary
M9   bounded windows + anomaly vocabulary
M10  alert rule/firing state
M11  action/sink composition
M12  dry-run/explainability
M13  RSS/Atom monitoring helper
```

## 24. Definition of done

1. Riko can repeatedly observe finite sources without a private event loop.
2. Source observation polling is clearly distinct from provider operation waiting.
3. First-observation/backfill semantics are explicit.
4. Source position is separate from observation/alert state.
5. State can persist without a mandatory service dependency.
6. Exact and approximate dedupe have explicit, distinct semantics.
7. Change detection and lightweight anomaly rules are configuration-friendly.
8. Monitoring reuses generic `RetryPolicy` instead of defining another retry contract.
9. Alert transition/cooldown behavior prevents accidental notification spam.
10. Actions remain ordinary provider/sink/fan-out operations.
11. Dry-run explains behavior without external mutation.
12. Scheduling/restart policy remains outside the monitoring core.
