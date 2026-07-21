# Riko Improvement Roadmap and Runtime Contract

This is the authoritative roadmap and runtime contract for riko. It consolidates the
former `ROADMAP.md` and `ASYNC_FEED_SUPPORT.md` into a single document. Tabled ideas that
are additive but not on the critical path (extra source pipes, protocol adapters,
orchestration and database integrations) live in [Shelf.md](Shelf.md).

## Index

**Part I — Runtime contract**

- [0. Architectural direction](#0-architectural-direction)
- [1. Product layers](#1-product-layers)
- [2. Core item and stream types](#2-core-item-and-stream-types)
- [3. Pipe behavior](#3-pipe-behavior)
- [4. Callable stages](#4-callable-stages)
- [5. Execution characteristics](#5-execution-characteristics)
- [6. Async execution and backpressure](#6-async-execution-and-backpressure)
- [7. Timeout](#7-timeout)
- [8. Union and merge](#8-union-and-merge)
- [9. Run status and exit codes](#9-run-status-and-exit-codes)
- [10. Delivery guarantee](#10-delivery-guarantee)
- [11. Retry policy](#11-retry-policy)
- [12. Errors and dispositions](#12-errors-and-dispositions)
- [13. Filter semantics](#13-filter-semantics)
- [14. Lineage and acknowledgements](#14-lineage-and-acknowledgements)
- [15. Stateful operators](#15-stateful-operators)
- [16. Batch model](#16-batch-model)
- [17. Riko Data Protocol](#17-riko-data-protocol)
- [18. State](#18-state)
- [19. Schema](#19-schema)
- [20. Batch transports](#20-batch-transports)
- [21. Manifest durability](#21-manifest-durability)
- [22. Memory limits](#22-memory-limits)
- [23. AnyIO and Twisted](#23-anyio-and-twisted)
- [24. Module registry and plugins](#24-module-registry-and-plugins)
- [25. Conversion and dataframe integration](#25-conversion-and-dataframe-integration)

**Part II — Implementation roadmap**

- [26. Implementation roadmap](#26-implementation-roadmap)
- [27. Explicit non-goals for the initial implementation](#27-explicit-non-goals-for-the-initial-implementation)

**Part III — HigherGov-first critical path**

- [28. Critical-path change](#28-critical-path-change)
- [29. Changes to the draft integration plan](#29-changes-to-the-draft-integration-plan)
- [30. Revised roadmap (HG-0 … HG-9)](#30-revised-roadmap-hg-0--hg-9)
- [31. Dependency change](#31-dependency-change)
- [32. HigherGov-first definition of done](#32-highergov-first-definition-of-done)

**Part IV — Async Feed integration**

- [33. Feed as the async I/O layer](#33-feed-as-the-async-io-layer)
- [34. Best HigherGov Feed use cases](#34-best-highergov-feed-use-cases)
- [35. Feed and schema drift](#35-feed-and-schema-drift)
- [36. Where Feed should not be used](#36-where-feed-should-not-be-used)
- [37. Recommended HigherGov Feed slices](#37-recommended-highergov-feed-slices)
- [38. Minimal Feed functionality HigherGov actually needs](#38-minimal-feed-functionality-highergov-actually-needs)

**Appendix**

- [A. Async primitive reference](#a-async-primitive-reference)

---

# Part I — Runtime contract

## 0. Architectural direction

Riko will retain its existing item-oriented pipeline model while adding:

* lazy asynchronous feeds
* bounded concurrency and backpressure
* callable `map` and `flat_map` stages
* logical record batches
* explicit schema and state handling
* the Riko Data Protocol, or RDP
* a Connect orchestration layer around the Core pipeline engine

The implementation should favor:

* explicit behavior over inference
* at-least-once delivery over claims of exactly-once processing
* bounded resource use
* compatibility with existing synchronous pipelines
* simple defaults
* conservative failure behavior
* execution plans that record all resolved assumptions

## 1. Product layers

### Riko Core

Core provides:

* synchronous and asynchronous pipelines
* built-in modules
* callable stages
* stream and Feed processing
* logical batches
* schema projection
* callbacks and sinks for errors and dispositions

### Riko Connect

Connect provides:

* source and destination orchestration
* RDP execution plans
* state persistence
* checkpointing
* batching
* manifests
* schema evolution
* run status
* retries
* merge coordination
* durable acknowledgements
* protocol compatibility

Core and Connect may remain in one distribution initially. Connect is a conceptual and architectural boundary rather than a required package split.

---

## 2. Core item and stream types

```python
type Item = (
    RikoDict
    | dict[str, RikoValue]
    | RSSEntry
    | DotDict[RikoValue]
)

type Items = Iterable[Item]
type Stream = Iterator[Item]
type Feed = AsyncIterable[Item]
```

`Stream` and `Feed` differ by iteration mechanism, not by whether the source is finite or live.

* `Stream` is synchronous iteration.
* `Feed` is asynchronous iteration.
* Boundedness is represented separately through opts.

The public asynchronous source type is:

```python
type AsyncSource = (
    Items
    | Feed
    | Awaitable[Items | Feed]
)
```

Each asynchronous execution resolves the source once and normalizes it to:

```python
AsyncIterator[Item]
```

The existing implementation currently accepts `Awaitable[Items]`, awaits it, and then passes synchronous iterables to module parsers. Chained async stages currently materialize the complete preceding stage through `_await_stream()`.

The new runtime must remove that materialization from normal stage chaining.

---

## 3. Pipe behavior

### 3.1 Synchronous pipes

`SyncPipe` remains synchronous and iterable:

```python
for item in pipe:
    ...
```

Its current parallel implementation materializes the complete source before pool submission:

```python
source_items = list(self.source)
```

This behavior may remain initially as an explicit limitation. Parallel synchronous execution is therefore not guaranteed to support infinite streams or bounded-memory source submission.

### 3.2 Asynchronous pipes

`AsyncPipe` supports lazy iteration:

```python
async for item in pipe:
    ...
```

Awaiting remains a compatibility terminal:

```python
result = await pipe
```

Awaiting collects the output and returns the historical synchronous stream-style result.

Internal chaining must pass the upstream pipe directly:

```python
return AsyncPipe(name, source=self)
```

It must not call `_await_stream()` between stages.

`AsyncCollection.async_pipe()` must similarly pass the collection itself rather than a materialized awaitable. The current implementation passes `_await_stream()`.

### 3.3 Feed reuse

Feeds behave like ordinary async iterators.

Riko will not:

* detect consumed feeds
* recreate them automatically
* raise a custom consumed-state exception

The underlying `StopAsyncIteration` behavior is authoritative.

---

## 4. Callable stages

### Stage execution options

Stage execution behavior is represented using the existing `Opts` typed dictionary.

Do not introduce:

* `StageTraits`
* `TraitOverrides`
* `@riko.stage`
* a separate traits mapping
* a separate trait-resolution object

### Extend `Opts`

```python
class Opts(TypedDict, total=False):
    # Existing options
    ftype: Required[BasicCastType]
    ptype: Required[BasicCastType]
    assign: str
    count: Literal["first", "all"]
    emit: bool
    extract: str
    field: str
    listize: bool
    objectify: bool
    parse: bool
    pollable: bool
    debug: bool
    skip_if: SkipIf

    # Execution characteristics
    boundedness: Literal[
        "preserve",
        "finite",
        "unbounded",
        "unknown",
    ]

    ordering: Literal[
        "preserve",
        "destroy",
        "establish",
    ]

    side_effects: Literal[
        "none",
        "idempotent",
        "non_idempotent",
    ]

    determinism: Literal[
        "deterministic",
        "nondeterministic",
    ]

    # Specialized execution requirements
    require_bounded: bool

    state_checkpoint: Literal[
        "replay",
        "persist",
    ]

    lineage_commit: Literal[
        "per_output",
        "on_complete",
    ]
```

`Defaults` remains reserved for module configuration defaults such as delimiters, field names, counts, and parsing behavior.

Execution characteristics belong in `Opts` because they describe how the wrapper and runtime execute the module rather than the contents of its `conf`.

### Defaults live in pipe modules

Each pipe module declares its own defaults through the existing `processor`, `operator`, or `splitter` decorator.

For example, `riko/modules/filter.py` declares behavior appropriate for filtering:

```python
@operator(
    boundedness="preserve",
    ordering="preserve",
    side_effects="none",
    determinism="deterministic",
    state_checkpoint="replay",
)
def pipe(stream, extraction, tuples, **kwargs):
    ...
```

`riko/modules/sort.py` declares:

```python
@operator(
    boundedness="preserve",
    ordering="establish",
    side_effects="none",
    determinism="deterministic",
    require_bounded=True,
)
def pipe(stream, extraction, tuples, **kwargs):
    ...
```

`riko/modules/union.py` declares:

```python
@operator(
    boundedness="unknown",
    ordering="preserve",
    side_effects="none",
    determinism="deterministic",
)
def pipe(stream, extraction, tuples, **kwargs):
    ...
```

Its boundedness is `unknown` by default because the additional streams may not have known boundedness.

The callable map module declares its own defaults in `riko/modules/map.py`:

```python
@processor(
    emit=True,
    boundedness="preserve",
    ordering="preserve",
    side_effects="none",
    determinism="deterministic",
)
def pipe(item, extraction, objconf, **kwargs):
    ...
```

The callable flat-map module declares:

```python
@processor(
    emit=True,
    boundedness="unknown",
    ordering="preserve",
    side_effects="none",
    determinism="deterministic",
)
def pipe(item, extraction, objconf, **kwargs):
    ...
```

`flat_map` defaults to unknown boundedness because an arbitrary callable may produce any number of children. A caller that knows the expansion is finite may override it.

### Normal call-site overrides

Overrides are ordinary pipe kwargs:

```python
pipe.map(
    fn=normalize,
    side_effects="idempotent",
    determinism="nondeterministic",
)
```

There is no `trait_overrides` argument.

The existing module preparation flow resolves the options:

```python
self.opts = Opts(self._opts)
self.opts.update(cast(Opts, kwargs))
```

Conceptually:

```text
module decorator options
        ↓
      _opts
        ↓ copy
       opts
        ↓ overlay invocation kwargs
resolved module options
```

### Callable method signatures

The public callable methods expose ordinary execution options:

```python
SyncPipe.map(
    fn,
    *,
    execution="inline",
    boundedness=None,
    ordering=None,
    side_effects=None,
    determinism=None,
    **kwargs,
)
```

```python
AsyncPipe.map(
    fn,
    *,
    ordered=True,
    execution="inline",
    reorder_buffer=None,
    boundedness=None,
    ordering=None,
    side_effects=None,
    determinism=None,
    **kwargs,
)
```

The optional values are passed through the existing pipe kwargs mechanism and become part of `Opts`.

`None` means that the method does not override the default declared in `riko/modules/map.py`.

The same applies to `flat_map`.

### Module-specific derived behavior

Options that depend on another module option remain the responsibility of that module.

For example, the map module begins with:

```python
ordering="preserve"
```

but resolves:

```python
ordered=False
```

to:

```python
ordering="destroy"
```

Likewise:

* `sort` derives ordering details from its normalized sort rules
* `timeout` derives boundedness from its mode and timeout behavior
* `merge` derives ordering from its scheduling mode
* reducers apply their configured `lineage_commit`
* stateful modules apply their configured `state_checkpoint`

This logic belongs in the respective pipe module, not in a centralized traits resolver.

### Planning and provenance

The execution planner may record the existing option dictionaries directly:

```python
declared = Opts(module._opts)
resolved = Opts(module.opts)
```

Provenance can be represented as ordinary plan data:

```python
{
    "boundedness": {
        "declared": "unknown",
        "resolved": "finite",
        "source": "call",
    }
}
```

This is execution-plan output, not a new runtime primitive.

### Revised decorator model

Built-in module:

```python
@operator(
    boundedness="preserve",
    ordering="preserve",
    side_effects="none",
    determinism="deterministic",
)
def pipe(...):
    ...
```

Call-site override:

```python
pipe.filter(
    ...,
    determinism="nondeterministic",
)
```

Resolved value:

```python
module.opts["determinism"] == "nondeterministic"
```

### Strict mode

Strictness is inherited from the pipe and may be overridden per stage.

```python
pipe = AsyncPipe(..., strict=True)
pipe.flat_map(fn)
pipe.flat_map(other_fn, strict=False)
```

With `strict=False`:

* the result is iterated without special type checking
* a mistakenly returned mapping may be flattened into its keys
* later stages may surface the error

With `strict=True`:

* a bare mapping result is rejected
* the result must be iterable or async iterable
* each emitted value must be a valid `Item`

### 4.3 Callable context

Callable stages use Riko's existing `Context` primitive and existing keyword propagation model.

#### Callable invocation

A callable stage invokes its function using the item followed by the normal pipe keyword arguments:

```python
result = fn(item, **kwargs)
```

The existing pipeline context is available as:

```python
kwargs["context"]
```

A callable that needs context may declare it explicitly:

```python
def transform(
    item: Item,
    *,
    context: Context,
    **kwargs,
) -> Item:
    ...
```

or access it from ordinary keyword arguments:

```python
def transform(item: Item, **kwargs) -> Item:
    context = kwargs["context"]
    ...
```

A callable that does not need specific keyword values may ignore them:

```python
def transform(item: Item, **_) -> Item:
    return item | {"normalized": True}
```

This matches the existing Riko module convention, where wrapped functions receive their parsed positional arguments followed by `**kwargs`.

#### Map API

```python
SyncPipe.map(
    fn,
    *,
    execution="inline",
    **kwargs,
)
```

```python
AsyncPipe.map(
    fn,
    *,
    ordered=True,
    execution="inline",
    reorder_buffer=None,
    **kwargs,
)
```

Invocation is conceptually:

```python
fn(item, **stage_kwargs)
```

where `stage_kwargs` is the ordinary resolved pipe kwargs and includes:

```python
{
    ...,
    "context": pipe.context,
}
```

#### Flat-map API

```python
SyncPipe.flat_map(
    fn,
    *,
    strict=None,
    drop_policy=None,
    **kwargs,
)
```

```python
AsyncPipe.flat_map(
    fn,
    *,
    strict=None,
    ordered=True,
    drop_policy=None,
    **kwargs,
)
```

Invocation uses the same rule:

```python
fn(item, **stage_kwargs)
```

There is no special context-aware flat-map path.

#### Context propagation

`PyPipe` already establishes the root context and includes it in normal pipe kwargs:

```python
self.context = context or Context(**kwargs)

self.kwargs.update(
    {
        "conf": self.conf,
        "inputs": self.inputs,
        "context": self.context,
    }
)
```

Callable stages should reuse that behavior rather than introducing a new context delivery mechanism.

The same `Context` instance is propagated through chained stages unless a narrower context is intentionally created for:

* an embedded module
* a Connect run
* a stage
* a source
* a positioned item

#### Scoped contexts

Per-stage or per-item execution metadata must not be written onto a single shared mutable context during concurrent execution.

When narrower execution metadata is needed, Riko derives a child `Context`:

```python
item_context = context.bind(
    stage_id=stage_id,
    source_id=position.source_id,
    position=position,
    schema_id=schema_id,
)
```

That child is then placed into the same ordinary kwargs mapping:

```python
item_kwargs = {
    **stage_kwargs,
    "context": item_context,
}

result = fn(item, **item_kwargs)
```

This is still normal Riko keyword propagation. It is not a separate public `call_kwargs` concept.

#### Inline and thread execution

Inline and thread workers receive the appropriate `Context` through the ordinary `context` keyword.

Each concurrent item receives its own bound child context when item-specific fields are required.

```python
fn(
    item,
    context=item_context,
    **kwargs,
)
```

Riko does not inspect whether the callable declares `context`, `**kwargs`, or neither. A callable used as a Riko stage is responsible for accepting the keyword arguments Riko supplies.

#### Process execution

Process execution preserves the same callable interface:

```python
fn(item, context=context, **kwargs)
```

Before submission, Riko validates and serializes the process-safe portions of the ordinary stage kwargs.

The `context` value remains a `Context`, reconstructed in the worker from a serializable snapshot.

No alternate process-only context type is exposed.

Runtime-owned objects that cannot cross a process boundary remain unavailable in the worker, including:

* open files and sockets
* state-store clients
* sinks
* callbacks
* task groups
* worker pools
* arbitrary registries

If the resolved kwargs cannot be safely serialized, planning fails before process workers start.

#### Callable contract

The practical callable protocol is:

```python
class ItemCallable(Protocol):
    def __call__(
        self,
        item: Item,
        **kwargs,
    ) -> Item | Awaitable[Item]:
        ...
```

The expected simple form is:

```python
def transform(item, **kwargs):
    ...
```

Context is supplied exactly as it is elsewhere in Riko:

```python
context = kwargs["context"]
```

There is no `with_context` parameter, no signature inspection, no `CallableContext` type,
and no `call_kwargs` primitive.

---

## 5. Execution characteristics

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

### 6.1 Bounded concurrency

Async mapping uses bounded worker concurrency.

It must not:

* create one task per source item
* materialize the entire source
* permit unbounded result buffering

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

### 8.1 Union

Historical `union` remains deterministic sequential concatenation:

```text
primary
→ other 1
→ other 2
```

The current implementation uses `itertools.chain`.

### 8.2 Merge

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

## 9. Run status and exit codes

```python
class RunStatus(Enum):
    COMPLETED = "completed"
    PARTIAL = "partial"
    FAILED = "failed"
    CANCELLED = "cancelled"
```

Default CLI exit codes:

```text
0 = completed
1 = failed
2 = CLI usage or configuration error
3 = partial
```

The partial exit code remains configurable.

---

## 10. Delivery guarantee

Riko Connect provides **at-least-once delivery**.

A source position advances only after its required downstream outputs or terminal dispositions are durable.

A failure between sink acknowledgement and checkpoint persistence may replay data.

Exactly-once processing is not claimed globally.

A sink may provide effective deduplication through:

* stable batch IDs
* idempotency keys
* native transactions
* merge/upsert semantics

These are sink capabilities, not universal Riko guarantees.

---

## 11. Retry policy

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

A filtered-out item with `drop_policy="complete"` is immediately considered complete.

With `filter(stop=True)` the first rejected item:

* is considered intentionally dropped
* is marked complete
* permits checkpoint advancement through that item
* stops upstream consumption
* results in `RunStatus.COMPLETED`

---

## 14. Lineage and acknowledgements

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

## 15. Stateful operators

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

## 16. Batch model

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

## 17. Riko Data Protocol

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

## 22. Memory limits

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

## 23. AnyIO and Twisted

AnyIO becomes the canonical runtime for new concurrency features:

* Feed support
* task groups
* bounded memory streams
* cancellation
* timeouts
* concurrent merge
* worker coordination

Twisted remains in compatibility and maintenance mode. Do not implement every new runtime semantic twice.

Before 1.0:

* remove Twisted if usage does not justify continued support, or
* retain it as an explicitly narrower legacy adapter

`AsyncIterable` is the pipeline-level abstraction. Async iteration is pull-based (`__anext__`
is awaited by the consumer), and a `Feed` is defined by its iteration mechanism, not by
whether the source is finite or live — a `Feed` may wrap a bounded in-memory collection
just as easily as a live source. The manual anyio integration guide is
[ANYIO_NO_SNIFFIO.md](ANYIO_NO_SNIFFIO.md).

---

## 24. Module registry and plugins

Initial registry:

* static built-in module registry
* unqualified names reserved for built-ins
* namespaces reserved now
* entry-point discovery deferred

One distribution and internal plugin architecture are sufficient initially. External connectors should use optional dependencies and plugin boundaries.

---

## 25. Conversion and dataframe integration

Meza owns conversion work.

Riko may temporarily provide adapters or protocols needed for the new architecture, but conversion implementation should eventually be upstreamed or finalized in Meza.

The batch/dataframe path should avoid pandas as a mandatory intermediary.

Logical Batch remains the Riko abstraction. Arrow, Narwhals, Polars, pandas, or SQL are execution representations selected by capability.

"Zero-copy" should be claimed only when the actual path avoids conversion or copying.

---

# Part II — Implementation roadmap

## 26. Implementation roadmap

The architectural milestones below describe the eventual RDP/Connect end state. The
**HigherGov-first critical path** in [Part III](#part-iii--highergov-first-critical-path)
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

* review Twisted usage
* remove or constrain Twisted before 1.0
* add entry-point plugin discovery if needed
* upstream temporary Meza adapters
* remove compatibility materialization stages where possible

---

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

The next practical artifact is a file-by-file change plan for `collections.py`,
`types/general.py`, the module wrappers, the new runtime package, and the RDP
specification.

---

# Part III — HigherGov-first critical path

Issue #176 moves schema work from a later RDP milestone into the **HigherGov minimum
viable integration**. HigherGov should not begin bulk transformation, scraping, or API
processing until the applicable ingestion boundary has been checked against a
version-controlled contract. The issue covers HigherGov CSV/API/scrape output and
Airtable metadata, and requires distinguishing an empty field from a removed field.

The roadmap therefore shifts from **protocol-first** to a **HigherGov vertical slice**
that deliberately implements reusable pieces of the eventual RDP architecture.

## 28. Critical-path change

Previous critical path:

```text
RDP specification
→ async Feed runtime
→ execution traits
→ batches/schema/state
→ Connect
→ application integration
```

Revised critical path:

```text
HigherGov acceptance fixtures
→ synchronous callable stages
→ schema contracts and drift detection
→ HigherGov concurrency integration
→ Riko sync-runtime hardening
→ async Feed
→ RDP and Connect
```

RDP remains the eventual architecture, but it no longer blocks Riko's first production use.
**Schema validation and synchronous callable execution become coequal P0 workstreams.**

## 29. Changes to the draft integration plan

The draft correctly identifies HigherGov's manual concurrency and repeated ingestion
transformations, but it attempts too much in the first migration (callable-stage
development, executor replacement, Selenium lifecycle redesign, CSV streaming, and a broad
rewrite of pandas transformations). The changes:

### 1. Do not use `itembuilder` as the bridge

`SyncPipe` dynamically resolves named Riko modules through `__getattr__`; it does not
provide a callable `.pipe(processor)` or `.output` interface. It already holds a direct
`source`, so callable stages build on that. The target API:

```python
flow = SyncPipe(
    source=dataframe.to_dict("records"),
    parallel=True,
    workers=workers,
    threads=not use_processes,
).map(processor)

result = pd.DataFrame(flow)
```

For an expanding callable:

```python
flow = SyncPipe(source=items).flat_map(processor)
```

This eliminates the artificial `itembuilder` source, `.pipe(processor)`, `.output`, and
the requirement that every callable yield an iterator. Most HigherGov functions are
one-input-to-one-output operations and should use `map`, not `flat_map`.

### 2. Do not rewrite the CSV transformations initially

Retain the existing vectorized pandas functions:

```python
process_grant_data(...)
process_sled_data(...)
process_fed_data(...)
process_forecast_data(...)
```

but insert schema validation immediately after each CSV load and before renaming or
transformation. Moving vectorized pandas work into Python dict processing would increase
migration surface, risk behavior drift, likely reduce performance, and make schema
validation harder to isolate. Row-oriented CSV processing can be revisited later.

### 3. Preserve batch-level Selenium lifecycle initially

The current implementation partitions the DataFrame into chunks, creates one driver inside
each chunk invocation, signs in, processes the chunk, and quits the driver. The first Riko
migration maps **chunk items**, not individual opportunities:

```python
items = [
    {"records": chunk.to_dict("records")}
    for chunk in dataframe_chunks
]

def scrape_chunk(item, **kwargs):
    frame = pd.DataFrame(item["records"])
    result = _scrape_highergov(frame)
    return {"records": result.to_dict("records")}
```

Riko replaces executor orchestration; HigherGov retains ownership of browser creation and
cleanup. A per-worker reusable browser can be considered later.

### 4. Preserve the existing redirect batch operation

The current redirect path uses authenticated Selenium batches, including driver recreation
after failures. Map the existing batch function; do not replace Selenium with `requests`
unless independently tested and proven equivalent:

```python
SyncPipe(
    source=redirect_batches,
    parallel=True,
    workers=max_workers,
).map(process_redirect_batch)
```

### 5. Keep `highergov.utils.riko` small

The first version should contain approximately:

```python
def parallel_map_dataframe(...): ...
def parallel_map_batches(...): ...
def fetch_content_parallel(...): ...
def call_api_parallel(...): ...
```

It should not initially contain CSV parsing, column pipe factories, Selenium resource
factories, thread-local resource management, process-worker support, or dataframe
transformation DSLs.

## 30. Revised roadmap (HG-0 … HG-9)

### Milestone HG-0 — Golden outputs and ingestion contracts

Before changing execution, capture representative fixtures for each HigherGov CSV type,
HigherGov opportunity API results, HigherGov scrape output by source type, and Airtable
Opportunities / Documents / NIGP metadata.

For each source, record expected fields, required fields, types, nullability, stable
external IDs when available, and representative payloads. Also capture before/after output
fixtures for the functions being parallelized. This separates execution regression from
upstream schema drift.

### Milestone HG-1 — Minimal synchronous callable stages

Implement only the synchronous callable functionality HigherGov needs.

New Riko modules `riko/modules/map.py` and `riko/modules/flatmap.py` use the existing
`processor` decorator and extend the existing `Opts`; defaults belong in each module:

```python
@processor(
    emit=True,
    boundedness="preserve",
    ordering="preserve",
    side_effects="none",
    determinism="deterministic",
)
def pipe(item, fn, objconf, **kwargs):
    return fn(item, **kwargs)
```

`flatmap.py` declares `boundedness="unknown"` and accepts multiple returned items.

Public methods:

```python
SyncPipe.map(fn, **kwargs)
SyncPipe.flat_map(fn, **kwargs)
```

Context is passed through the existing kwargs mechanism: `fn(item, context=self.context,
**kwargs)`. There is no signature inspection, `with_context`, `CallableContext`, traits
object, or `call_kwargs` primitive.

The existing sync parallel implementation materializes the source before pool mapping. That
is acceptable for the first HigherGov release because the targeted DataFrames and chunk
collections are already materialized; bounded streaming submission is an immediate
follow-up, not a prerequisite. `map()` defaults to ordered results; HigherGov functions
that reconstruct results by stable IDs may explicitly select unordered execution.

### Milestone HG-2 — Schema contract and drift core

This milestone is now part of the MVP.

Continue using raw Draft-07 JSON Schema as the authoritative contract. Do not make Pandera
the source of truth.

```python
OPPORTUNITY_CSV_SCHEMA = {
    "$schema": "http://json-schema.org/draft-07/schema#",
    "type": "object",
    "properties": {
        "Source ID": {"type": ["string", "null"]},
        "Title": {"type": ["string", "null"]},
        "Due Date": {"type": ["string", "null"]},
    },
    "required": ["Source ID", "Title"],
    "additionalProperties": True,
}
```

Minimal Riko API — functions and `TypedDict` reports, not a large schema object model:

```python
observed = inspect_schema(columns=dataframe.columns, dtypes=dataframe.dtypes)
report = diff_schema(expected=OPPORTUNITY_CSV_SCHEMA, observed=observed)
validate_schema(report, on_missing="error", on_extra="warn", on_type_change="error")
```

```python
class SchemaDriftReport(TypedDict):
    source: str
    added: list[str]
    removed: list[str]
    renamed: list[Rename]
    type_changes: list[TypeChange]
    nullable_changes: list[NullableChange]
    computed_field_errors: list[str]
```

Rename behavior: do not infer renames as authoritative from similar names. Airtable
identifies renames through stable field IDs; CSV/API report removed plus added; optional
fuzzy matches may appear under `rename_candidates`; never automatically remap based on
similarity.

Added columns normally warn, not fail. Removed required columns fail before transformation.
Removed optional columns default to warning unless downstream code requires that field
(policy may be `error`/`warn`/`allow` per source).

### Milestone HG-3 — Source-specific schema adapters

**HigherGov CSV** — inspect the CSV header before `pd.read_csv()` transformation work.
Replace the repeated per-mapping-key existence checks with one structured error:

```python
report = validate_csv_header(filepath, schema=GRANT_SCHEMA)
```

**HigherGov API** — before bulk execution, validate one representative live/metadata
result against the expected API contract, validate each returned item for required fields,
and normalize optional missing keys to `None`. Absence of an optional field must not
automatically mean it was removed.

**HigherGov scrape output** — validate the normalized output from each source-specific
scraper (`sled`, `sled_forecast`, `grant`, `sam`, `forecast`). Normalize all expected
output keys before validation:

```python
result = {**EXPECTED_EMPTY_FIELDS[source_type], **scraped_result}
```

This distinguishes a selector returning no value, a scraper forgetting a field, and a null
field. Selector failure is primarily data-health drift and is reported under field-health
failures in the same structured report.

**Airtable** — use the Metadata API before fetching records. Compare field ID, name, type,
computed-field configuration, and linked-table information. Reindex record DataFrames
against metadata fields so an entirely empty column still appears. Treat fields exposing
`.errorType` as computed-field health failures, as required by issue #176.

### Milestone HG-4 — HigherGov integration

1. **Content fetching** first — stateless, I/O-bound, easy to compare, independent of
   Selenium authentication.
2. **API calls** — extract `_api_call_single_item(item) -> Item`; run schema validation:
   input DataFrame schema → API preflight schema → parallel map → output record validation
   → DataFrame.
3. **Redirect batches** — keep the current batch callable and browser lifecycle, replace
   the outer `ThreadPoolExecutor`.
4. **Selenium scrape chunks** — keep `_scrape_highergov(chunk)`, use Riko only for chunk
   scheduling; no browser-per-thread persistence yet.
5. **Document API calls** — `fetch_document_data()` becomes a later low-risk `map` target
   after opportunity API processing is stable.

### Milestone HG-5 — Drift sentinel

Add a preflight command `validate_ingestion_sources()` that runs at the earliest point each
source can be inspected:

| Source        | Earliest validation point                                            |
| ------------- | ------------------------------------------------------------------- |
| Airtable      | pipeline start, via Metadata API                                    |
| HigherGov API | before bulk API calls                                               |
| HigherGov CSV | immediately after each CSV download                                 |
| Scrape output | after first normalized scrape result and on every result validation |

The contract: validate at the earliest available boundary, before transformation or
persistence. The sentinel returns one combined report routed through existing HigherGov
alerting.

### Milestone HG-6 — Sync executor hardening

After the first production integration: remove full-source materialization for pool
submission; bound in-flight tasks; add bounded ordered-result buffering; improve pool
cleanup on early consumer exit; add retry policy; add aggregate metrics; implement
fail/skip/dead-letter policies; add cancellation semantics; support explicit process-safe
context serialization. This work becomes production-driven because HigherGov exercises the
sync runtime.

### Milestone HG-7 — Optional row-stream CSV migration

Only after schema and concurrency integration is stable: evaluate row-stream CSV
processing, benchmark against pandas, migrate only row-local transformations, retain
vectorized and dataframe-wide operations in pandas. The decision is based on memory and
performance measurements, not line-count reduction.

### Milestone HG-8 — Async Feed

Then continue with `Feed = AsyncIterable[Item]`, lazy `AsyncPipe` chaining, AnyIO, bounded
async map, merge, cancellation, timeout, and async source normalization. HigherGov's
existing async OpenAI path can remain outside Riko until this milestone. See
[Part IV](#part-iv--async-feed-integration) for the Feed integration detail.

### Milestone HG-9 — RDP and Connect

Finally return to the RDP specification, Singer compatibility, batches, manifests, state
stores, checkpoints, CDC, schema evolution events, and Connect execution plans. The schema
contracts implemented for HigherGov become the first working slice of this architecture
rather than throwaway application validation.

## 31. Dependency change

HigherGov and current Riko both require Python 3.12+. Current Riko is version `0.69.0`.
During development, HigherGov should use a pinned Git revision or local workspace source:

```toml
[project]
dependencies = [
    "riko",
]

[tool.uv.sources]
riko = { path = "../riko", editable = true }
```

After the callable and schema APIs are released, replace that with a minimum released
version and update `uv.lock`.

## 32. HigherGov-first definition of done

The first production Riko milestone is complete when:

1. `SyncPipe.map()` and `flat_map()` exist using current module primitives.
2. HigherGov has no direct executor code in the selected migrated functions.
3. CSV, API, scrape, and Airtable boundaries have explicit schema contracts.
4. Removed required fields fail before transformation.
5. Added fields produce structured warnings.
6. Airtable empty fields and removed fields are distinguishable through metadata.
7. Selenium drivers are always closed.
8. Heroku worker limits remain unchanged.
9. Golden output fixtures match the pre-Riko implementation.
10. Schema drift and processing failures are reported separately.

---

# Part IV — Async Feed integration

HigherGov uses `Feed` as the **asynchronous I/O layer between DataFrame-oriented stages**,
not as a replacement for pandas or for the script-level pipeline.

## 33. Feed as the async I/O layer

The basic architecture:

```text
SQL / CSV / Airtable
        ↓
schema validation
        ↓
DataFrame or paginated source
        ↓
Feed[Item]
        ↓
bounded async I/O processing
        ↓
Feed[Item]
        ↓
DataFrame / batch sink
        ↓
existing pandas transforms, SQL, or Airtable
```

Feed avoids creating a list of every record and submitting all tasks at once. It provides
bounded submission, natural backpressure, results as they finish, normal Riko error/retry
handling, and cancellation through the pipeline.

## 34. Best HigherGov Feed use cases

### 1. OpenAI processing

The strongest Feed use case. The current implementation iterates the complete DataFrame,
builds `entry_args`, creates one task handle per entry, waits for the entire task group,
and merges all answers. Document summarization follows the same pattern. A Feed-based
implementation processes entries lazily with bounded concurrency:

```python
async def entry_feed(entries: pd.DataFrame):
    for row in entries.itertuples(index=False):
        yield {
            column: value
            for column, value in zip(entries.columns, row, strict=True)
        }


async def analyze_entry(item: dict, **kwargs) -> dict:
    description = str(
        {
            key: value
            for key, value in item.items()
            if key != "id" and pd.notna(value)
        }
    )

    return await _aanalyze_entry(
        description=description,
        entry_id=item["id"],
        question=kwargs["question"],
    )


flow = (
    AsyncPipe(source=entry_feed(entries_df), context=context)
    .map(analyze_entry, concurrency=MAX_CONCURRENT, ordered=False, question=question)
)

answers = [answer async for answer in flow]
```

**Recursive document summarization** — the chunks of one document must remain sequential
because later chunks may include prior summaries. Concurrency is **across documents**, not
across chunks within one document:

```python
async def summarize_document(item: dict, **kwargs) -> dict:
    summary = await _asummarize_text_recursive(
        chunks=item["summary_iterators"],
        large_doc=item["size_category"] == "large",
    )

    return {**item, "Summary": summary}
```

The existing OpenAI SDK retry configuration remains responsible for HTTP-level retries.
Riko should not independently retry the entire document callable unless explicitly
configured.

### 2. Webpage-content fetching

Scripts 08 and 13 perform blocking URL extraction through pandas `.apply()`. Feed executes
these blocking functions in a bounded thread pool:

```python
def fetch_finder_content(item: dict, **kwargs) -> dict:
    content = get_content_from_path(item["url"])

    if content and len(content) > 100_000:
        content = reduce_text(content, truncation=True)

    return {**item, "Finder Webpage Content": content}


flow = (
    AsyncPipe(source=finder_opportunity_feed(dataframe))
    .map(
        fetch_finder_content,
        execution="thread",
        concurrency=3,
        ordered=False,
        side_effects="none",
        determinism="nondeterministic",
    )
)
```

Preferable to `SyncPipe(parallel=True)` here because the containing script already has
async-compatible dependencies, Feed provides bounded submission, cancellation is meaningful
for long HTTP fetches, and results can be sent to Airtable in batches without waiting for
every page. The callable still receives Riko's normal kwargs; there is no special context
signature.

### 3. HigherGov API calls

The per-row body becomes an ordinary thread-executed callable (initially, because the
current implementation uses `requests`):

```python
def call_highergov_api(item: dict, **kwargs) -> dict:
    result = _api_call_single_item(item)
    return result if result is not None else item


flow = (
    AsyncPipe(source=dataframe_feed(cleaned_higher_df))
    .map(
        call_highergov_api,
        execution="thread",
        concurrency=4,
        ordered=False,
        side_effects="none",
        determinism="nondeterministic",
    )
)
```

Later the callable may use an async HTTP client; no other HigherGov code changes because
`AsyncPipe.map()` supports synchronous and asynchronous callables.

The Feed source validates its input schema before yielding anything, and returned API
records are validated before downstream transformation:

```python
async def validated_api_input_feed(dataframe, schema):
    report = inspect_dataframe_schema(dataframe, schema)

    if report["removed_required"]:
        raise SchemaDriftError(report)

    for item in dataframe_records(dataframe):
        yield item


flow = (
    AsyncPipe(source=validated_api_input_feed(df, INPUT_SCHEMA))
    .map(call_highergov_api, execution="thread", concurrency=4)
    .map(validate_api_result)
)
```

### 4. HigherGov document fetching

Script 09 becomes an incremental Feed pipeline:

```text
opportunity
    ↓ flat_map
fetch document metadata → document
    ↓
extract text → chunk document → reuse cached summary or summarize → clean and hash
    ↓
batch database write
```

```python
flow = (
    AsyncPipe(source=opportunity_feed(logic_mapped))
    .flat_map(fetch_documents, execution="thread", concurrency=4, ordered=False)
    .map(normalize_document)
    .map(extract_document_text, execution="thread", concurrency=3, ordered=False)
    .map(summarize_if_needed, concurrency=MAX_CONCURRENT, ordered=False)
    .map(hash_document)
)
```

`fetch_documents()` uses `flat_map` because one opportunity can return multiple documents.
Do **not** flatten summary chunks into independent records — a large document's summary
chunks are ordered and stateful; keep them inside the document item and let the
summarization callable consume the iterator sequentially.

### 5. Airtable pagination and updates

A Feed source adapter wraps Airtable pagination, loading and validating authoritative
metadata before yielding records:

```python
async def airtable_feed(table, *, view: str | None = None, schema: dict):
    metadata = await anyio.to_thread.run_sync(load_table_metadata, table)
    validate_airtable_metadata(metadata, schema)

    async for page in airtable_pages(table, view=view):
        for record in page:
            yield normalize_airtable_record(record, metadata)
```

Updates remain batches:

```python
async for batch in achunks(flow, 10):
    await anyio.to_thread.run_sync(
        partial(
            opportunities_table.batch_update,
            list(batch),
            replace=False,
            typecast=True,
        )
    )
```

Feed adds value even though Airtable requires batched writes: records read page by page,
transformations begin before the full table loads, update batches write incrementally, and
bounded queues prevent fetchers from outrunning writes. DataFrame-wide steps (duplicate
detection, whole-table masks) still load a DataFrame.

### 6. Selenium scraping

Feed replaces the outer executor but retains the chunk-level browser lifecycle. Represent
each chunk as one Feed item:

```python
async def dataframe_chunk_feed(dataframe: pd.DataFrame, size: int):
    for start in range(0, len(dataframe), size):
        yield {
            "start": start,
            "records": dataframe.iloc[start : start + size].to_dict("records"),
        }


def scrape_chunk(item: dict, **kwargs) -> dict:
    chunk = pd.DataFrame(item["records"])
    result = _scrape_highergov(chunk)
    return {"start": item["start"], "records": result.to_dict("records")}


flow = (
    AsyncPipe(source=dataframe_chunk_feed(opportunities, 15))
    .map(
        scrape_chunk,
        execution="thread",
        concurrency=1 if IS_HEROKU else 3,
        ordered=False,
        side_effects="non_idempotent",
        determinism="nondeterministic",
    )
)
```

Bounded scheduling and cancellation without thread-local drivers. Explicit worker resource
setup/cleanup (`worker_resource=ChromeDriverResource(...)`) is not needed for the first
integration.

### 7. URL redirect resolution

Use a Feed of batches; each result remains `{"results": {...}, "failures": [...]}` and a
final reducer combines dictionaries and failure lists. Do not convert to one URL per driver
invocation:

```python
flow = (
    AsyncPipe(source=url_batch_feed(pairs, batch_size=20))
    .map(
        process_redirect_batch,
        execution="thread",
        concurrency=3,
        ordered=False,
        side_effects="none",
        determinism="nondeterministic",
    )
)
```

## 35. Feed and schema drift

Feed makes schema validation a source-boundary guarantee.

**CSV source** — validation occurs before the first row is yielded:

```python
async def highergov_csv_feed(path, schema, mappings):
    header = read_csv_header(path)
    report = diff_schema(schema, header)

    if report["removed_required"]:
        raise SchemaDriftError(report)

    for row in csv_dict_rows(path):
        yield normalize_csv_row(row, mappings)
```

**Airtable source** — Metadata API → validate field IDs/types → normalize empty fields →
start yielding records.

**API source** — validate input dataframe → call API → validate each returned payload →
yield normalized result.

**Scrape source** — web scraping has no authoritative metadata, so validate the normalized
output shape and field health:

```python
result = {**EMPTY_SCRAPE_RESULT[source_type], **scraped}
validate_scrape_result(result, source_type)
```

A missing output key is schema drift. A present key whose value is `None` is an empty scrape
result. This directly supports issue #176's empty-versus-removed distinction.

## 36. Where Feed should not be used

**Keep pandas for whole-dataset operations** — do not convert these merely to use Riko:
`combine_first` and DataFrame joins, global duplicate detection, mask calculations
depending on the entire dataset, vectorized date and string transformations,
source-specific CSV transformations, schema reports requiring the complete column set, and
Airtable batch payload formatting. For these stages, `Feed → collect into DataFrame →
pandas transformation → optionally return to Feed` is valid.

**Keep SQL as a durable script boundary** — Feed initially operates **inside** each script.
Do not attempt `script 01 → one live Feed → script 17`. Use `script input → Feed
processing → existing SQL/Airtable output`. This limits recovery scope and avoids requiring
checkpoints and Connect before HigherGov can use Feed.

## 37. Recommended HigherGov Feed slices

**Slice 1: OpenAI and webpage content** — implement lazy `AsyncPipe` chaining, AnyIO
runtime, bounded async `map`, synchronous callable thread offload, ordered/unordered
results, cancellation and `aclose()`. Migrate OpenAI document summarization, OpenAI entry
analysis, Finder webpage content, and Opportunity webpage content.

**Slice 2: HigherGov APIs** — add async/thread callable retries, `flat_map`, structured
errors, per-stage counters. Migrate opportunity API calls, document API calls, document
content extraction.

**Slice 3: blocking stateful resources** — migrate Selenium scrape chunks and redirect
batches. Keep browser ownership inside each chunk callable.

**Slice 4: paginated ingestion and batched sinks** — add Airtable page source, SQL
row/chunk source, batch/chunk operator, incremental Airtable and SQL sinks.

## 38. Minimal Feed functionality HigherGov actually needs

HigherGov does not need the entire Connect/RDP roadmap to use Feed. Its initial dependency:

```text
Feed = AsyncIterable[Item]

AsyncPipe accepts:
    Items
    Feed
    Awaitable[Items | Feed]

AsyncPipe.map:
    lazy
    bounded concurrency
    ordered=True by default
    thread execution for blocking callables

AsyncPipe.flat_map:
    lazy expansion
    bounded concurrency
    sync or async iterable results

Lifecycle:
    cancellation
    aclose()
    bounded result queues

Context:
    existing Context passed through normal kwargs
```

It does not initially require manifests, checkpoint lineage, CDC, RDP messages, Arrow
batches, merge dependency groups, process execution, or persistent stage state.

The practical HigherGov architecture is therefore:

```text
pandas for dataset logic
Feed for concurrent I/O
schema contracts at source boundaries
SQL/Airtable for durable boundaries
```

Feed is a near-term HigherGov requirement rather than a post-HigherGov roadmap item.

---

# Appendix

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
| Generator coroutine (`.send()`) | `_registry` in `riko/utils.py` — named coroutines that receive items pushed by `send` module | S | Fan-out in sync pipelines; the only option without an async runtime |
| `collections.deque` | `_receive_queue` in `riko/utils.py` — buffer between sender coroutine and polling consumer | S | Sync bridge between push (`.send()`) and pull (`next(receiver)`) sides |
| `time.sleep` polling (`wait` / `max_wait`) | Receiver loop in `riko/modules/receive.py` | S | Sync waiting for items from a named channel; unavoidable in sync context |
| `StreamState.PENDING` sentinel | Yielded by `receive` while no items are available | S | Signals caller that the receiver is alive but waiting; enables cooperative interleaving |

### Async pubsub

Async pubsub is an *addition*, not a replacement. Sync pipelines continue to use generator
coroutines + deque + polling unchanged.

| Primitive | riko mapping | Environments | Best suited for |
|---|---|---|---|
| `asyncio.Queue` | Async alternative to `_receive_queue` + polling | A · Y | Fan-out between async tasks; bounded queue gives natural backpressure |
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
