# Riko Persistent Feed Monitoring and Change Detection Gameplan

## 1. Mission

Add first-class primitives for repeatedly observing finite sources and emitting only useful
changes, without turning Riko into a general-purpose scheduler, daemon, or workflow
orchestrator.

The target use cases are Huginn-style monitoring patterns such as:

```text
poll RSS/API/page
→ identify new or changed records
→ apply rules or anomaly logic
→ fan out interesting events
→ repeat
```

Riko already has strong pieces for the middle of this flow: RSS/Atom and web ingestion,
record transformations, filters, joins, fan-out, sync/async execution, and workflow
definitions. The missing pieces are the polling lifecycle and explicit source-state / change-
detection contracts.

This gameplan extends, but does not replace, `_docs/gameplans/orchestration.md`. The
orchestration plan remains authoritative for deployment-level scheduling, cron, webhook
servers, Airflow, Prefect, Dagster, and durable run boundaries. This plan defines reusable
**in-process monitoring primitives** that orchestrators or ordinary Python applications may
invoke.

## 2. Architectural rule

Separate four concerns:

```text
polling cadence
    when should the source be checked?

source position
    where should the next acquisition resume?

observation history
    which logical entities have already been seen, and did they change?

analysis
    does the new observation satisfy an alert/anomaly condition?
```

Do not collapse these into one `poll()` implementation.

## 3. Lessons from other systems

### 3.1 Huginn

Useful pattern:

* monitoring is a domain concept;
* sources can run on schedules;
* source/event state persists between observations;
* change and de-duplication are explicit user-facing concepts.

Do not copy:

* a Rails-style persistent server architecture;
* database-backed agent graphs as a Riko core requirement;
* a general scheduler inside the base CLI.

### 3.2 Streamz

Useful pattern:

* a periodic callback injects fresh values into the ordinary stream graph;
* once acquired, observations use the same stream operators as any other data source.

This is the closest conceptual fit for Riko's in-process API.

### 3.3 Bytewax

Useful pattern:

* polling sources cooperatively return control to the runtime;
* source-position state is separate from processing/operator state;
* state can be snapshotted and resumed when a deployment enables persistence.

This separation should be adopted even if the first Riko implementation keeps state in
memory.

### 3.4 dlt

Useful pattern:

* incremental extraction cursors are first-class source configuration;
* persisted pipeline state allows later runs to request only new/updated records;
* REST acquisition state is distinct from downstream transformation logic.

Riko should borrow the state model, not dlt's warehouse-loading focus.

## 4. Non-goals

This plan does not add:

* a durable scheduler daemon;
* cron parsing in core;
* distributed leases or worker ownership;
* exactly-once delivery claims;
* durable alert delivery;
* a monitoring UI;
* database-backed state as a mandatory dependency;
* a general CEP engine;
* machine-learning anomaly models in core.

Those may be provided by orchestrators, connectors, extension packages, or user code.

## 5. Phase M0 — define finite poll semantics

A polling source performs **one finite observation attempt** at a time.

Conceptually:

```python
result = await poll_once(source, context)
```

returns records and source metadata, then closes network/file resources before the next
interval begins.

A recurring monitor composes those finite polls:

```text
poll once
→ process result
→ commit source state after successful handoff
→ cancellation-aware sleep/backoff
→ poll again
```

This preserves the orchestration plan's rule that durable deployments should checkpoint
between finite polls rather than hiding an endless in-memory loop behind a restartable
source claim.

## 6. Phase M1 — in-process periodic source

Provide a lightweight async-native periodic source for ordinary Python applications.

Possible API:

```python
flow = AsyncPipe.poll(
    "fetch",
    interval=60,
    conf={"url": "https://example.com/feed.xml"},
)
```

or, if classmethod integration is too invasive initially:

```python
flow = AsyncPipe(
    "poll",
    conf={
        "pipe": "fetch",
        "interval": 60,
        "pipe_conf": {"url": "https://example.com/feed.xml"},
    },
)
```

Requirements:

* AnyIO-based cancellation-aware sleep;
* no private event loop;
* each poll closes its own finite source resources;
* interval begins from a documented point (`fixed_delay` initially);
* exceptions follow an explicit retry/error policy rather than silently continuing;
* unboundedness is declared through execution metadata;
* polling can be stopped by consumer cancellation/close.

Initial scheduling mode:

```text
fixed_delay
    wait interval after one poll finishes before starting the next
```

Do not add fixed-rate catch-up semantics until there is a demonstrated need.

## 7. Phase M2 — source position / cursor contract

Source position answers:

> Where should acquisition resume?

This is distinct from whether a record has changed.

Define a serializable checkpoint payload:

```python
@dataclass(frozen=True, slots=True, kw_only=True)
class SourceCheckpoint:
    source_id: str
    cursor: JsonValue
    observed_at: datetime
    metadata: Mapping[str, JsonValue]
```

Possible source cursor examples:

```text
RSS/Atom       latest stable item id + publication metadata
REST API       updated_at cursor / page token / last id
IMAP           UIDVALIDITY + UID
Kafka          partition offsets
file tail      inode/fingerprint + byte offset
```

The connector/source owns cursor interpretation. Core only defines lifecycle and
serialization contracts.

## 8. Phase M3 — checkpoint store protocol

Reuse the orchestration plan's `FeedCheckpointStore` concept and generalize only if needed.

```python
class CheckpointStore(Protocol):
    async def load(self, source_id: str) -> SourceCheckpoint | None: ...
    async def save(self, source_id: str, checkpoint: SourceCheckpoint) -> None: ...
```

Initial implementations:

```text
MemoryCheckpointStore
JsonFileCheckpointStore (optional utility, atomic replace)
```

External packages may provide database/object-store implementations.

Commit rule:

```text
acquire records
→ process/handoff succeeds
→ commit new checkpoint
```

Never advance durable source position before successful handoff unless a connector's
delivery semantics explicitly require it.

## 9. Phase M4 — de-duplication

De-duplication answers:

> Have I already observed this logical record?

Add a streaming operator with explicit key derivation:

```python
flow.dedupe(
    key="guid",
    retention=1000,
)
```

or composite keys:

```python
flow.dedupe(key=["source", "external_id"])
```

Semantics:

* first occurrence emits;
* repeat occurrence suppresses;
* order of emitted items is preserved;
* missing key behavior is explicit (`error`, `emit`, or `hash_record`);
* retention policy is bounded by count and optionally duration;
* hash-based whole-record fallback uses a stable canonical serializer.

Do not use an unbounded Python `set` by default for unbounded monitoring.

## 10. Phase M5 — change detection

Change detection answers:

> I have seen this entity before; did the selected value change?

Target API:

```python
flow.changed(
    key="product_id",
    fields=["price", "availability"],
)
```

Input:

```text
{id: 42, price: 100}
{id: 42, price: 100}
{id: 42, price: 95}
```

Output under `first="emit"`:

```text
{id: 42, price: 100}
{id: 42, price: 95}
```

Configuration:

```python
first: Literal["emit", "suppress"] = "emit"
comparison: Literal["selected", "record_hash"] = "selected"
```

Optional output metadata may include:

```python
{
    "_change": {
        "fields": ["price"],
        "previous": {"price": 100},
        "current": {"price": 95},
    }
}
```

Metadata injection must be opt-in or use a namespaced Riko metadata field so user records
are not silently polluted.

## 11. Phase M6 — state store separation

Observation-history state is different from source checkpoints.

Define a separate protocol:

```python
class StateStore(Protocol):
    async def get(self, namespace: str, key: str) -> JsonValue | None: ...
    async def set(self, namespace: str, key: str, value: JsonValue) -> None: ...
    async def delete(self, namespace: str, key: str) -> None: ...
```

Use it for:

* `dedupe` keys;
* `changed` baselines;
* rolling anomaly statistics;
* future keyed stateful operators.

Do not overload `SourceCheckpoint` with arbitrary transformation state.

## 12. Phase M7 — lightweight rolling/window state

To make anomaly detection useful without becoming Bytewax, add bounded local windows.

Initial primitives should be intentionally small:

```python
flow.window(count=100)
```

and later:

```python
flow.window(duration="5m", timestamp="observed_at")
```

Requirements:

* count windows are bounded in memory;
* duration windows evict expired observations;
* window output semantics are explicit (snapshot vs incremental aggregate);
* unbounded streams never create unbounded retained state accidentally;
* time-zone/timestamp parsing uses one normalized internal representation.

Do not start with watermarks, distributed event-time coordination, or late-data correction.
Those are Bytewax/Flink-class concerns.

## 13. Phase M8 — anomaly operator vocabulary

Riko should not ship ML models in core, but it can provide a configuration-friendly way to
express common monitoring thresholds.

Initial scope:

```text
absolute threshold
percentage change
rolling mean deviation
z-score
rate/count threshold
```

Possible API:

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

The operator emits only anomalous records by default and may attach diagnostic metadata:

```json
{
  "method": "zscore",
  "score": 3.42,
  "baseline": 121.5,
  "threshold": 3.0
}
```

For advanced statistical or ML logic, users should use callable stages or extension
packages.

## 14. Phase M9 — feed-aware defaults

RSS/Atom is a natural first monitored source because Riko already normalizes entries.

Define stable key-selection precedence for feed monitoring:

```text
entry id/guid
→ canonical link
→ configured composite key
→ stable record hash only when explicitly enabled
```

Feed-specific monitor helper may be added after generic primitives stabilize:

```python
flow = AsyncPipe.monitor_feed(
    url,
    interval=300,
    checkpoint="feed:example",
)
```

This helper should compose generic poll + source checkpoint + dedupe behavior rather than
implementing a second monitoring runtime.

## 15. Retry and backoff

Polling failures require explicit policy.

Suggested configuration:

```python
retry={
    "max_attempts": 5,
    "initial_delay": 1,
    "max_delay": 60,
    "multiplier": 2,
    "jitter": True,
}
```

Rules:

* retry belongs to one finite poll attempt;
* after attempts are exhausted, follow pipeline error policy;
* checkpoint is not advanced on failed acquisition/handoff;
* cancellation interrupts backoff immediately;
* HTTP `Retry-After` may influence delay through connector metadata;
* non-idempotent sink retries remain an orchestration/output concern.

## 16. Polling and orchestration boundary

Two supported deployment styles:

### In-process monitor

```text
Python application
→ AsyncPipe.poll(...)
→ changed/dedupe/anomaly
→ sink/send
```

Useful for:

* local agents;
* services that already own a process lifecycle;
* notebooks/development;
* short-lived monitoring utilities.

### Orchestrated finite polling

```text
cron / Prefect / Airflow / sensor
→ one finite Riko poll
→ changed/dedupe/anomaly using durable state
→ persist output
→ commit checkpoint
→ process exits
```

Preferred for restartable production deployments.

Both styles must share the same source-checkpoint and observation-state contracts.

## 17. Interaction with fan-out

The monitoring stack should compose naturally with named pub/sub:

```text
poll
→ dedupe
→ changed
→ anomaly
→ send("alerts")
      ├── email/webhook connector
      └── audit/archive branch
```

Fan-out buffer/error semantics are defined by the fan-out gameplan, not duplicated here.

## 18. Observability

Emit normalized events/metrics for:

* poll start/finish;
* records acquired;
* cursor before/after;
* records deduplicated;
* entities changed;
* anomalies emitted;
* retry count/backoff;
* checkpoint commit;
* checkpoint/state load failure;
* monitor cancellation.

Do not log secrets, raw credential material, or full sensitive payloads by default.

## 19. Testing strategy

Required contract tests:

1. periodic source emits multiple finite poll results;
2. cancellation stops sleep and closes source resources;
3. source checkpoint resumes after restart simulation;
4. checkpoint is not committed when downstream handoff fails;
5. dedupe suppresses repeated IDs with bounded retention;
6. change detection emits only selected field changes;
7. first-observation policy is honored;
8. state survives recreation when persistent test store is supplied;
9. count window stays bounded;
10. z-score/threshold anomaly fixtures are deterministic;
11. feed monitor does not re-emit previously committed items;
12. retry backoff is cancellation-aware;
13. in-process and finite orchestrated polling produce equivalent logical deltas.

## 20. Phases

```text
M0  Finite poll contract
M1  Async periodic source
M2  SourceCheckpoint cursor contract
M3  CheckpointStore
M4  dedupe
M5  changed
M6  StateStore separation
M7  bounded windows
M8  lightweight anomaly operators
M9  RSS/Atom monitoring helper
```

## 21. Definition of done

1. Riko can poll a finite source repeatedly without a private event loop.
2. Source position is separate from transformation state.
3. A durable deployment can resume from an explicit checkpoint.
4. `dedupe` and `changed` are separate operators with bounded-state behavior.
5. Simple anomaly detection can be expressed without custom monitoring loops.
6. RSS/Atom monitoring has stable new-item semantics.
7. Polling cancellation and retry behavior are explicit.
8. In-process monitoring does not turn the base CLI into a scheduler daemon.
9. Orchestrated finite polling remains the recommended restartable production pattern.
10. All monitoring primitives compose with existing Riko filters, fan-out, union, join, and callable stages.