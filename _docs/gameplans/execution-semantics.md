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

| pipe                        | Opt         |
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

| pipe                     | Ordering  |
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
* pipe failure
* downstream cancellation
* consumer abandonment

When both execution and cleanup fail:

* use `ExceptionGroup` where available
* otherwise preserve the original exception and attach cleanup failure as context

---

## Execution-mode adaptation (`Pipeline` sync ↔ async)

> **Status: Planned.** Owns the sync↔async adaptation layer behind the public
> [`Pipeline`](release-readiness.md) (definition) / `SyncExecution` / `AsyncExecution` (one-shot,
> built fresh per `iter`/`aiter`). API shape → [release-readiness.md § 4](release-readiness.md);
> decorator DX → [callable-pipes.md](callable-pipes.md); source ingest →
> [feed-native-streaming.md § 7.1](feed-native-streaming.md). AnyIO/Asyncer are **private** — never
> surfaced through `riko`/`riko.ext`.

### Native-wins resolution matrix

The resolver returns a module *definition* (its optional `sync_pipe`/`async_pipe` slots), then the
execution selects an implementation for its mode. A native implementation always wins; adapt only
when the matching side is absent.

| Module implements | Sync execution | Async execution |
|---|---|---|
| sync + async | native sync | native async |
| sync only | native sync | sync on a worker |
| async only | async on the execution portal | native async |

### Async-only under sync execution — one persistent portal

A single `SyncExecution` owns **one** lazily-created AnyIO `BlockingPortal`, created only when an
async component is first encountered and reused by every async step, the async source, and any
async pub/sub for the life of that execution. **Never one portal per item.**

- Long-lived async resources (HTTP clients, DB pools, task groups, channels, async generators) stay
  on that portal's loop.
- If an async step yields an async iterator, `anext()` bridges through the same portal; `aclose()`
  runs through it during teardown.
- The portal closes deterministically on normal exhaustion, explicit close, and exceptions;
  original exceptions propagate.
- Two independent executions of the same reusable `Pipeline` get **independent** portal lifetimes.

If the `async` extra is absent and a pipeline needs an async-only module, raise a clear riko-level
error (install `riko[async]`) — never a deep AnyIO/Asyncer `ImportError`.

### Sync-only under async execution — worker policy

Unknown synchronous extension code is potentially blocking and is **safe by default**: it runs on a
worker thread, not the event-loop thread. riko does **not** inspect imports, bytecode, names,
timing, or source to guess whether a `def` blocks. The policy is the single `execution` `Opts` field
(declared on the decorator, overridable per call; the same field used by
[callable-pipes.md](callable-pipes.md)):

| `execution` | Behavior |
|---|---|
| `auto` (default) | native async awaited inline; unknown sync under async → worker |
| `inline` | explicitly safe to run on the event-loop thread (riko's own pure transforms) |
| `thread` | worker thread |
| `process` | existing process machinery; do not expand scope to support it |

Built-in pure transforms are marked `inline` internally because riko owns and tests them.
Third-party modules declare nothing for correctness — absence of metadata stays safe.

### Do not auto-detect blocking

There is no reliable general test for whether arbitrary Python blocks (it may return immediately,
call `requests`, read a file, sleep, or run CPU-heavy Python depending on input). Optimize known
cases via the `execution` policy; never make safety depend on a heuristic.

### Sync islands (Deferred — first performance follow-up)

To avoid one worker hop per tiny pure transform under async execution, the execution plan *may*
group consecutive `inline`/`thread` sync-only processors into one worker segment
(`[async fetch] → [filter → strreplace → rename] → [async write]`). Grouping is driven by resolved
implementation kind + `execution` policy, **never** by inferring whether code blocks. Safe only
across consecutive sync steps with no native-async step, operator/splitter/whole-stream boundary,
ordering/concurrency boundary, or resource/side-effect boundary between them. **Not shipped** — the
planner (`riko/_execution/plan.py`) must allow adding it without API changes; benchmark
before/after.

### Non-goals

Do not turn the whole runtime into one async engine, force sync execution through AnyIO, spin up an
async runtime per record, or expose AnyIO/Asyncer types. The cheap native sync path stays cheap.

---

## 7. Timeout

> **Status: Partial.** **Shipped → [IMPLEMENTED.md §7](../IMPLEMENTED.md#7-timeout-shipped)**
> (lifetime `total` timeout, sync + async `TimeoutIterator`). **Remaining:** the `idle`/`item`
> modes, the `on_timeout` policy described below, and the unbounded async
> `receive` wait (§7.1).

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

* `total`: maximum lifetime of the timeout pipe
* `idle`: maximum interval between emitted items
* `item`: maximum time waiting for the next upstream item

`on_timeout="stop"` is normal completion.

`on_timeout="error"` enters the configured error policy.

### 7.1 `receive` has no async timeout

The sync and async `receive` pipes wait on entirely different terms, and only
the sync one can give up:

| | Waits by | Honors `max_wait` |
|---|---|---|
| `parser` (sync) | polling the queue, yielding `StreamState.PENDING` | yes — closes and stops |
| `async_parser` | blocking until the sender finishes | **no** |

`async_parser` reads only `objconf.name`; `wait`, `max_wait` and `max_len` are
sync-only (`max_len` is applied in `_register_receiver`, which the async path
never calls). Measured:

```text
async_pipe(conf={"name": "nosender", "max_wait": 1})   ->  hangs indefinitely
```

So a mistyped receiver name, or a sender that errors before starting, wedges an
async pipeline with no diagnostic — while the same mistake on the sync path
times out and closes cleanly. This is the same hazard as `§7`'s `item` mode: a
wait with no upper bound.

Fixing it means wrapping the subscribe in `anyio.fail_after`/`move_on_after`
using `max_wait`, and deciding which of `on_timeout="stop"` (return what
arrived) or `"error"` applies — so it should land **with** the `on_timeout`
policy above rather than as a separate patch. Until then the docstrings state
that the async path has no timeout.

### 7.2 A blocked `anext` outlives the deadline

`AsyncTimeoutIterator.__anext__` bounds the *intervals between* items, not the wait
itself:

```python
async def __anext__(self) -> T:
    self._raise_if_expired()
    item = await anext(self.aiter)   # unbounded
    self._raise_if_expired()
    return item
```

If the source stalls, the second check is never reached — so the deadline holds only
while items keep arriving, which is the opposite of what a timeout is for and the same
unbounded-wait hazard as § 7.1. The claim that `timeout` bounds an infinite `Feed`
therefore holds only for a *productive* infinite feed.

The fix is an AnyIO cancel scope around the `await` carrying the **remaining** deadline
(`move_on_after(remaining)`), with expiry mapping onto the same
`on_timeout="stop" | "error"` policy as § 7 — so it lands with that policy rather than
before it. `move_on_after` is also what
[feed-native-streaming § 2](feed-native-streaming.md#2-per-pipe-audit) assumes for the
Feed-native `timeout` port; doing it twice is wasted work.

Registered as [correctness-audit **R14**](correctness-audit.md#8-open-defect-register--features-branch-audit).

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

A source may discover partitions internally, but new top-level feeds are not dynamically added to a running merge pipe.

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
* non-idempotent pipes may not be retried unless explicitly authorized
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

The value is inherited from the pipe and may be overridden per pipe.

**Complete**

* emit no public acknowledgement
* internally mark the position successfully disposed
* allow checkpoint advancement

This preserves current filter behavior, where rejected records are silently omitted.

**External**

* send a structured disposition to a sink
* wait for acknowledgement before advancing

**Error**

* attempted dropping becomes a pipe failure

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

Every pipe tracks aggregate counts:

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
>
> **Consumer:** the runtime `batch_feed`/`batch_stream` primitives and their use in streaming
> `write`/`split`/reducers are planned in [feed-native-streaming.md](feed-native-streaming.md), which
> delegates to this `BatchPolicy` rather than exposing a separate per-pipe chunk concept.

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
>
> **Alignment audit (separate concern).** Which of these `bado` helpers to remove/replace/keep as
> AnyIO adds equivalents (4.14 task handles, `functools.reduce`, async `itertools`) — plus the async
> benchmarking/profiling methodology — lives in
> [bado-anyio-alignment.md](bado-anyio-alignment.md). This appendix owns their *semantics*; that
> gameplan owns the *cleanup*.

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

Stateful streaming pipes declare:

```python
state_checkpoint: Literal[
    "replay",
    "persist",
] = "replay"
```

**Replay** — persist source checkpoints only. Rebuild operator state by replay after restart.

**Persist** — store versioned pipe state with the checkpoint. A pipe may use `persist` only when it provides a durable state codec.

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
