# Riko Execution Semantics Contract Gameplan

> **Provenance.** Extracted from `docs/ROADMAP.md` so the roadmap stays a high-level overview. This gameplan is the authoritative detail for the runtime execution-semantics contract — execution characteristics, async backpressure, timeout, union/merge, retry, errors/dispositions, filter semantics, and the batch model (ROADMAP §5–§8, §11–§13, §16). Section references like §N point back to [RUNTIME_CONTRACT.md](../RUNTIME_CONTRACT.md) (the runtime contract); the numbered `## N.` headings are preserved so those references resolve.

## 5. Execution characteristics

> **Status: Planned.** `Opts` does not contain `boundedness`/`ordering`/`side_effects`/`determinism`/`require_bounded`/`state_checkpoint`/`lineage_commit`; the bounded/ordered *behaviors* live in the §6 primitives, not as declared metadata.

### 5.1 Boundedness

```python
boundedness: Literal[
    "preserve",
    "finite",
    "unbounded",
    "unknown",
]
```

Examples:

| Stage                       | Opt         |
| --------------------------- | ----------- |
| `map`                       | `preserve`  |
| `filter`                    | `preserve`  |
| `truncate`                  | `finite`    |
| total timeout               | `finite`    |
| polling source              | `unbounded` |
| arbitrary `flat_map`        | `unknown`   |
| finite-expansion `flat_map` | `preserve`  |

Blocking operators use:

```python
require_bounded=True
```

When enabled:

| Input     | Result  |
| --------- | ------- |
| finite    | execute |
| unbounded | reject  |
| unknown   | reject  |

### 5.2 Ordering

```python
ordering: Literal[
    "preserve",
    "destroy",
    "establish",
]
```

Examples:

| Stage                    | Ordering  |
| ------------------------ | --------- |
| sequential map           | preserve  |
| ordered concurrent map   | preserve  |
| unordered concurrent map | destroy   |
| merge                    | destroy   |
| sort                     | establish |

Sort ordering details are derived from the existing normalized `SortConfRule` configuration rather than duplicated in a second public metadata model. `SortConfRule` already contains `field`, `dir`, and type information.

For multiple rules, the first configured rule is the primary key. Stable sorts must therefore be applied in reverse configuration order.

### 5.3 Side effects

```python
side_effects: Literal[
    "none",
    "idempotent",
    "non_idempotent",
]
```

### 5.4 Determinism

```python
determinism: Literal[
    "deterministic",
    "nondeterministic",
]
```

These opts influence retry safety, replay warnings, caching, and planner behavior.

---

## 6. Async execution and backpressure

> **Status: Partial.** **Shipped → [IMPLEMENTED.md §6](../IMPLEMENTED.md#6-async-execution-and-backpressure-shipped)**
> (bounded concurrency, order-preserving streaming via `async_map_stream`/`async_map_ordered_stream`).
> **Remaining:** true indexed reorder buffer, the `ordered=False` doc/behavior fix, and
> cancellation/cleanup below.

### 6.1 Bounded concurrency

Shipped as-built — see [IMPLEMENTED.md §6](../IMPLEMENTED.md#6-async-execution-and-backpressure-shipped).

### 6.2 Ordering

```python
ordered=True
```

preserves input order.

```python
ordered=False
```

emits completion order.

The current `async_map()` documentation says input order is preserved, but the bounded implementation appends callback results in completion order. This discrepancy must be corrected.

### 6.3 Reorder buffer

Ordered concurrent execution uses a bounded reorder buffer.

When the buffer fills:

* producers or workers pause
* the runtime waits for the missing earlier position
* ordering is never silently relaxed

### 6.4 Cancellation

> **Deferred / not yet implemented.** `on_cancel` does not exist. Async
> mid-iteration early close currently marks the pipe `FAILED`, and full `anext`
> cancellation is unspecified — P7 carryover (PHASE_CHECKLISTS § P7).

```python
on_cancel: Literal[
    "drain",
    "cancel_pending",
] = "cancel_pending"
```

On cancellation:

* stop accepting new work
* cancel queued work where supported
* running threads may finish
* process workers may be terminated after a grace period

### 6.5 Cleanup

When downstream execution stops early, Riko calls `aclose()` on active feeds when available.

This applies to:

* truncation
* timeout
* stage failure
* downstream cancellation
* consumer abandonment

When both execution and cleanup fail:

* use `ExceptionGroup` where available
* otherwise preserve the original exception and attach cleanup failure as context

---

## 7. Timeout

> **Status: Partial.** **Shipped → [IMPLEMENTED.md §7](../IMPLEMENTED.md#7-timeout-shipped)**
> (lifetime `total` timeout, sync + async `TimeoutIterator`). **Remaining:** the `idle`/`item`
> modes and the `on_timeout` policy described below.

```python
timeout(
    seconds,
    mode="total" | "idle" | "item",
    on_timeout="stop" | "error",
)
```

Default:

```python
on_timeout="stop"
```

Definitions:

* `total`: maximum lifetime of the timeout stage
* `idle`: maximum interval between emitted items
* `item`: maximum time waiting for the next upstream item

`on_timeout="stop"` is normal completion.

`on_timeout="error"` enters the configured error policy.

---

## 8. Union and merge

> **Status: Partial.** **Shipped → [IMPLEMENTED.md §8](../IMPLEMENTED.md#8-union-shipped)**
> (`union` sequential concatenation; the internal `async_merge` primitive). **Remaining:**
> the user-facing concurrent async `merge` operator below.

### 8.1 Union

Shipped as-built — see [IMPLEMENTED.md §8](../IMPLEMENTED.md#8-union-shipped).

### 8.2 Merge

> **Partial / deferred.** The internal `async_merge` primitive ships (see
> [IMPLEMENTED.md §8](../IMPLEMENTED.md#8-union-shipped)). The user-facing `merge` *operator*
> below (`scheduling`/`on_source_error`/`buffer_budget`/`per_source_limit`) does not exist
> yet.

`merge` is a distinct async-native concurrent operator.

```python
merge(
    feeds,
    scheduling="fair" | "ready",
    on_source_error="fail" | "continue",
    buffer_budget=128,
    per_source_limit=32,
)
```

Defaults:

```python
scheduling="fair"
on_source_error="fail"
```

Each input receives its own bounded channel.

Configuration is rejected when:

```text
buffer_budget < active source count
```

#### Scheduling

* `fair`: rotate among ready sources
* `ready`: emit whichever source becomes ready first

#### Source failures

With `on_source_error="fail"` the merge fails and closes remaining sources.

With `on_source_error="continue"` healthy sources continue and the final run status becomes `RunStatus.PARTIAL`.

#### State groups

Merged sources retain independent source-position domains.

Sources in the same dependency group:

* checkpoint together
* fail together
* stop together if one member fails

Independent groups may continue.

#### Inputs

The top-level collection of merge inputs is fixed at plan time.

A source may discover partitions internally, but new top-level feeds are not dynamically added to a running merge stage.

---

## 11. Retry policy

> **Status: Planned.** no retry policy in code.

```python
@dataclass(frozen=True)
class RetryPolicy:
    max_retries: int = 0
    backoff: Literal[
        "none",
        "constant",
        "exponential",
    ] = "exponential"
    retry_on: tuple[type[BaseException], ...] = ()
```

Default `max_retries=0`. There are no hidden automatic retries.

Retries occur before the final error policy:

```text
operation fails
→ configured retries
→ retries exhausted
→ fail | skip | dead_letter
```

Rules:

* lineage does not advance during retry
* ordered execution holds the affected position
* stable batch IDs are reused across retries
* only one layer should own retrying a given operation
* non-idempotent stages may not be retried unless explicitly authorized
* state-store CAS conflicts may be retried internally

Retry policies may be configured separately for:

* source operations
* record callables
* batch writes
* state stores
* error sinks
* disposition sinks

---

## 12. Errors and dispositions

> **Status: Planned.** only `on_error`/`error_key` + basic exception classes; no error/disposition sinks or drop policy.

### 12.1 Error policies

```python
error_policy: Literal[
    "fail",
    "skip",
    "dead_letter",
]
```

Semantics:

**Fail**

* stop execution
* do not advance the failed position

**Skip**

* requires `allow_data_loss=True`
* report the failure
* advance the position

**Dead letter**

* write to a durable error sink
* advance only after positive acknowledgement

### 12.2 Error sink

```python
class ErrorSink(Protocol):
    def write(
        self,
        failure: ItemFailure,
    ) -> Ack | Awaitable[Ack]: ...
```

### 12.3 Drop policy

```python
drop_policy: Literal[
    "complete",
    "external",
    "error",
] = "complete"
```

The value is inherited from the pipe and may be overridden per stage.

**Complete**

* emit no public acknowledgement
* internally mark the position successfully disposed
* allow checkpoint advancement

This preserves current filter behavior, where rejected records are silently omitted.

**External**

* send a structured disposition to a sink
* wait for acknowledgement before advancing

**Error**

* attempted dropping becomes a stage failure

### 12.4 Disposition sink

```python
class DispositionSink(Protocol):
    def write(
        self,
        disposition: ItemDisposition,
    ) -> Ack | Awaitable[Ack]: ...
```

Failure policy:

```python
on_disposition_failure: Literal[
    "fail",
    "warn",
    "ignore",
] = "fail"
```

Semantics:

| Policy | Advance | Run status |
| ------ | ------: | ---------- |
| fail   |      no | failed     |
| warn   |     yes | partial    |
| ignore |     yes | completed  |

### 12.5 Internal counters

Every stage tracks aggregate counts:

```text
emitted
dropped
dead_lettered
failed
retried
```

Per-item events are not required for the normal `complete` path.

---

## 13. Filter semantics

> **Status: Partial.** **Shipped → [IMPLEMENTED.md §13](../IMPLEMENTED.md#13-filter-semantics-shipped)**
> (`permit`/`combine`/`stop`). **Remaining:** the drop-policy / disposition semantics below.

A filtered-out item with `drop_policy="complete"` is immediately considered complete.

With `filter(stop=True)` the first rejected item:

* is considered intentionally dropped
* is marked complete
* permits checkpoint advancement through that item
* stops upstream consumption
* results in `RunStatus.COMPLETED`

---

## 16. Batch model

> **Status: Planned.** no `Batch`/`BatchPipe`/`BatchPolicy`.

```python
@dataclass(frozen=True)
class Batch:
    batch_id: str
    stream_id: str
    schema_id: str
    records: Sequence[Item]
    lineage: Lineage
    metadata: Mapping[str, object]
```

Batch pipes use:

```python
BatchPipe.map(
    fn: Callable[
        [Batch],
        Batch | Awaitable[Batch],
    ],
) -> BatchPipe
```

Record pipes and batch pipes both use `.map()`. The pipe type determines the callable input.

### 16.1 Batch policy

```python
@dataclass(frozen=True)
class BatchPolicy:
    max_records: int = 10_000
    max_bytes: int | None = None
    max_delay: float | None = None
```

Default `BatchPolicy(max_records=10_000)`. The first configured threshold reached flushes the batch.

Always flush before:

* state barriers
* schema changes
* source completion
* explicit checkpoint requests
* normal configured termination

On failure or external cancellation:

* stop accepting records
* do not flush an incomplete in-memory batch by default
* preserve already durable batches

Record-level fallback inside a failed batch remains configurable:

```text
allow
warn
error
```

---

---

> **Extracted from ROADMAP Appendix A.** Async/sync primitive reference for the runtime-semantics contract. `§N` references point back to [ROADMAP.md](../ROADMAP.md).

## A. Async primitive reference

Reference for every sync and async primitive relevant to riko's pipeline and pubsub
layers. Environments: **S** = sync (no async backend) · **T** = Twisted · **A** = asyncio ·
**Y** = anyio. Async iteration is pull-based; a `Feed` is defined by its iteration
mechanism, not by whether its source is finite or live.

### Sync iteration

| Primitive | riko mapping | Environments | Best suited for |
|---|---|---|---|
| `Iterator` / `Generator` | `Stream = Iterator[Item]` — primary pipeline I/O type | S · T · A · Y | Static sources: in-memory data, files read once, single URL fetch |
| `for item in stream` | Operator inner loop over `Stream` | S · T · A · Y | All sync operator parsers (`filter`, `count`, `sort`, …) |

### Async iteration

| Primitive | riko mapping | Environments | Best suited for |
|---|---|---|---|
| `AsyncIterator` / `AsyncGenerator` | `Feed = AsyncIterable[Item]` — async pipeline I/O type | A · Y | Any source consumed asynchronously — paginated APIs, WebSocket, SSE, live RSS, and bounded in-memory collections wrapped for concurrent I/O |
| `async for item in feed` | Operator inner loop over `Feed` | A · Y | Composer operators (`filter`, `timeout`, `truncate`, `uniq`, `union`) processing a `Feed` |

### Sync pubsub

| Primitive | riko mapping | Environments | Best suited for |
|---|---|---|---|
| Generator coroutine (`.send()`) | `sync_hub.receivers` in `riko/_pubsub` — named coroutines that receive items pushed by `send` module | S | Fan-out in sync pipelines; the only option without an async runtime |
| `collections.deque` | `sync_hub.queues` in `riko/_pubsub` — buffer between sender coroutine and polling consumer | S | Sync bridge between push (`.send()`) and pull (`next(receiver)`) sides |
| `time.sleep` polling (`wait` / `max_wait`) | Receiver loop in `riko/modules/receive.py` | S | Sync waiting for items from a named channel; unavoidable in sync context |
| `StreamState.PENDING` sentinel | Yielded by `receive` while no items are available | S | Signals caller that the receiver is alive but waiting; enables cooperative interleaving |

### Async pubsub

Async pubsub is an *addition*, not a replacement. Sync pipelines continue to use generator
coroutines + deque + polling unchanged.

| Primitive | riko mapping | Environments | Best suited for |
|---|---|---|---|
| `asyncio.Queue` | Async alternative to `sync_hub.queues` + polling | A · Y | Fan-out between async tasks; bounded queue gives natural backpressure |
| `anyio.create_memory_object_stream()` | Backend-agnostic named send/receive stream pair | Y | Fan-out on both asyncio and trio; naming mirrors `send`/`receive` semantics |
| `anyio.TaskGroup` / `asyncio.TaskGroup` | Structured concurrency; each consumer runs as a concurrent task | A · Y | Multiple async consumers; lifetime tied to the group |

### Structured concurrency and producers

| Primitive | riko mapping | Environments | Best suited for |
|---|---|---|---|
| `twisted.internet.defer.Deferred` | `async_pipe` return type; `bado.async_get`; `FileReader.deferred` | T | Single async result in Twisted; chained with `.addCallback` / `.addErrback` |
| `Cooperator` | `bado/itertools.py` `async_map` — rate-limited parallel async work | T | Cooperative multitasking in Twisted; controls concurrency without threads |
| `asyncio.Future` / `asyncio.Task` | Not currently used; anyio backend planned | A · Y | Single async result or background task in asyncio |
| `anyio.TaskGroup` / `asyncio.TaskGroup` | Replacement for `Cooperator` in `async_map` under anyio; also async pubsub fan-out | A · Y | Structured concurrency — all tasks complete before the group exits; preferred over `gather` for complex fan-out |
| `anyio.open_file` async read | anyio backend `async_read_file` replacement for `FileReader` | A · Y | File I/O under anyio; `async for chunk in f` needs no producer/consumer protocol |

### Fan-out

A `Feed` is consumed by a single consumer, like `Iterator`. For fan-out — delivering each
item to multiple independent consumers — use a `TaskGroup` with one bounded queue per
consumer. This is the async alternative to riko's sync `send`/`receive` pubsub, not a
replacement; natural backpressure comes from bounded queues rather than a polling interval.

---

> **Extracted from the runtime contract (§15, §22)** — stateful-operator and memory-limit
> execution semantics (borderline features, not part of the bare-bones contract).

## 15. Stateful operators

> **Status: Planned.** `StatefulItem` type exists but no checkpoint/persist machinery.

Stateful streaming stages declare:

```python
state_checkpoint: Literal[
    "replay",
    "persist",
] = "replay"
```

**Replay** — persist source checkpoints only. Rebuild operator state by replay after restart.

**Persist** — store versioned stage state with the checkpoint. A stage may use `persist` only when it provides a durable state codec.

---

## 22. Memory limits

> **Status: Planned.** no enforced memory/record limits.

Initial limits are item-count based:

```python
merge(
    buffer_budget=128,
    per_source_limit=32,
)
```

```python
map(
    concurrency=16,
    reorder_buffer=32,
)
```

```python
BatchPolicy(
    max_records=10_000,
)
```

These limits are enforced, not advisory.

Byte-aware accounting is deferred for:

* merge queues
* reorder buffers
* pending lineage
* error channels
* disposition channels
* batch builders

Universal deep Python-object size estimation is not required initially.

---
