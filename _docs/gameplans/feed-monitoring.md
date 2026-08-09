# Riko Persistent Feed Monitoring and Change Detection Gameplan

## 1. Mission

Add first-class primitives for repeatedly observing finite sources and emitting only useful
changes, without turning Riko into a general-purpose scheduler, daemon, or workflow
orchestrator.

The target use cases are Huginn-style and earlier Nerevu monitoring patterns such as:

```text
poll RSS/API/page
→ identify new or changed records
→ evaluate threshold/change/anomaly rules
→ fan out interesting events
→ record delivery state
→ repeat
```

Riko already has strong pieces for the middle of this flow: RSS/Atom and web ingestion,
record transformations, filters, joins, fan-out, sync/async execution, and workflow
definitions. The missing pieces are polling lifecycle, explicit source-state/change
contracts, and a small alert-state vocabulary.

This plan extends `_docs/gameplans/orchestration.md`. The orchestration plan remains
authoritative for deployment-level scheduling, cron, webhook servers, Airflow, Prefect,
Dagster, durable workers, and run boundaries. This plan defines reusable monitoring
primitives that an orchestrator or ordinary Python application may invoke.

## 2. Inspiration integrated by this plan

The repository's inspiration corpus supplies several concrete precedents:

* **Chakula**: RSS `tail -f`, configurable interval, finite/infinite iteration count,
  persisted cache, `--unique`, `--newer`, explicit fail-on-error, and initial/backfill
  control.
* **email-sub-api**: a dedicated feed-monitor worker with file or Redis cache that emits
  an email action only for new entries.
* **AMS**: persisted named alert rules, min/max thresholds, rule enable/disable/restore,
  scoped rules, and notification history.
* **meetup**: explicit new-versus-changed entity detection and dry-run behavior.
* **ckanny / ckanutils**: content hashes used to suppress writes when a remote resource has
  not changed.
* **Huginn / Streamz / Bytewax / dlt**: domain-level monitoring, periodic sources,
  separation of source position from processing state, and incremental cursors.

These are design inputs, not compatibility targets. In particular, Riko should not copy
pickle state files, platform-specific Growl notifications, a permanent worker daemon, or a
scheduler into core.

## 3. Architectural rule

Keep these concerns separate:

```text
polling cadence
    when should the source be checked?

source position
    where should acquisition resume?

observation history
    which entities/items have been seen and what was their prior value?

analysis
    does the observation constitute a change/anomaly/threshold event?

notification state
    was an alert already emitted, acknowledged, disabled, or cooled down?
```

Do not collapse these into one `poll()` or `alert()` implementation.

## 4. Non-goals

This plan does not add:

* a durable scheduler daemon or cron parser to core;
* distributed leases or worker ownership;
* exactly-once delivery claims;
* a mandatory database/Redis dependency;
* a monitoring dashboard;
* a general complex-event-processing engine;
* machine-learning anomaly models in core;
* provider-specific notification clients in core.

## 5. M0 — finite poll contract

A source poll is one bounded observation attempt:

```python
result = await poll_once(source, context)
```

It returns records plus source metadata and closes finite network/file resources before the
next attempt.

A recurring monitor composes finite attempts:

```text
load committed checkpoint
→ poll once
→ process records
→ successful handoff
→ commit checkpoint/state
→ cancellation-aware delay/backoff
→ repeat
```

This is the same logical contract whether the recurrence is driven by an in-process loop,
cron, an orchestrator sensor, or an agent worker.

## 6. M1 — periodic source and bounded iterations

Provide an async-native periodic source for applications that already own a process
lifecycle:

```python
flow = AsyncPipe.poll(
    "fetch",
    interval=60,
    conf={"url": "https://example.com/feed.xml"},
)
```

Requirements:

* AnyIO cancellation-aware sleep;
* no private event loop;
* fixed-delay cadence initially;
* explicit retry/error policy;
* clean close on consumer cancellation;
* declared unboundedness;
* optional `iterations` limit for tests, one-off monitors, and deterministic CLI usage.

The `iterations` idea comes directly from Chakula and is useful even though production
monitoring is normally unbounded or orchestrated:

```python
AsyncPipe.poll(..., interval=60, iterations=3)
```

## 7. M2 — bootstrap and backfill policy

A monitor must define what happens on its first observation. Do not infer this from cache
contents implicitly.

Suggested policy:

```python
bootstrap: Literal["all", "latest", "none", "count"] = "all"
bootstrap_count: int | None = None
```

Examples:

```text
all      emit all current items, then checkpoint
latest   emit only the newest current item
none     establish checkpoint without emitting existing items
count    emit the newest N current items
```

Also support an optional source-level lower bound when the source has reliable timestamps:

```python
after="2026-08-01T00:00:00Z"
```

This generalizes Chakula's `--initial` and `--newer` behavior while keeping source-specific
timestamp interpretation inside the connector/source.

## 8. M3 — source checkpoint contract

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
RSS/Atom       stable item id/guid + publication metadata
REST API       updated_at / last id / continuation token
IMAP           UIDVALIDITY + UID
Kafka          partition offsets
file tail      file identity + byte offset
```

Connector/source code owns cursor meaning. Core owns lifecycle, serialization, and commit
ordering.

## 9. M4 — checkpoint and state stores

Checkpoint state and observation state are separate protocols.

```python
class CheckpointStore(Protocol):
    async def load(self, source_id: str) -> SourceCheckpoint | None: ...
    async def save(self, source_id: str, checkpoint: SourceCheckpoint) -> None: ...


class StateStore(Protocol):
    async def get(self, namespace: str, key: str) -> JsonValue | None: ...
    async def set(self, namespace: str, key: str, value: JsonValue) -> None: ...
    async def delete(self, namespace: str, key: str) -> None: ...
```

Initial implementations:

```text
MemoryCheckpointStore / MemoryStateStore
JsonFileCheckpointStore / JsonFileStateStore
```

Optional packages may provide Redis, SQLite, database, or object-store implementations.
This preserves the useful file/Redis cache pattern from Chakula and email-sub-api without
making either backend mandatory.

Commit rule:

```text
acquire
→ downstream handoff succeeds
→ commit checkpoint and observation state
```

## 10. M5 — exact de-duplication

De-duplication answers: **have I already observed this logical record?**

```python
flow.dedupe(key="guid", retention=1000)
flow.dedupe(key=["source", "external_id"], retention="30d")
```

Requirements:

* first occurrence emits;
* repeat occurrence suppresses;
* order is preserved;
* missing-key behavior is explicit (`error`, `emit`, `hash_record`);
* retention is bounded by count and/or duration;
* record hashing uses stable canonical serialization;
* state scope is explicit (`execution` or named external state namespace).

`uniq` remains the finite-stream deterministic operator; monitored de-duplication owns
cross-poll history.

## 11. M6 — approximate membership is optional and explicit

The Changanya inspiration includes Bloom filters and similarity hashes. These are useful
only when their semantics are visible.

An optional high-volume dedupe backend may use a Bloom filter:

```python
flow.dedupe(
    key="guid",
    backend="bloom",
    capacity=1_000_000,
    false_positive_rate=0.001,
)
```

Rules:

* approximate mode is never silently substituted for exact mode;
* configured capacity and false-positive rate are reported in metadata;
* a false positive may suppress a genuinely new item and must be documented;
* use exact state when missed records are unacceptable.

Simhash/Nilsimsa-style near-duplicate content detection remains under the enrichment
module gameplan rather than being conflated with exact item identity.

## 12. M7 — change detection

Change detection answers: **I have seen this entity; did selected values change?**

```python
flow.changed(
    key="product_id",
    fields=["price", "availability"],
    first="emit",
)
```

Optional change metadata may expose previous/current selected values and changed fields.
Metadata must be namespaced and opt-in.

The operator supports historical snapshot patterns such as the Meetup `changed` command
without requiring source timestamps to encode business identity.

## 13. M8 — hash-aware sink suppression

Some systems do not need to suppress records at acquisition time; they need to avoid a
remote write when output bytes/data are unchanged. CKAN tooling in the inspiration corpus
used a persisted resource hash for this purpose.

Keep that as a sink/write policy, not as source checkpoint state:

```text
transform records
→ canonicalize output artifact/table payload
→ fingerprint
→ compare remote/committed fingerprint
→ write only if changed
```

The connector gameplan owns the eventual `if_changed` / idempotent write contract. This
monitoring plan only requires change metadata to compose with it.

## 14. M9 — bounded windows and anomaly vocabulary

Add small local windows sufficient for lightweight anomaly detection:

```python
flow.window(count=100)
flow.window(duration="5m", timestamp="observed_at")
```

Initial anomaly methods:

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

Do not add watermarks, distributed event-time coordination, late-data correction, or ML
model hosting to core.

## 15. M10 — alert rule and firing semantics

AMS demonstrates that a useful monitoring system needs more than a threshold function: it
needs rule identity and firing history. Define a portable rule description, but keep
persistence/UI outside core unless later justified.

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
every_match   emit on every matching observation
transition    emit only when state changes from non-matching to matching
cooldown      re-emit only after the configured quiet period
```

Alert state may record:

```text
last_evaluated_at
last_match
last_fired_at
fire_count
last_event_id
```

Disabling a rule should preserve its history so it can be re-enabled, mirroring the useful
remove/restore idea from AMS without requiring a pickle-based registry.

## 16. M11 — alert actions are ordinary sinks/fan-out

Do not hard-code email, desktop notifications, SMS, or webhooks into anomaly operators.

```text
monitor
→ changed/anomaly
→ send("alerts")
      ├── email connector
      ├── webhook connector
      └── audit/archive sink
```

This preserves the useful email-sub-api architecture: monitoring decides **what happened**;
a delivery adapter decides **how to notify**.

## 17. M12 — dry-run and explainability

Monitoring and alert rule testing should support a no-side-effect mode:

```python
monitor(..., dry_run=True)
```

Dry-run may poll and evaluate but must not:

* advance durable checkpoints unless explicitly requested;
* mutate external observation state;
* invoke side-effecting notification sinks.

It should emit an explanation record showing the matched rule, observed value, baseline,
and whether a notification would have fired. This generalizes the dry-run pattern seen in
Meetup and Microsoft administration tooling.

## 18. Feed-aware identity defaults

RSS/Atom is the first monitored source because Riko already normalizes entries. Recommended
key precedence:

```text
entry id/guid
→ canonical link
→ configured composite key
→ stable record hash only when explicitly enabled
```

A convenience helper may later compose generic primitives:

```python
flow = AsyncPipe.monitor_feed(
    url,
    interval=300,
    bootstrap="none",
    checkpoint="feed:example",
)
```

It must not create a second monitoring runtime.

## 19. Retry, failure, and delivery policy

Polling failures require explicit bounded retry/backoff. Chakula's fail-fast switch becomes
a general policy rather than a feed-only flag.

```python
retry={
    "max_attempts": 5,
    "initial_delay": 1,
    "max_delay": 60,
    "multiplier": 2,
    "jitter": True,
}
```

After retry exhaustion, an application chooses `raise`, `record_and_continue`, or another
explicit policy. Cancellation interrupts backoff immediately. Checkpoints are never
advanced for a failed acquisition or failed required handoff.

Notification delivery has separate retry/idempotency semantics and must not cause a source
cursor to advance prematurely.

## 20. Deployment styles

### In-process monitor

```text
application/service
→ AsyncPipe.poll(...)
→ dedupe/changed/window/anomaly
→ sink/send
```

### Orchestrated finite polling

```text
cron / Prefect / Airflow / sensor
→ one finite Riko poll
→ stateful operators using durable stores
→ durable handoff
→ commit checkpoint
→ exit
```

The latter remains preferred for restartable production deployments. Both must use the
same checkpoint and state contracts.

## 21. Observability

Emit normalized events/metrics for:

* poll start/finish and duration;
* records acquired/emitted/suppressed;
* bootstrap policy and count;
* cursor before/after;
* state/checkpoint backend;
* entities changed;
* anomalies/rules evaluated and fired;
* retry/backoff;
* checkpoint commits;
* sink delivery outcome;
* dry-run decisions;
* cancellation.

Never log credentials or sensitive payloads by default.

## 22. Testing strategy

Required contract tests include:

1. periodic source emits multiple finite poll results;
2. finite `iterations` stops deterministically;
3. bootstrap `all/latest/none/count` behavior;
4. timestamp lower-bound behavior when supported;
5. cancellation closes resources and interrupts sleeps;
6. checkpoint resumes after restart simulation;
7. failed handoff does not advance checkpoint;
8. exact dedupe stays bounded;
9. Bloom dedupe reports approximate semantics and configured error rate;
10. `changed` reports selected-field changes only;
11. count/duration windows remain bounded;
12. deterministic threshold/z-score anomaly fixtures;
13. transition and cooldown alert firing semantics;
14. disabled rule preserves history and can be re-enabled;
15. dry-run performs no external mutation;
16. feed identity precedence is stable;
17. in-process and orchestrated finite polling produce equivalent logical deltas.

## 23. Phases

```text
M0   finite poll contract
M1   periodic source + bounded iterations
M2   bootstrap/backfill policy
M3   SourceCheckpoint
M4   checkpoint/state stores
M5   exact dedupe
M6   optional approximate membership backend
M7   changed
M8   hash-aware sink integration contract
M9   bounded windows + anomaly vocabulary
M10  alert rule/firing state
M11  action/sink composition
M12  dry-run/explainability
M13  RSS/Atom monitoring helper
```

## 24. Definition of done

1. Riko can repeatedly poll finite sources without a private event loop.
2. First-observation/backfill semantics are explicit and deterministic.
3. Source position is separate from observation and alert state.
4. State can persist through file or extension-provided backends without a mandatory
   service dependency.
5. Exact dedupe and changed-record detection have distinct contracts.
6. Approximate dedupe cannot masquerade as exact dedupe.
7. Lightweight threshold/window anomaly detection is configuration-friendly.
8. Alert transition/cooldown semantics prevent accidental notification spam.
9. Actions remain ordinary sinks/fan-out, not embedded notification code.
10. Dry-run can explain behavior without external mutations.
11. Production restartability continues to belong to orchestration/deployment policy.
12. All monitoring primitives compose with existing Riko filters, fan-out, `union`,
    `join`, REST sources, and callable stages.
