# Production Step

## Implementation sequence

The work should be divided into five independently shippable changes:

1. **Callable synchronous stages**

   * `SyncPipe.map()`
   * `SyncPipe.flat_map()`
   * existing `Context` propagation
   * `Opts` extensions
   * module defaults

2. **Schema contracts and drift detection**

   * generic Draft-07 schema comparison
   * structured drift reports
   * HigherGov source adapters

3. **Feed runtime**

   * lazy `AsyncPipe`
   * bounded concurrency
   * thread execution
   * backpressure and cleanup

4. **HigherGov migration**

   * OpenAI calls
   * webpage extraction
   * HigherGov APIs
   * Selenium chunks
   * schema validation at ingestion boundaries

5. **RDP specification and Connect implementation**

   * protocol messages
   * capabilities
   * state
   * batches
   * manifests
   * CDC

The first two changes provide immediate HigherGov value without waiting for the complete asynchronous or protocol architecture.

---

# 1. `riko/collections.py`

## Current constraints

`SyncPipe` currently assigns its pool mapping function to:

```python
self.map = self.pool.imap
```

or:

```python
self.map = self.pool.imap_unordered
```

That instance attribute prevents adding a public `SyncPipe.map()` method until it is renamed.

Chained `SyncPipe` instances also do not explicitly propagate the existing `Context`; they create a new child pipe using execution settings but omit `context`, `inputs`, ordering, and chunksize.

`AsyncPipe` currently materializes every preceding stage through `_await_stream()` before constructing the next stage.

## Phase 1 changes: synchronous callable stages

### 1.1 Rename internal pool mapping attributes

Replace:

```python
self.map
```

with:

```python
self._pool_map
```

in both:

* `SyncPipe`
* `SyncCollection`

Examples:

```python
self._pool_map = self.pool.imap
self._pool_map = self.pool.imap_unordered
self._pool_map = map
```

This change must occur before defining the public `.map()` method.

### 1.2 Store resolved execution settings

Change:

```python
ordered: bool | None = False
```

to:

```python
ordered: bool | None = None
```

`None` means that the pipe constructor did not override the module’s declared `Opts`.

Resolution should occur after importing the module:

```python
declared_opts = getattr(self.pipe, "opts", {})
self.ordered = (
    ordered
    if ordered is not None
    else declared_opts.get("ordered", False)
)
```

Legacy modules without an `ordered` option retain the historical unordered parallel behavior.

The callable `map` module declares:

```python
ordered=True
```

in its own module decorator.

### 1.3 Add a private chaining helper

Both explicit methods and `__getattr__` should use one private helper:

```python
def _chain(self, name: str, **kwargs):
    pipe_kwargs = {
        "parallel": self.parallel,
        "threads": self.threads,
        "pool": self.pool if self.reuse_pool else None,
        "reuse_pool": self.reuse_pool,
        "workers": self.workers,
        "chunksize": self.chunksize,
        "ordered": self.ordered,
        "inputs": self.inputs,
        "context": self.context,
    }

    pipe_kwargs.update(kwargs)
    return type(self)(name, source=self, **pipe_kwargs)
```

This fixes context propagation without introducing another context mechanism.

### 1.4 Add explicit callable methods

```python
def map(self, func, **kwargs):
    return self._chain("map", func=func, **kwargs)
```

```python
def flat_map(self, func, **kwargs):
    return self._chain("flatmap", func=func, **kwargs)
```

Do not add:

```python
pipe(callable)
```

`pipe` already has other meanings in the current collection API, and `map`/`flat_map` state the cardinality contract more clearly.

### 1.5 Preserve ordinary kwargs and context behavior

A call such as:

```python
flow.map(
    normalize,
    side_effects="none",
    metadata={"source": "highergov"},
)
```

must eventually invoke:

```python
normalize(
    item,
    context=flow.context,
    inputs=flow.inputs,
    conf=flow.conf,
    side_effects="none",
    metadata={"source": "highergov"},
)
```

There is no:

* `with_context`
* signature inspection
* `CallableContext`
* `call_kwargs`

The callable must accept the normal keyword arguments supplied by riko.

### 1.6 Keep initial synchronous materialization

The current parallel path converts the complete source to a list before pool mapping.

For the first HigherGov integration, retain this behavior because the target inputs are already materialized DataFrames or explicit chunk lists.

Mark bounded pool submission as a follow-up rather than combining it with the callable API work.

### 1.7 Fix pool cleanup boundaries

The current pool is only closed inside `_stream()` when:

```python
not self.reuse_pool
```

Add an explicit:

```python
def close(self) -> None:
    ...
```

and context-manager support:

```python
def __enter__(self):
    return self

def __exit__(self, *_):
    self.close()
```

Do not close a reused pool after each stage.

This matters for HigherGov exceptions and early exits.

---

## Phase 3 changes: Feed-aware `AsyncPipe`

### 1.8 Widen the source type

Replace:

```python
source: Awaitable[Items] | None
```

with:

```python
source: AsyncSource | None
```

where `AsyncSource` is defined in `types/general.py`.

### 1.9 Remove stage materialization from chaining

Replace:

```python
kwargs = {
    "source": self._await_stream(),
    "connections": self.connections,
}
```

with:

```python
kwargs = {
    "source": self,
    "connections": self.connections,
    "inputs": self.inputs,
    "context": self.context,
}
```

`AsyncPipe` itself is a `Feed`, so it should be the source of the next stage.

### 1.10 Retain awaiting as a terminal operation

Keep:

```python
result = await pipe
```

as a compatibility terminal that collects the Feed:

```python
async def _await_stream(self) -> Stream:
    return iter([item async for item in self])
```

Internal chaining must not call it.

### 1.11 Delegate source normalization

`AsyncPipe._stream()` should begin with:

```python
source = normalize_source(self.source)
```

from the new runtime package.

It should not directly decide whether the source is:

* synchronous
* asynchronous
* awaitable

### 1.12 Delegate processor concurrency

For processor modules:

```python
async for item in map_feed(
    source,
    pipeline,
    opts=resolved_opts,
):
    yield item
```

For the `flatmap` module:

```python
async for item in flat_map_feed(
    source,
    pipeline,
    opts=resolved_opts,
):
    yield item
```

### 1.13 Preserve legacy operator compatibility

Existing async operator wrappers accept synchronous `Stream` values rather than `Feed`. Their type definitions and implementation remain based on synchronous iterators.

Initially:

```text
Feed
→ materialize at legacy operator
→ invoke existing async operator
→ normalize output back to Feed
```

The resolved plan and debug logging should identify that stage as materializing.

Do not block HigherGov Feed support on converting every existing operator.

### 1.14 Add asynchronous cleanup

Add:

```python
async def aclose(self) -> None:
    ...
```

It should close:

* the active iterator
* the upstream Feed when it has `aclose()`
* runtime worker channels

### 1.15 Update `AsyncCollection`

Replace:

```python
return AsyncPipe(source=self._await_stream(), **kwargs)
```

with:

```python
return AsyncPipe(
    source=self,
    context=context,
    **kwargs,
)
```

The current implementation materializes the collection before the new pipe begins.

---

# 2. `riko/types/general.py`

## 2.1 Add Feed types

Add `AsyncIterable` and `AsyncIterator` imports.

```python
type Feed = AsyncIterable[Item]
type AsyncStream = AsyncIterator[Item]
```

Keep the existing meanings:

```python
type Items = Iterable[Item]
type Stream = Iterator[Item]
```

Do not redefine a list or arbitrary iterable as `Stream`.

## 2.2 Add the asynchronous source union

```python
type AsyncSource = (
    Items
    | Feed
    | Awaitable[Items | Feed]
)
```

This preserves current `Awaitable[Items]` support while allowing direct synchronous and asynchronous sources.

## 2.3 Add callable result types

```python
type SyncMapResult = Item
type AsyncMapResult = Item | Awaitable[Item]

type SyncFlatMapResult = Iterable[Item]
type AsyncFlatMapResult = (
    Iterable[Item]
    | AsyncIterable[Item]
    | Awaitable[Iterable[Item] | AsyncIterable[Item]]
)
```

These are static aliases only. They do not create a generic public `Pipe[T]` abstraction.

## 2.4 Extend the existing `Opts`

`Opts` remains the only runtime/module option container.

Add:

```python
class Opts(TypedDict, total=False):
    # Existing fields remain unchanged.

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

    execution: Literal[
        "inline",
        "thread",
        "process",
    ]

    ordered: bool
    concurrency: int
    buffer_size: int

    strict: bool

    drop_policy: Literal[
        "complete",
        "external",
        "error",
    ]

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

Do not place default values here.

Defaults belong in each pipe module’s decorator.

## 2.5 Do not add RDP wire types here

`types/general.py` should remain focused on pipeline and module types.

Later protocol types belong in:

```text
riko/types/rdp.py
```

Schema-report types belong in:

```text
riko/types/schema.py
```

This prevents `general.py` from becoming a protocol catch-all.

## 2.6 Transitional async parser types

Do not immediately replace all current async parser types with Feed inputs.

Add separate transitional aliases if needed:

```python
type FeedProcessor = Callable[..., Feed]
type FeedOperator = Callable[..., Feed]
```

The current `AsyncPipeParser` remains available for legacy modules until their wrappers are converted.

---

# 3. `riko/modules/__init__.py`

## Current behavior to retain

`Module` already has the desired resolution flow:

```text
decorator options
→ self._opts
→ copied into self.opts
→ invocation kwargs override self.opts
```

`prepare()` performs that copy and update today.

The change is to make this flow safer and expose its declared defaults to the runtime.

## 3.1 Filter invocation kwargs before updating `Opts`

Current code effectively casts all kwargs to `Opts`:

```python
self.opts.update(cast_type(Opts, kwargs))
```

That allows unrelated values such as `context`, `conf`, and arbitrary user parameters to enter `self.opts`.

Add:

```python
OPT_KEYS = frozenset(
    Opts.__required_keys__ | Opts.__optional_keys__
)
```

Then:

```python
updates = {
    key: value
    for key, value in kwargs.items()
    if key in OPT_KEYS
}

self.opts.update(cast_type(Opts, updates))
```

All original kwargs still pass to the wrapped module or user callable. They simply do not become module execution options.

## 3.2 Expose declared module options

When constructing a wrapper, add:

```python
setattr(wrapper, "opts", Opts(self._opts))
```

The wrapper already exposes metadata such as:

* `type`
* `name`
* `sub_type`
* `pollable`

The new `opts` attribute lets `collections.py` and the runtime resolve module defaults before invocation.

This is still an `Opts` dictionary, not a new traits object.

## 3.3 Optionally expose resolved options

For debugging and planning, the wrapper may expose the most recently resolved options:

```python
setattr(wrapper, "resolved_opts", self.opts)
```

Do not use this mutable value as the authoritative option source for concurrent runs.

The execution runtime should create its own local `Opts` copy:

```python
resolved = Opts(wrapper.opts)
resolved.update(call_overrides)
```

## 3.4 Keep ordinary kwargs propagation

The processor wrappers already invoke the wrapped function using:

```python
pipe(*casted, **kwargs)
```

Retain this behavior.

A callable module receives `context` through those existing kwargs.

## 3.5 Do not inspect user callable signatures

The wrappers must never branch based on:

* whether the callable declares `context`
* whether it declares `**kwargs`
* positional parameter count
* annotations

A callable used with riko is responsible for accepting riko’s standard kwargs.

## 3.6 Avoid mutable global resolution during Feed execution

The decorator’s `Module` instance is shared by the imported module wrapper.

For the Feed runtime, avoid depending on mutable `Module.opts` after concurrent execution begins.

Use:

```python
declared = Opts(wrapper.opts)
resolved = Opts(declared)
resolved.update(option_overrides)
```

as local runtime state.

A larger rewrite making every decorator invocation immutable is unnecessary for the HigherGov milestone.

---

# 4. New callable modules

## 4.1 `riko/modules/map.py`

Add:

```python
DEFAULTS = Defaults()
```

Declare module defaults in the decorator:

```python
@processor(
    DEFAULTS,
    emit=True,
    boundedness="preserve",
    ordering="preserve",
    side_effects="none",
    determinism="deterministic",
    execution="inline",
    ordered=True,
)
def pipe(item, extraction, objconf, **kwargs):
    func = kwargs.pop("func")
    return func(item, **kwargs)
```

The actual implementation should copy kwargs before removing `func`:

```python
call_kwargs = dict(kwargs)
func = call_kwargs.pop("func")
return func(item, **call_kwargs)
```

`call_kwargs` here is only a local implementation variable. It is not a public concept or API.

Add an async version:

```python
@processor(
    DEFAULTS,
    isasync=True,
    emit=True,
    boundedness="preserve",
    ordering="preserve",
    side_effects="none",
    determinism="deterministic",
    execution="inline",
    ordered=True,
)
async def async_pipe(item, extraction, objconf, **kwargs):
    ...
```

It calls the function and awaits the result only when the result is awaitable.

Do not use `inspect.signature`.

## 4.2 `riko/modules/flatmap.py`

Defaults:

```python
@processor(
    DEFAULTS,
    emit=True,
    boundedness="unknown",
    ordering="preserve",
    side_effects="none",
    determinism="deterministic",
    execution="inline",
    ordered=True,
    strict=False,
    drop_policy="complete",
)
```

The synchronous parser:

1. invokes the callable;
2. optionally validates the returned iterable;
3. returns it for flattening.

Strict mode controls all flat-map result validation.

With `strict=False`, a returned mapping follows ordinary iteration behavior.

With `strict=True`:

* a bare mapping is rejected;
* every result must be an `Item`;
* a non-iterable result raises a clear error.

A zero-output result uses the resolved `drop_policy`.

## 4.3 Update module listings

Add:

```python
"map",
"flatmap",
```

to `__transformers__`.

The public method remains:

```python
flat_map()
```

while the module filename remains:

```text
flatmap.py
```

to match existing module naming conventions.

---

# 5. New runtime package

Create only the files required by the first Feed implementation. Do not create empty lineage, batching, or checkpoint modules yet.

## 5.1 `riko/runtime/__init__.py`

Re-export the small public internal surface:

```python
from .feed import (
    close_feed,
    flat_map_feed,
    map_feed,
    normalize_source,
)
```

This package is internal infrastructure. `AsyncPipe` remains the public API.

## 5.2 `riko/runtime/feed.py`

This is the first implementation file.

### `normalize_source`

```python
async def normalize_source(
    source: AsyncSource | None,
) -> AsyncIterator[Item]:
    ...
```

Behavior:

1. await the source if it is awaitable;
2. use `aiter()` when it is asynchronous;
3. adapt a synchronous iterable to an async iterator;
4. yield nothing for `None`.

Synchronous iteration initially occurs inline.

A later `source_execution="thread"` option can offload blocking source iteration.

### `invoke`

Private helper:

```python
async def _invoke(
    func,
    item,
    *,
    execution,
    kwargs,
):
    ...
```

Behavior:

* `inline`: invoke and await the result when necessary;
* `thread`: use `anyio.to_thread.run_sync`;
* `process`: raise `NotImplementedError` initially or use the later process adapter.

HigherGov initially needs only `inline` and `thread`.

### `map_feed`

```python
async def map_feed(
    source: Feed,
    func,
    *,
    opts: Opts,
    kwargs: Mapping[str, object],
) -> AsyncIterator[Item]:
    ...
```

Requirements:

* bounded work queue;
* bounded result queue;
* fixed worker count;
* no task per source item;
* `ordered=True` preserves source order;
* `ordered=False` emits completion order;
* downstream backpressure stops source consumption;
* cancellation closes the source.

### Ordered implementation

Assign each source item a monotonically increasing sequence number:

```text
0, 1, 2, 3, ...
```

Workers produce:

```python
(sequence, result)
```

The ordered consumer retains only bounded out-of-order results until the next sequence arrives.

The configured result buffer is a hard limit.

### `flat_map_feed`

Use the same worker infrastructure, but emit zero or more child items for each parent.

For ordered execution:

```text
parent 0 children
→ parent 1 children
→ parent 2 children
```

Children from one parent retain callable iteration order.

For unordered execution, parent result groups may complete in any order.

### `close_feed`

```python
async def close_feed(feed) -> None:
    close = getattr(feed, "aclose", None)

    if close:
        await close()
```

Preserve the primary execution exception if cleanup also fails.

## 5.3 `riko/runtime/errors.py`

Add in the second runtime change, not the initial Feed PR.

Define:

```python
class RunStatus(Enum):
    COMPLETED = "completed"
    PARTIAL = "partial"
    FAILED = "failed"
    CANCELLED = "cancelled"
```

And structured errors:

```python
class ItemFailure(TypedDict):
    item: Item
    stage: str
    exception_type: str
    message: str
    attempt: int
```

Do not inject `_riko_error` into business records.

The current roadmap proposes error fields inside records, but that has been superseded by the separate error-channel decision.

## 5.4 Later runtime files

Create these only when their implementation begins:

```text
riko/runtime/merge.py
riko/runtime/lineage.py
riko/runtime/batch.py
riko/runtime/state.py
riko/runtime/manifest.py
```

Do not create placeholder modules during the HigherGov Feed work.

## 5.5 Existing `riko/bado/itertools.py`

Do not build the new Feed runtime on the existing `async_map`.

The current AnyIO plan still proposes:

```python
items = list(iterable)
await asyncio.gather(...)
```

which is incompatible with lazy Feed processing and bounded submission.

Keep `bado.itertools.async_map` for compatibility until old async modules are migrated.

---

# 6. Existing `Context`

## `riko/__init__.py`

Extend and reuse the current `Context`; do not introduce a second type.

The current primitive contains:

* `verbose`
* `test`
* `describe_input`
* `describe_dependencies`
* `inputs`
* `submodule`

### Immediate change

Fix `Context.__repr__`, which currently overwrites rather than appends portions of its content.

### HigherGov/Feed requirement

Ensure the same root context reaches chained sync and async stages.

No per-item execution metadata is required for the first HigherGov Feed implementation.

### Later extension

When lineage and Connect are implemented, add:

```python
run_id
stage_id
source_id
position
schema_id
metadata
```

and a shallow `bind()` method.

That change should not block callable stages or Feed.

---

# 7. Schema drift implementation

Schema drift is a HigherGov prerequisite, but it should not be embedded directly in `collections.py`.

## 7.1 `riko/types/schema.py`

Add report types:

```python
class SchemaField(TypedDict, total=False):
    type: str | list[str]
    nullable: bool
    required: bool
    external_id: str
```

```python
class FieldTypeChange(TypedDict):
    field: str
    expected: object
    observed: object
```

```python
class SchemaDriftReport(TypedDict):
    source: str
    added: list[str]
    removed: list[str]
    rename_candidates: list[dict[str, str]]
    type_changes: list[FieldTypeChange]
    nullable_changes: list[str]
    computed_field_errors: list[str]
```

## 7.2 `riko/schema.py`

Start with one simple module.

Functions:

```python
def inspect_records_schema(...) -> dict: ...
def diff_schema(...) -> SchemaDriftReport: ...
def validate_schema(...) -> SchemaDriftReport: ...
```

The expected schema is a Draft-07 mapping or boolean schema.

Behavior:

* missing required field → error
* added field → warning by default
* removed optional field → warning by default
* incompatible type change → error
* rename similarity → advisory candidate only
* stable external field IDs → authoritative rename detection

Do not require pandas in this module.

HigherGov can provide DataFrame column and dtype information through an adapter.

## 7.3 HigherGov repository adapters

In HigherGov, add:

```text
data_enrichment_pipeline/schema/contracts.py
data_enrichment_pipeline/schema/airtable.py
data_enrichment_pipeline/schema/dataframe.py
data_enrichment_pipeline/schema/preflight.py
```

These files:

* convert DataFrame dtypes to generic schema observations;
* inspect CSV headers;
* query Airtable Metadata;
* report `.errorType` computed-field failures;
* call the generic riko schema functions.

This satisfies issue #176 without making pandas or Airtable part of riko core.

---

# 8. RDP specification

## 8.1 Add `docs/RDP.md`

Use one authoritative specification file initially.

Do not split it into many documents until the wire protocol stabilizes.

Required sections:

### 1. Scope

Define RDP as:

* an input superset of Singer;
* a strict Singer-compatible profile;
* a native profile for batches, manifests, schema changes, and richer state.

### 2. Message framing

Define JSONL framing and required `type` discrimination.

Singer-compatible messages:

```text
SCHEMA
RECORD
STATE
```

Native messages:

```text
BATCH
SCHEMA_CHANGE
ACTIVATE_VERSION
```

### 3. Catalog

Specify:

```text
ConfiguredRikoCatalog
```

as canonical, with Singer catalog adapters.

### 4. Schema

State:

* Draft-07 is authoritative;
* the original unresolved schema is retained;
* references resolve through an immutable registry;
* tabular projections may be lossy;
* projection loss must be reported.

### 5. State

Define:

* `STREAM`
* `GLOBAL`
* `LEGACY`

State values remain source-authoritative.

Singer `STATE.value` must be preserved exactly.

### 6. Capabilities

Define required and optional capabilities.

* unknown required capability → fail
* unknown optional capability → ignore or warn

### 7. Batches and manifests

Specify:

* logical batch envelope;
* schema ID;
* lineage envelope;
* manifest commit sequence;
* stable batch ID;
* object checksum and size.

### 8. Transport

Define:

```text
manifest
ipc-stream
auto
```

with the restricted direct IPC fast path.

### 9. CDC

Specify:

* insert
* update
* delete
* delete projection rules
* native versus Singer compatibility behavior

### 10. Delivery guarantee

State that Riko Connect is at-least-once by default.

Do not claim global exactly-once behavior.

### 11. Safe degradation

Codify:

```text
performance difference
→ automatic fallback

representation difference
→ explicit projection

correctness difference
→ fail unless explicitly authorized
```

### 12. Run status

Define:

```text
COMPLETED
PARTIAL
FAILED
CANCELLED
```

and CLI exit codes:

```text
0 completed
1 failed
2 usage/configuration
3 partial
```

### 13. Conformance examples

Include examples for:

* Singer schema/record/state
* native batch
* schema change
* stream state
* global state
* delete record
* manifest acknowledgement
* unsupported required capability

## 8.2 Add examples after prose stabilizes

Later add:

```text
docs/rdp/examples/singer.jsonl
docs/rdp/examples/native-batch.jsonl
docs/rdp/examples/schema-change.jsonl
docs/rdp/examples/cdc.jsonl
```

## 8.3 Add machine-readable schemas later

After at least one reader and writer implementation agree:

```text
docs/rdp/schema/message.schema.json
docs/rdp/schema/catalog.schema.json
docs/rdp/schema/manifest.schema.json
docs/rdp/schema/checkpoint.schema.json
```

Do not make machine-readable protocol schemas the first deliverable. Otherwise the project will encode unsettled details too early.

---

# 9. Documentation updates

## `docs/ROADMAP.md`

Rewrite the milestone order around:

1. callable sync stages;
2. schema drift;
3. Feed;
4. HigherGov migration;
5. RDP/Connect.

Remove or replace:

* `SyncPipe.pipe(callable)`
* error fields injected into records
* broad row-wise DataFrame rewrites
* worker-local Selenium as an initial requirement
* assumptions that DataFrame export is already enabled

The current roadmap still treats `.pipe(callable)` as the primary API.

## `docs/ANYIO_SUPPORT.md`

Replace the list-materializing `async_map` proposal with the new bounded Feed runtime.

Clarify:

* AnyIO is the new runtime for Feed;
* Twisted remains a compatibility path;
* new concurrency semantics are not implemented twice;
* legacy async modules may materialize temporarily.

## `README.rst`

Add examples:

```python
SyncPipe(source=items).map(normalize)
```

```python
async for result in (
    AsyncPipe(source=feed)
    .map(fetch, execution="thread", concurrency=4)
):
    ...
```

Add an explicit example showing context:

```python
def normalize(item, **kwargs):
    context = kwargs["context"]
    ...
```

---

# 10. Tests

## `tests/test_collections.py`

Add tests for:

* public `.map()` no longer conflicting with internal pool mapping;
* ordered parallel map;
* unordered parallel map;
* `flat_map()` expansion;
* zero-result flat-map behavior;
* chained stages retaining the same `Context`;
* pool reuse;
* explicit pool closing;
* backward-compatible dynamic module chaining.

An existing collections test file is already present and should remain the central compatibility suite.

## `tests/test_modules_map.py`

Test:

* ordinary callable kwargs;
* context access;
* no signature inspection;
* sync map;
* async map;
* callable exception propagation;
* module-declared `Opts`;
* call-site option overrides.

## `tests/test_modules_flatmap.py`

Test:

* list results;
* generators;
* zero outputs;
* strict bare-mapping rejection;
* non-strict mapping iteration;
* invalid child items;
* drop-policy resolution.

## `tests/test_runtime_feed.py`

Test:

* synchronous source normalization;
* asynchronous source normalization;
* awaitable source normalization;
* lazy first-result behavior;
* bounded source consumption;
* ordered completion;
* unordered completion;
* bounded reorder buffer;
* thread execution;
* async callable execution;
* cancellation;
* upstream `aclose()`;
* downstream early exit.

## `tests/test_schema.py`

Test the issue #176 matrix:

* no drift;
* removed required field;
* removed optional field;
* added field;
* type change;
* nullability change;
* authoritative rename by external ID;
* advisory rename candidate;
* computed-field error.

## Future `tests/test_rdp_conformance.py`

Test each example in `docs/rdp/examples` against the reader and writer.

---

# 11. Pull request boundaries

## PR 1 — Callable stages

Files:

```text
riko/collections.py
riko/types/general.py
riko/modules/__init__.py
riko/modules/map.py
riko/modules/flatmap.py
riko/__init__.py
tests/test_collections.py
tests/test_modules_map.py
tests/test_modules_flatmap.py
```

Definition of done:

* HigherGov can use `SyncPipe.map()` and `flat_map()`;
* context is preserved;
* no new traits or context primitive exists;
* existing tests remain green.

## PR 2 — Schema drift core

Files:

```text
riko/schema.py
riko/types/schema.py
tests/test_schema.py
docs/SCHEMA.md
```

HigherGov changes occur in a separate HigherGov PR.

## PR 3 — Feed runtime

Files:

```text
riko/runtime/__init__.py
riko/runtime/feed.py
riko/collections.py
riko/types/general.py
pyproject.toml
tests/test_runtime_feed.py
docs/ANYIO_SUPPORT.md
```

Definition of done:

* chained `AsyncPipe` stages are lazy;
* bounded map supports inline and thread execution;
* awaiting still collects;
* legacy async operators still work through materialization.

## PR 4 — HigherGov Feed migration

Initial targets:

```text
OpenAI summarization
OpenAI entry analysis
Finder webpage extraction
Opportunity webpage extraction
HigherGov API calls
document API calls
```

Keep pandas for whole-dataset transforms.

## PR 5 — RDP specification

Files:

```text
docs/RDP.md
docs/ROADMAP.md
docs/rdp/examples/*
```

Protocol implementation follows after the specification and HigherGov Feed behavior have been exercised in production.

# Roadmap Supplement: Correcting the Reverted `features` Work

This supplement defines the correct implementation of the features attempted in commit `59093ea`.

It supersedes the original roadmap sections covering:

* callable pipeline stages
* per-item errors
* worker initialization
* pool cleanup
* async modernization
* thread-safe `send` and `receive`
* related documentation and tests

The implementation should follow the settled architecture:

* use `map` and `flat_map`, not `pipe(callable)`
* extend the existing `Opts`
* use the existing `Context`
* preserve ordinary kwargs propagation
* do not inspect callable signatures
* do not inject errors into business records
* do not introduce a worker-local public primitive
* use Feed and AnyIO for new asynchronous execution
* preserve Twisted only as a compatibility layer
* keep pool and resource ownership explicit

---

# Upstream changes

## 1. Callable pipeline stages

### Problem with the reverted implementation

The documentation used:

```python
SyncPipe(source=items).pipe(func)
```

but `SyncPipe.pipe()` was not implemented. Attribute lookup would instead attempt to import:

```text
riko.modules.pipe
```

The existing `aggregate` module also applies a callable to the entire stream rather than providing the required one-item-to-one-item operation.

### Correct API

Add two explicit methods:

```python
SyncPipe.map(func, **kwargs)
SyncPipe.flat_map(func, **kwargs)

AsyncPipe.map(func, **kwargs)
AsyncPipe.flat_map(func, **kwargs)
```

Cardinality is explicit:

```text
map:
    Item → Item

flat_map:
    Item → Iterable[Item]
```

Do not add:

```python
pipe(func)
```

### Required internal rename

`SyncPipe` currently uses an instance attribute named `map` for pool execution.

Rename it before adding the public method:

```python
self.map
```

becomes:

```python
self._pool_map
```

The same rename should be applied to `SyncCollection`.

### Correct chaining implementation

Use one private chaining method:

```python
class SyncPipe(PyPipe):
    def _chain(self, name: str, **kwargs):
        pipe_kwargs = {
            "parallel": self.parallel,
            "threads": self.threads,
            "pool": self.pool if self.reuse_pool else None,
            "reuse_pool": self.reuse_pool,
            "workers": self.workers,
            "chunksize": self.chunksize,
            "ordered": self.ordered,
            "inputs": self.inputs,
            "context": self.context,
        }

        pipe_kwargs.update(kwargs)
        return type(self)(name, source=self, **pipe_kwargs)

    def map(self, func, **kwargs):
        return self._chain("map", func=func, **kwargs)

    def flat_map(self, func, **kwargs):
        return self._chain("flatmap", func=func, **kwargs)

    def __getattr__(self, name):
        if name.startswith("_") or name in {"keys", "values", "items", "get"}:
            raise AttributeError(name)

        return self._chain(name)
```

This preserves:

* execution configuration
* pool ownership
* ordering
* inputs
* the existing `Context`

### New modules

Add:

```text
riko/modules/map.py
riko/modules/flatmap.py
```

#### `map.py`

```python
from inspect import isawaitable

from riko.types.general import Defaults

from . import processor

DEFAULTS = Defaults()


@processor(
    DEFAULTS,
    emit=True,
    boundedness="preserve",
    ordering="preserve",
    side_effects="none",
    determinism="deterministic",
    execution="inline",
    ordered=True,
)
def pipe(item, extraction, objconf, **kwargs):
    func = kwargs["func"]
    forwarded = {key: value for key, value in kwargs.items() if key != "func"}
    return func(item, **forwarded)


@processor(
    DEFAULTS,
    isasync=True,
    emit=True,
    boundedness="preserve",
    ordering="preserve",
    side_effects="none",
    determinism="deterministic",
    execution="inline",
    ordered=True,
)
async def async_pipe(item, extraction, objconf, **kwargs):
    func = kwargs["func"]
    forwarded = {key: value for key, value in kwargs.items() if key != "func"}
    result = func(item, **forwarded)
    return await result if isawaitable(result) else result
```

The local `forwarded` variable is only an implementation detail. It is not a public `call_kwargs` abstraction.

#### `flatmap.py`

The defaults belong in the module:

```python
@processor(
    DEFAULTS,
    emit=True,
    boundedness="unknown",
    ordering="preserve",
    side_effects="none",
    determinism="deterministic",
    execution="inline",
    ordered=True,
    strict=False,
    drop_policy="complete",
)
```

Strict behavior:

```text
strict=False:
    iterate the returned value normally

strict=True:
    reject bare mappings
    reject non-iterables
    validate every emitted Item
```

There is no signature inspection.

---

## 2. Existing `Context` propagation

### Problem with the reverted implementation

Normal pipeline chaining failed to pass the original `Context` into child pipes.

A new context could therefore be created at each stage, breaking shared pipeline configuration and future Connect metadata.

### Correct implementation

`PyPipe` remains responsible for creating or accepting the root context:

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

Every chained pipe passes:

```python
context=self.context
```

Callables receive it through ordinary kwargs:

```python
def normalize(item, **kwargs):
    context = kwargs["context"]
    ...
```

Do not add:

* `with_context`
* `CallableContext`
* signature inspection
* a second callable invocation path

### Immediate `Context` cleanup

Fix the existing representation method:

```python
def __repr__(self):
    content = (
        f"verbose={self.verbose}, "
        f"test={self.test}, "
        f"describe_input={self.describe_input}, "
        f"describe_dependencies={self.describe_dependencies}, "
        f"inputs={self.inputs}, "
        f"submodule={self.submodule}"
    )
    return f"Context({content})"
```

### Deferred context binding

Do not add per-item `Context.bind()` during the first callable-stage pull request.

Add it later with lineage and Connect, when these fields are needed:

```text
run_id
stage_id
source_id
position
schema_id
metadata
```

---

## 3. Extend `Opts`

### Problem with the reverted implementation

Execution behavior was added directly to collection constructors without integrating the existing module option system.

### Correct implementation

Extend the existing `Opts` typed dictionary:

```python
class Opts(TypedDict, total=False):
    # Existing fields remain.

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

    execution: Literal[
        "inline",
        "thread",
        "process",
    ]

    ordered: bool
    concurrency: int
    buffer_size: int
    strict: bool

    drop_policy: Literal[
        "complete",
        "external",
        "error",
    ]

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

Do not put defaults in `Opts`.

Each pipe module declares its own defaults.

### Correct option filtering

`Module.prepare()` must not copy arbitrary invocation kwargs into `Opts`.

Use:

```python
OPT_KEYS = frozenset(
    Opts.__required_keys__ | Opts.__optional_keys__
)

updates = {
    key: value
    for key, value in kwargs.items()
    if key in OPT_KEYS
}

self.opts.update(cast(Opts, updates))
```

Values such as these remain ordinary kwargs:

```text
context
inputs
func
metadata
headers
session
question
```

They must not become execution options.

### Wrapper metadata

Expose declared options on wrapped modules:

```python
setattr(wrapper, "opts", Opts(self._opts))
```

The runtime can resolve options locally:

```python
resolved = Opts(wrapper.opts)
resolved.update(call_overrides)
```

Do not create a separate traits object.

---

## 4. Error handling

### Problem with the reverted implementation

The reverted commit converted failures into ordinary records:

```python
{
    "_riko_item": item,
    "_riko_error": str(exc),
}
```

This contaminates the business-data stream and changes failure behavior silently.

### Correct initial implementation

The default remains:

```text
fail
```

A callable exception propagates unless an explicit error policy is configured.

Core supports callback-based reporting:

```python
def on_error(failure):
    ...
```

Use a structured failure object:

```python
class ItemFailure(TypedDict):
    item: Item
    stage: str
    exception_type: str
    message: str
    attempt: int
```

Initial policies:

```python
error_policy: Literal[
    "fail",
    "skip",
    "dead_letter",
] = "fail"
```

#### `fail`

```text
report callback if configured
raise original exception
do not advance the item
```

#### `skip`

Requires:

```python
allow_data_loss=True
```

Behavior:

```text
report callback
emit nothing
consider the item complete
```

#### `dead_letter`

Requires an `ErrorSink`:

```python
class ErrorSink(Protocol):
    def write(
        self,
        failure: ItemFailure,
    ) -> Ack | Awaitable[Ack]: ...
```

The item completes only after a positive durable acknowledgement.

### What belongs in the first pull request

For the initial synchronous callable-stage PR:

```text
default propagation
on_error callback
explicit skip with allow_data_loss=True
```

Defer durable dead-letter sinks until the error-channel runtime PR.

### Callback failures

Use the already settled callback-failure policy:

```python
on_error_failure: Literal[
    "fail",
    "warn",
    "ignore",
] = "warn"
```

Ordinary observer callbacks default to warning.

Durable error or disposition sinks default to failure.

---

## 5. Worker initialization and resources

### Problem with the reverted implementation

The reverted implementation:

* created a `threading.local`
* passed it to `worker_init`
* injected it into callables as `_local`
* rejected process workers
* lost the setting when chaining

This introduces a specialized public convention and incomplete lifecycle management.

### Correct short-term implementation

Do not add a Riko worker-resource primitive yet.

For HigherGov’s initial integration, keep resource ownership inside the mapped callable or batch callable.

Example:

```python
def scrape_chunk(item, **kwargs):
    driver = create_driver()

    try:
        sign_in(driver)
        return scrape_records(driver, item["records"])
    finally:
        driver.quit()
```

Riko handles scheduling. HigherGov handles browser ownership.

This is the least surprising behavior and guarantees cleanup.

### Optional low-level pool initializer

If the existing pool initializer is retained as an advanced constructor option, it should use the standard pool interface:

```python
worker_initializer: Callable[[], None] | None = None
```

and:

```python
worker_initargs: tuple[object, ...] = ()
```

Then:

```python
pool = ThreadPool(
    workers,
    initializer=worker_initializer,
    initargs=worker_initargs,
)
```

Do not create or inject `_local`.

Users who need thread-local values may implement that in their own initializer module.

### Correct long-term resource API

A reusable worker-resource abstraction may be introduced later:

```python
class WorkerResource(Protocol[T]):
    def open(self, context: Context) -> T: ...
    def close(self, resource: T) -> None: ...
```

But only after:

* worker lifecycle is explicit
* process serialization rules are defined
* cancellation cleanup exists
* HigherGov proves that per-worker reuse is needed

It should not be part of the first callable or Feed implementation.

---

## 6. Pool ownership and cleanup

not sure if this is still applicable given the code changes. verify first before
making changes.

### Problem with the reverted implementation

Cleanup occurred only when:

```python
reuse_pool=False
```

The default reusable pool had no explicit owner and no public close operation.

Early iteration termination could also leave workers or queues alive.

### Correct ownership model

Track whether the pipe created the pool:

```python
self._owns_pool = pool is None and self.parallelize
```

A borrowed pool is never closed by the stage.

An owned pool is closed by the root pipeline owner.

### Explicit lifecycle

Add:

```python
def close(self) -> None:
    if self._owns_pool and self.pool is not None:
        self.pool.close()
        self.pool.join()
        self.pool = None
```

For failure or cancellation before normal completion:

```python
def terminate(self) -> None:
    if self._owns_pool and self.pool is not None:
        self.pool.terminate()
        self.pool.join()
        self.pool = None
```

Add context-manager support:

```python
def __enter__(self):
    return self

def __exit__(self, exc_type, exc, traceback):
    if exc_type is None:
        self.close()
    else:
        self.terminate()
```

Usage:

```python
with SyncPipe(
    source=items,
    parallel=True,
    workers=4,
) as flow:
    result = list(flow.map(process))
```

### Chained pool ownership

When a pool is passed to a child stage:

```python
pool=self.pool
```

the child must set:

```python
self._owns_pool = False
```

Only the root owner closes it.

### Early iterator closure

Wrap pool-backed iteration:

```python
try:
    yield from chain.from_iterable(mapped)
except BaseException:
    if self._owns_pool:
        self.terminate()
    raise
finally:
    if completed_normally and self._owns_pool:
        self.close()
```

Avoid relying on garbage collection.

### Collection cleanup

Apply the same ownership rules to `SyncCollection`.

Its current parallel pool also needs explicit closure.

---

## 7. `send` and `receive`

### Problem with the reverted implementation

Replacing global registries with independent `ContextVar` dictionaries does not make the registry safely shared across worker threads.

A `ContextVar` value belongs to a logical context. A receiver registered in one context may not appear in another worker’s context.

### Correct near-term implementation

Preserve one shared registry but protect it with synchronization.

```python
_registry: dict[
    str,
    Generator[None, Item | StatefulItem, None],
] = {}

_receive_queue: dict[
    str,
    deque[tuple[StreamState | None, Item]],
] = {}

_pubsub_lock = threading.RLock()
```

Registry operations:

```python
def register(name, generator, maxlen):
    with _pubsub_lock:
        _registry[name] = generator
        _receive_queue[name] = deque(maxlen=maxlen)
```

```python
def send(target, item):
    with _pubsub_lock:
        generator = _registry.get(target)

    if generator is None:
        logger.error(...)
    else:
        generator.send(item)
```

Queue operations:

```python
def append_received(name, state, item):
    with _pubsub_lock:
        _receive_queue[name].append((state, item))
```

```python
def pop_received(name):
    with _pubsub_lock:
        queue = _receive_queue.get(name)

        if queue:
            return queue.popleft()

    return None
```

Do not hold the global lock while:

* running arbitrary user functions
* sleeping
* yielding
* performing network I/O

### Important limitation

Python generators cannot safely be entered concurrently.

Therefore, `send()` must serialize calls per receiver.

A better registry entry is:

```python
@dataclass
class ReceiverState:
    generator: Generator
    queue: deque
    lock: threading.Lock
```

Then:

```python
with receiver.lock:
    receiver.generator.send(item)
```

This protects each receiver independently rather than serializing every receiver through one global lock.

### Longer-term implementation

Replace polling generator pub/sub with Feed channels when the Feed runtime is ready.

Conceptually:

```text
send
→ bounded AnyIO memory object stream
→ receive Feed
```

At that point:

* queue capacity is explicit
* backpressure is supported
* async cancellation works
* polling and `sleep()` disappear
* receiver shutdown is explicit

The lock-based implementation is the compatibility fix, not the final architecture.

---

## 8. Async modernization and Feed

### Problem with the reverted implementation

The commit retained the old architecture:

```text
await complete upstream stage
→ convert to synchronous iterator
→ run next stage
```

It also used eager `async_map()` behavior and returned a collected stream.

That is native syntax, but not a lazy asynchronous pipeline.

### Correct source types

In `riko/types/general.py`:

```python
type Feed = AsyncIterable[Item]
type AsyncStream = AsyncIterator[Item]

type AsyncSource = (
    Items
    | Feed
    | Awaitable[Items | Feed]
)
```

### Correct chaining

Replace:

```python
source=self._await_stream()
```

with:

```python
source=self
```

Example:

```python
class AsyncPipe(PyPipe):
    def _chain(self, name: str, **kwargs):
        pipe_kwargs = {
            "source": self,
            "connections": self.connections,
            "inputs": self.inputs,
            "context": self.context,
        }

        pipe_kwargs.update(kwargs)
        return type(self)(name, **pipe_kwargs)
```

### Awaiting remains a terminal

Keep:

```python
result = await pipe
```

for compatibility.

It explicitly collects:

```python
async def _await_stream(self) -> Stream:
    return iter([item async for item in self])
```

Internal chaining never invokes it.

### Source normalization

Create:

```text
riko/runtime/feed.py
```

with:

```python
async def normalize_source(source: AsyncSource | None):
    if inspect.isawaitable(source):
        source = await source

    if source is None:
        return

    if isinstance(source, AsyncIterable):
        async for item in source:
            yield item
    else:
        for item in source:
            yield item
```

Blocking synchronous sources may later opt into thread execution.

### Bounded map

The Feed implementation must use:

* one bounded work queue
* one bounded result queue
* a fixed worker count
* structured cancellation
* no task per source item
* no full-source list conversion

Conceptually:

```text
source producer
    ↓ bounded queue
worker 1
worker 2
worker 3
    ↓ bounded result queue
ordered or unordered consumer
```

### Ordered results

Each source item receives a sequence number.

```python
(sequence, item)
```

Workers return:

```python
(sequence, result)
```

When:

```python
ordered=True
```

the consumer emits only the next required sequence.

The reorder buffer must be bounded.

When:

```python
ordered=False
```

results emit in completion order.

### Thread execution

Blocking HigherGov callables use:

```python
execution="thread"
```

implemented with:

```python
await anyio.to_thread.run_sync(
    partial(func, item, **kwargs)
)
```

Do not detect blocking functions automatically.

### Process execution

Do not implement process execution in the first Feed PR.

The first implementation should raise a clear error:

```python
NotImplementedError(
    "Feed process execution is not implemented"
)
```

Add it only after process-safe context and kwargs validation exist.

### Cleanup

On early downstream termination:

```python
close = getattr(source, "aclose", None)

if close is not None:
    await close()
```

Use AnyIO task groups and cancellation scopes.

Twisted remains a compatibility backend for legacy modules; new Feed concurrency should not be implemented twice.

---

## 9. Async and sync error parity

The same policy names should exist in both runtimes:

```text
fail
skip
dead_letter
```

But they do not need identical internal machinery in the first release.

### Synchronous Core

Initial support:

```text
fail
skip with explicit data-loss opt-in
on_error callback
```

### Feed runtime

Initial support:

```text
fail
skip with explicit data-loss opt-in
on_error callback
task-group cancellation
upstream aclose
```

### Later shared runtime

Add:

```text
ErrorSink
DispositionSink
RetryPolicy
RunStatus
aggregate counters
```

Do not represent parity by injecting identical error dictionaries into both streams.

---

## 10. Documentation corrections

### Remove invalid examples

Delete every example using:

```python
SyncPipe(...).pipe(func)
```

Replace it with:

```python
SyncPipe(source=items).map(func)
```

For expanding functions:

```python
SyncPipe(source=items).flat_map(func)
```

### Correct async syntax

Use:

```python
async def run(reactor):
    stream = await (
        AsyncPipe(...)
        .filter(...)
        .xpathfetchpage(...)
    )
```

Never place `await` inside a normal `def`.

### Do not document default error capture

The correct default documentation is:

```text
Exceptions propagate by default.
```

Then document explicit policies.

### Do not document `_local`

HigherGov’s first browser/session integrations should demonstrate resource ownership inside the callable or chunk operation.

### Correct installation language

Use the actual extras defined by `pyproject.toml`.

Do not document:

```text
riko[async]
```

unless that extra exists.

As Feed and AnyIO are implemented, add an actual extra such as:

```toml
[project.optional-dependencies]
async = [
    "anyio>=4",
]
```

or make AnyIO a core dependency if Feed becomes a core API.

---

## 11. Tests replacing the reverted milestone tests

### Callable-stage tests

Add:

```text
test_sync_map
test_sync_flat_map
test_async_map
test_async_flat_map
test_context_propagates_through_chain
test_callable_receives_normal_kwargs
test_no_signature_inspection
test_public_map_does_not_conflict_with_pool_map
```

### Error tests

Add:

```text
test_error_propagates_by_default
test_on_error_observes_failure
test_skip_requires_allow_data_loss
test_skip_emits_nothing
test_callback_failure_warns_by_default
```

Do not test `_riko_error` records.

### Pool tests

Add:

```text
test_owned_pool_closes_after_completion
test_owned_pool_terminates_after_error
test_borrowed_pool_is_not_closed
test_child_stage_does_not_own_reused_pool
test_context_manager_closes_pool
test_partial_iteration_close_releases_pool
```

### Pub/sub tests

Add:

```text
test_receiver_visible_across_threads
test_receiver_send_is_serialized
test_independent_receivers_do_not_share_queue
test_close_removes_receiver
test_done_closes_receiver
test_pubsub_state_resets_between_tests
```

### Feed tests

Add:

```text
test_feed_accepts_async_iterable
test_feed_accepts_sync_iterable
test_feed_accepts_awaitable_source
test_chaining_is_lazy
test_bounded_source_consumption
test_ordered_map
test_unordered_map
test_reorder_buffer_is_bounded
test_thread_execution
test_early_exit_closes_upstream
test_failure_cancels_workers
```

### Documentation tests

Because doctests are enabled, every new README example must run without:

* live internet access
* external credentials
* Selenium
* nondeterministic ordering assumptions

Use local deterministic examples.

---

## 12. Revised pull request sequence

### PR 1 — Correct callable stages

Files:

```text
riko/collections.py
riko/types/general.py
riko/modules/__init__.py
riko/modules/map.py
riko/modules/flatmap.py
riko/__init__.py
tests/test_collections.py
tests/test_modules_map.py
tests/test_modules_flatmap.py
```

Includes:

* internal `_pool_map` rename
* `map`
* `flat_map`
* context propagation
* `Opts` extension and filtering

Does not include:

* error sinks
* Feed
* worker resources
* schema drift
* RDP

### PR 2 — Pool lifecycle

Files:

```text
riko/collections.py
tests/test_collections.py
```

Includes:

* owned versus borrowed pools
* `close`
* `terminate`
* context-manager support
* partial-consumption cleanup

### PR 3 — Basic error policy

Files:

```text
riko/collections.py
riko/types/general.py
riko/runtime/errors.py
tests/test_errors.py
```

Includes:

* propagation by default
* callback reporting
* skip with data-loss opt-in
* no business-record contamination

### PR 4 — Pub/sub compatibility safety

Files:

```text
riko/utils.py
riko/modules/receive.py
riko/modules/send.py
tests/test_collections.py
tests/test_pubsub.py
```

Includes:

* shared registry
* per-receiver locking
* thread-safe queues
* explicit cleanup

Does not convert pub/sub to Feed yet.

### PR 5 — Schema drift core

Files:

```text
riko/schema.py
riko/types/schema.py
tests/test_schema.py
docs/SCHEMA.md
```

This remains a HigherGov MVP requirement.

### PR 6 — Feed runtime

Files:

```text
riko/runtime/__init__.py
riko/runtime/feed.py
riko/collections.py
riko/types/general.py
pyproject.toml
tests/test_runtime_feed.py
docs/ANYIO_SUPPORT.md
```

Includes:

* lazy chaining
* bounded async map
* thread execution
* ordering
* cancellation
* cleanup

### PR 7 — HigherGov migration

Initial targets:

```text
OpenAI entry analysis
OpenAI document summaries
webpage extraction
HigherGov API calls
document API calls
```

### PR 8 — Feed-based pub/sub

Replace compatibility queues and polling with bounded channels after Feed has stabilized.

---

## 12.1 Shelf promotion sequence

The following Shelf ideas are compatible with this roadmap, but must land after the
Feed runtime and HigherGov vertical slice. They are not part of PRs 1-8.

### PR 9 — HTTP response contracts

Promote the useful parts of the `fetchpage` proposal without adding a transformation
callback to the fetch module.

Add an immutable response envelope:

```python
@dataclass(frozen=True, slots=True, kw_only=True)
class HttpResponseRecord:
    body: bytes
    status: int
    content_type: str | None
    final_url: str
    headers: Mapping[str, str]
```

Requirements:

* fetching and content transformation remain separate stages;
* `fetchpage` may expose metadata through an assignment-compatible record;
* PDF, DOCX, HTML-to-Markdown, and text extraction belong in named downstream modules
  or an optional document connector package;
* redirects, timeouts, and response size limits are represented explicitly;
* no `postprocess` callable is added to serialized module configuration.

This gives HigherGov document ingestion access to status, content type, and canonical URL
without mixing network I/O with document parsing.

### PR 10 — Declarative record transformations

Add only the missing reusable record operations:

```text
coalesce
strtransform
dropfields
```

Use existing modules for:

```text
regex
rename
```

Rules:

* `strip` is a `strtransform` operation, not a separate module;
* dropping `_drop` or `_additional` fields uses `dropfields`, not an overloaded `rename`;
* missing-value handling recognizes `None` and supported scalar NaN values through one
  helper with tests for float, pandas, Polars, and Arrow scalars when those extras exist;
* the modules operate on ordinary records first and gain batch implementations only after
  the batch contract is stable;
* do not add public `applys()` generator composition. `SyncPipe._chain()`, `then()`, and
  compiled pipeline execution remain the composition mechanisms.

### PR 11 — Codec protocol and measured optimization

Do not make `msgspec.Struct` the canonical Riko item. Plain mappings remain the public
record contract.

Introduce an execution-scoped codec protocol only where serialization is required:

```python
class RecordCodec(Protocol):
    media_type: str

    def encode(self, value: JsonValue) -> bytes: ...
    def decode(self, payload: bytes) -> JsonValue: ...
```

The standard JSON codec is always available. A `msgspec` implementation is optional and
may provide JSON or MessagePack. Selection belongs in `ExecutionContext.resources` or an
RDP/connector configuration, not in each module.

Before changing defaults, benchmark:

* encode/decode throughput;
* allocation count;
* payload size;
* thread and task safety;
* small-record latency;
* large-batch throughput.

Do not replace isolated `json.dumps()` calls until the callsite is confirmed to be a
protocol, checkpoint, cache, or artifact boundary. Internal Python stage-to-stage flow
must not serialize records.

### PR 12 — Runtime source bridges

Promote DataFrame ingestion as a runtime-resource bridge, not a serialized configuration
value:

```python
flow = SyncPipe.from_frame(frame)
```

or:

```python
context.resources.register("frames/customers", frame)
flow = SyncPipe(
    "fetchdataframe",
    conf={"resource": "frames/customers"},
    context=context,
)
```

Requirements:

* pandas, Polars, Arrow, and other frame libraries are normalized through the accepted
  interchange layer;
* lazy frames are rejected unless the caller explicitly supplies a bounded collection
  operation;
* the frame object never appears in serialized pipeline JSON;
* conversion preserves nulls and column names predictably;
* early termination releases readers and imported resources.

Database ingestion is not implemented in this PR. It belongs in the separate SQL and
dbt integration gameplan because connection management, credentials, query push-down,
write semantics, and schema evolution are larger than a source-module patch.

### Revised later pull-request order

```text
PR 9   HTTP response contracts
PR 10  Declarative record transformations
PR 11  Codec protocol and benchmarks
PR 12  Runtime frame source bridge
```

Connector, orchestration, SQL, dbt, broker, mail, and storage implementations remain in
extension packages and their dedicated gameplans.

## 13. Definition of done

The corrected roadmap work is complete when:

1. `SyncPipe.map()` no longer conflicts with the internal pool mapping function.
2. `map` and `flat_map` are real modules using existing wrappers.
3. Module execution behavior is represented by `Opts`.
4. Defaults live in the respective modules.
5. The existing `Context` reaches every chained stage.
6. Callables receive normal kwargs with no signature inspection.
7. Exceptions propagate by default.
8. Errors never appear in business records unless the user explicitly creates such records.
9. Pool ownership is explicit.
10. Owned pools close or terminate under all exit paths.
11. Borrowed pools are never closed by child stages.
12. Worker resources are user-owned until a full lifecycle abstraction is justified.
13. `send` and `receive` work across threads without relying on context-local registries.
14. Async stages chain lazily through Feed.
15. Feed processing is bounded and supports backpressure.
16. Async early termination closes upstream sources.
17. Documentation examples use valid APIs and valid Python syntax.
18. HigherGov can adopt callable stages, schema drift detection, and Feed incrementally.

