# Riko Implemented Runtime (as-built)

This is the **as-built companion** — everything that **ships today**, verified against the
code. It documents both stable core sections (from [RUNTIME_CONTRACT.md](RUNTIME_CONTRACT.md))
and the shipped parts of feature topics (owned by gameplans). **This file is the single source
for build-completeness:** each section is tagged **Implemented** (fully ships) or **Partial**
(ships in part; its remaining/planned work is linked per section). A topic **absent here is
Planned** (nothing ships yet). Find any `§N` via the [ROADMAP §-index](ROADMAP.md#index).

> **Provenance.** These are shipped facts, not aspirations. If code and this document
> disagree, the code is authoritative and this document is the bug. Planned behavior lives
> in ROADMAP.md, never here.

## Index

- [0. Architectural direction (shipped)](#0-architectural-direction-shipped)
- [1. Product layers — Riko Core (shipped)](#1-product-layers--riko-core-shipped)
- [2. Core item and stream types](#2-core-item-and-stream-types)
- [3. Pipe behavior (shipped)](#3-pipe-behavior-shipped)
- [6. Async execution and backpressure (shipped)](#6-async-execution-and-backpressure-shipped)
- [7. Timeout (shipped)](#7-timeout-shipped)
- [8. Union (shipped)](#8-union-shipped)
- [9. Exit codes (shipped)](#9-exit-codes-shipped)
- [13. Filter semantics (shipped)](#13-filter-semantics-shipped)
- [23. AnyIO runtime (shipped)](#23-anyio-runtime-shipped)
- [24. Module discovery (shipped)](#24-module-discovery-shipped)
- [25. Conversion — export converters (shipped)](#25-conversion--export-converters-shipped)

---

## 0. Architectural direction (shipped)

> **Partial.** Direction beyond what ships (callable pipes, batches, schema/state, RDP, Connect) is [roadmap](ROADMAP.md).

Riko retains its item-oriented pipeline model. Already shipping from the architectural
direction:

* lazy asynchronous iteration
* bounded concurrency and backpressure
* synchronous/asynchronous parity for the built-in modules

Not yet shipped (see ROADMAP §0): callable `map`/`flat_map` pipes, logical record
batches, explicit schema/state handling, the Riko Data Protocol, and the Connect
orchestration layer.

## 1. Product layers — Riko Core (shipped)

> **Partial.** Riko Connect (orchestration) is not started → [rdp-connect.md](gameplans/rdp-connect.md).

**Riko Core** ships the following of its layer:

* synchronous and asynchronous pipelines
* built-in modules
* stream and Feed processing
* meza-backed export converters (see [§25](#25-conversion--export-converters-shipped))

Not yet shipped in Core: callable pipes, logical batches, schema projection, and
error/disposition callbacks and sinks. **Riko Connect** is not started.

## 2. Core item and stream types

> **Implemented.** Minor: removing legacy async-chaining materialization → [execution-semantics.md](gameplans/execution-semantics.md).

The core item and stream types exist as described, in `riko/types/general.py`:

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

`Stream` and `Feed` differ by iteration mechanism, not by whether the source is finite or
live.

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

Each asynchronous execution resolves the source once and normalizes it to
`AsyncIterator[Item]`. The implementation currently accepts `Awaitable[Items]`, awaits it,
and passes synchronous iterables to module parsers.

## 3. Pipe behavior (shipped)

> **Partial.** Remaining lazy-Feed-chaining gaps → [execution-semantics.md](gameplans/execution-semantics.md).

### Synchronous pipes

`SyncPipe` is synchronous and iterable:

```python
for item in pipe:
    ...
```

Its parallel implementation materializes the complete source before pool submission
(`source_items = list(self.source)`). This ships as an explicit limitation: parallel
synchronous execution is not guaranteed to support infinite streams or bounded-memory
source submission.

### Asynchronous pipes

`AsyncPipe` supports lazy iteration and a compatibility await terminal:

```python
async for item in pipe:
    ...

result = await pipe          # collects output, returns the historical sync-style result
```

Async chaining is lazy at the pipe boundary. The non-bounded legacy-parser path still
buffers its upstream at the named `AsyncPipe._materialize_legacy_source` seam; only the
bounded/parallel path streams end-to-end. Incremental `AsyncCollection` merge on the
unordered path streams as records arrive (via `async_merge`); ordered collections still
materialize per source.

### Feed reuse

Feeds behave like ordinary async iterators. Riko does **not** detect consumed feeds,
recreate them automatically, or raise a custom consumed-state exception — the underlying
`StopAsyncIteration` behavior is authoritative.

## 6. Async execution and backpressure (shipped)

> **Partial.** Reorder-buffer indexing, `ordered=False` fix, cancellation/cleanup → [execution-semantics.md §6](gameplans/execution-semantics.md#6-async-execution-and-backpressure).

Async mapping uses **bounded worker concurrency**: it does not create one task per source
item, materialize the entire source, or permit unbounded result buffering. Order-preserving
streaming ships through `async_map_stream` / `async_map_ordered_stream`
(`riko/bado/itertools.py`). Ordering currently uses a batched window rather than a true
indexed reorder buffer.

`connections=0` means unlimited; `async_map` preserves legitimate `None` results through a
`_missing` sentinel; eager materialization is by design, with the streaming variants above
as the bounded alternative.

## 7. Timeout (shipped)

> **Partial.** `idle`/`item` modes + `on_timeout` policy → [execution-semantics.md §7](gameplans/execution-semantics.md#7-timeout).

Lifetime (`total`) timeout ships for both sync and async through `TimeoutIterator`
(`riko/modules/timeout.py`). The sync `TimeoutIterator` wraps the upstream read so a blocked
read cannot overrun the deadline; async `timeout=0` means "no timeout" (matching sync).
Full async `anext` cancellation remains partial.

## 8. Union (shipped)

> **Partial.** The user-facing concurrent `merge` operator → [execution-semantics.md §8](gameplans/execution-semantics.md#8-union-and-merge).

`union` ships (`riko/modules/union.py`) as deterministic sequential concatenation
implemented with `itertools.chain`:

```text
primary
→ other 1
→ other 2
```

The internal `async_merge` primitive (`riko/bado/itertools.py`) also ships — bounded,
arrival-order — and powers incremental `AsyncCollection` merge on the unordered path. The
user-facing `merge` operator is not yet built.

## 9. Exit codes (shipped)

> **Partial.** The `RunStatus` enum + formal 4-code scheme are planned (no gameplan yet).

The CLI returns process exit codes (`riko/cli/manage.py`). The `RunStatus` enum and the
formal 4-code completed/failed/usage/partial scheme are not yet implemented.

## 13. Filter semantics (shipped)

> **Partial.** Drop-policy / disposition semantics → [execution-semantics.md §13](gameplans/execution-semantics.md#13-filter-semantics).

`filter` ships `permit` / `combine` / `stop` semantics (`riko/modules/filter.py`). Each
rule's `op` is validated once at prep; missing operands are then treated as `None` and the
comparison is skipped. Drop-policy and disposition semantics are absent.

## 23. AnyIO runtime (shipped)

> **Partial.** Protocol adapters + the `asyncioreactor` escape hatch → [twisted-protocol-servers.md](gameplans/twisted-protocol-servers.md).

AnyIO is the **sole** async runtime (`riko/bado/__init__.py`); backend selection is purely
"does `anyio` import?" (`backend = "empty" if run is None else "anyio"`). There is **no
Twisted** anywhere in the code and **no `RIKO_ASYNC_BACKEND` env var**. `AsyncIterable` is
the pipeline-level abstraction; async iteration is pull-based (`__anext__` awaited by the
consumer), and a `Feed` is defined by its iteration mechanism, not by whether the source is
finite or live.

Runtime and protocol layers are orthogonal: network protocol support is a source/sink
adapter concern, not a core-runtime concern. That adapter design (asyncio-native libraries;
the Twisted `asyncioreactor` escape hatch for server roles) is roadmap, in ROADMAP §23.

## 24. Module discovery (shipped)

> **Partial.** Entry-point / runtime `ModuleRegistry` (P8) → [extensibility.md §24](gameplans/extensibility.md#24-module-registry-and-plugins).

Module discovery is the `pkgutil`-based catalog. `list_modules()` /
`list_modules(show_metadata=True)` (defined in `riko/modules/_metadata.py`, re-exported from
`riko/modules/__init__.py`) discover pipes via `pkgutil` and read `ModuleMetadata` off the decorator-set wrapper attributes (`type`,
`subtype`, `supported_subtypes`, `pollable`); subtype is derived (see `_derive_subtypes`).
The catalog is derived, not declared. Unqualified names are reserved for built-ins;
namespaces are reserved. The entry-point/runtime `ModuleRegistry` is P8-planned.

## 25. Conversion — export converters (shipped)

> **Partial.** Batch/dataframe path (Arrow/Polars/SQL) → [database-transforms.md §25](gameplans/database-transforms.md#25-conversion-and-dataframe-integration).

Meza-backed export converters ship: `csv` / `json` / `geojson` / `ofx` / `qif` / `list` /
`tuple` (`riko/collections.py`; `list_targets()` lists registered export converters). Meza
owns conversion work. The Batch/dataframe path (Arrow/Narwhals/Polars/SQL execution
representations selected by capability) is deferred.
