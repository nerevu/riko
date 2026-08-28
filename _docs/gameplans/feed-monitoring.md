# Feed monitoring gameplan

## 1. Mission

Add first-class primitives for repeatedly observing finite sources and emitting useful new,
changed, threshold, or anomaly events without turning Riko into a scheduler, daemon, or
workflow orchestrator.

Target shape:

```text
observe RSS/API/page
→ identify new or changed records
→ evaluate threshold/change/anomaly rules
→ explicit fan-out of interesting events
→ commit observation/source state through StateStore
→ repeat
```

This plan owns **recurring source observation and monitoring policy**. It does not define a
second persistence/checkpoint abstraction.

Related authoritative plans:

* `execution-semantics.md` — `Pipeline`, `FeedResult`, `FeedState`, `StateStore`, checkpoints,
  identity/generation, retry, timeout, cancellation, error/disposition policy;
* `orchestration.md` — deployment schedules, durable run boundaries, external workers;
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

All persisted forms use the common `FeedState[T]` / `StateStore` infrastructure; the
logical payload type and stateful owner distinguish source position, monitoring history,
and alert state.

This plan does **not** own generic provider-operation waiting:

```text
feed monitoring
    repeat independent finite source observations and emit records

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
IMAP        UIDVALIDITY + UID
Kafka       partition offsets
file tail   file identity + byte offset
```

A source may use an owner-level `StateKey[T]` (`item_key=None`, `generation=None`) for
intrinsic source progress. Explicit incremental recovery boundaries use `.checkpoint()` and
the enclosing stateful owner's identity rules from `execution-semantics.md`.

## 9. M4 — one StateStore, heterogeneous state

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
        self,
        key: StateKey[T],
        *,
        expected_version: StateVersion,
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
* identity/fingerprints reuse the canonical freezing/digest contract in
  `execution-semantics.md`;
* persisted history uses `StateStore`, with an explicit stateful owner/scope.

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
* use exact state when missed records are unacceptable;
* persistence still uses the configured `StateStore` rather than a backend-specific
  monitoring state API.

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
uses the common `Metadata` model and is namespaced/opt-in.

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
own the remote-write contract. Side-effecting writes use the execution-derived idempotency
key where the destination can honor it.

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

Window/alert persistence uses the same stateful-owner and `StateStore` rules when state
must survive executions.

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

## 16. M11 — actions are ordinary sinks/fan-out

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

## 17. M12 — dry-run and explainability

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

## 18. Feed-aware identity defaults

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
monitor = {
    "on_poll_failure": "raise",  # raise | record_and_continue
    "failure_delay": 60,
}
```

The underlying source/pipeline uses the normal `RetryPolicy`; this plan does not introduce
a second `retry={...}` schema.

Cancellation interrupts both retries and recurrence delays. A failed observation or failed
required handoff never advances source/observation state.

Notification/provider delivery has its own provider idempotency and may use the same generic
`RetryPolicy`; it must not cause source state to commit prematurely. A state-store CAS
conflict propagates; it is not treated as an instruction to reload/rerun automatically.

## 20. Deployment styles

### In-process

```text
application/service
→ Pipeline.poll(...)
→ dedupe/changed/window/anomaly
→ publish/sink
```

### Orchestrated finite observations

```text
cron / Prefect / Airflow / sensor
→ finite poll_once
→ stateful monitoring operators
→ durable handoff
→ StateStore commit
→ exit
```

`orchestration.md` owns scheduling and run retries; both deployment styles reuse the same
core state contracts.

## 21. Observability

Emit normalized events/metrics for:

* observation start/finish/duration;
* records acquired/emitted/suppressed;
* bootstrap policy/count;
* cursor before/after;
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

## 22. Testing strategy

Required tests include:

1. periodic source emits multiple finite observations;
2. finite recurrence stops deterministically;
3. bootstrap `all/latest/none/count` behavior;
4. timestamp lower-bound behavior where supported;
5. cancellation closes resources and interrupts recurrence delay;
6. `FeedState` resumes after restart simulation with a persistent store;
7. failed handoff does not advance source state;
8. source retries use the shared `RetryPolicy` rather than a monitoring-specific retry type;
9. CAS conflict propagates and leaves state unchanged;
10. failed-observation `raise`/`record_and_continue` behavior;
11. exact dedupe remains bounded;
12. approximate dedupe reports its error semantics;
13. `changed` reports selected-field changes only;
14. count/duration windows remain bounded;
15. deterministic threshold/z-score fixtures;
16. transition/cooldown firing semantics;
17. dry-run performs no external mutation;
18. in-process and orchestrated finite observation produce equivalent logical deltas.

## 23. Phases

```text
M0   finite FeedResult observation contract
M1   Pipeline.poll + bounded recurrence
M2   bootstrap/backfill policy
M3   source-position FeedState payloads
M4   StateStore integration/capability validation
M5   exact dedupe
M6   optional approximate membership
M7   changed
M8   write-if-changed composition boundary
M9   bounded windows + anomaly vocabulary
M10  alert rule/firing state
M11  publish/subscription action composition
M12  dry-run/explainability
M13  RSS/Atom monitoring helper
```

## 24. Definition of done

1. Riko can repeatedly observe finite sources without a private event loop.
2. Source observation polling is clearly distinct from provider operation waiting.
3. First-observation/backfill semantics are explicit.
4. Source position, observation history, and alert state are distinct logical payloads but
   reuse one `FeedState` / `StateStore` infrastructure.
5. State can persist without a mandatory service dependency, and configured store
   capabilities are inspectable/validatable.
6. Exact and approximate dedupe have explicit, distinct semantics.
7. Change detection and lightweight anomaly rules are configuration-friendly.
8. Monitoring reuses generic `RetryPolicy` instead of defining another retry contract.
9. Alert transition/cooldown behavior prevents accidental notification spam.
10. Actions remain ordinary provider/sink/`publish` operations.
11. Dry-run explains behavior without external mutation.
12. Scheduling/restart policy remains outside the monitoring core.
