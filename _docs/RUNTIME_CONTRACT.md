# Riko Runtime Contract

The **stable core** of what a riko pipeline is and guarantees — the item/stream model, pipe
behavior, and the execution/delivery semantics that ship today. It is deliberately small and
changes rarely. Planned capabilities and new features are **not** here; they live in the
[gameplans](ROADMAP.md#gameplans), and [ROADMAP.md](ROADMAP.md) is the complete `§0–27` index
mapping every section number to its home. What actually ships (as-built detail) is in
[IMPLEMENTED.md](IMPLEMENTED.md).

> Section numbers are stable identifiers referenced across the codebase. The missing numbers
> below (§4, §5, §11, §14–§22, §24, §25) are feature / end-state topics owned by gameplans —
> find any of them via the [ROADMAP §-index](ROADMAP.md#index).

## Index

- [0. Architectural direction](#0-architectural-direction)
- [1. Product layers](#1-product-layers)
- [2. Core item and stream types](#2-core-item-and-stream-types)
- [3. Pipe behavior](#3-pipe-behavior)
- [6. Async execution and backpressure](#6-async-execution-and-backpressure)
- [7. Timeout](#7-timeout)
- [8. Union and merge](#8-union-and-merge)
- [9. Run status and exit codes](#9-run-status-and-exit-codes)
- [10. Delivery guarantee](#10-delivery-guarantee)
- [12. Errors and dispositions](#12-errors-and-dispositions)
- [13. Filter semantics](#13-filter-semantics)
- [23. AnyIO and Twisted](#23-anyio-and-twisted)

---

## 0. Architectural direction

Riko is an item-oriented pipeline engine. Its design favors: explicit behavior over
inference; at-least-once delivery over exactly-once claims; bounded resource use; simple
defaults; conservative failure behavior; and compatibility with existing synchronous
pipelines. Where the runtime is *headed* (callable pipes, logical batches, schema/state, the
Riko Data Protocol, the Connect layer) is roadmap, not contract — see [ROADMAP.md](ROADMAP.md).

## 1. Product layers

**Riko Core** is the pipeline engine and the subject of this contract: synchronous and
asynchronous pipelines, built-in modules, stream and `Feed` processing, and export
converters. The orchestration layer, **Riko Connect**, is roadmap — see
[gameplans/rdp-connect.md](gameplans/rdp-connect.md).

## 2. Core item and stream types

The core types (`riko/types/general.py`):

```python
type Item = RikoDict | dict[str, RikoValue] | RSSEntry | DotDict[RikoValue]
type Items = Iterable[Item]
type Stream = Iterator[Item]  # synchronous iteration
type Feed = AsyncIterable[Item]  # asynchronous iteration
type AsyncSource = Items | Feed | Awaitable[Items | Feed]
```

`Stream` and `Feed` differ by iteration mechanism, not by whether the source is finite or
live. Boundedness is **not** a declared `Opts` field today — `Opts.boundedness` /
`require_bounded` are planned ([execution-semantics.md §5](gameplans/execution-semantics.md#5-execution-characteristics)).
What ships is the *behavioral* bound in the §6 async primitives (bounded worker concurrency,
no whole-source materialization). Each asynchronous execution resolves the source once and
normalizes it to `AsyncIterator[Item]`.

## 3. Pipe behavior

A pipe instance is **one-shot** — a single execution. Iteration never restarts and never
raises; an exhausted or closed pipe simply yields nothing. `SyncPipe` is synchronous and
iterable (`for item in pipe`); `AsyncPipe` iterates lazily (`async for item in pipe`) with an
`await pipe` collect terminal. Async chaining is lazy at the pipe boundary. `Feed`s behave
like ordinary async iterators — riko does not detect or recreate a consumed feed.

## 6. Async execution and backpressure

Async mapping uses **bounded worker concurrency**: never one task per source item, never
whole-source materialization, never unbounded result buffering. Order-preserving streaming
ships via `async_map_stream` / `async_map_ordered_stream` (`riko/bado/itertools.py`).
`connections=0` means unlimited; legitimate `None` results are preserved.

## 7. Timeout

A lifetime (`total`) timeout applies to both sync and async (`TimeoutIterator`). The sync
wrapper guards a blocked upstream read so it cannot overrun the deadline; async `timeout=0`
means "no timeout" (matching sync).

## 8. Union and merge

`union` is deterministic **sequential concatenation** (primary → other 1 → other 2 …), via
`itertools.chain`.

## 9. Run status and exit codes

The CLI (`riko/cli/manage.py`) returns process exit codes: `0` completed · `1` failed ·
`2` CLI usage/config error. The formal `RunStatus` enum and the four-code
completed/failed/usage/**partial** scheme (with a configurable partial code) are **planned**,
not yet implemented — see [IMPLEMENTED.md §9](IMPLEMENTED.md#9-exit-codes-shipped).

## 10. Delivery guarantee

Today delivery is **best-effort, in-process**: a run streams items from source to sinks within
a single process, with per-item graceful error capture (§12). There is **no** durable
checkpoint, source-position, acknowledgement, or replay machinery, so riko makes no cross-run
durability guarantee yet. The **at-least-once** durability contract — durable outputs gating
source-position advance, replay on failure between sink acknowledgement and checkpoint
persistence, exactly-once explicitly *not* claimed — is **planned** and owned by
[rdp-connect.md](gameplans/rdp-connect.md#17-riko-data-protocol) (§14, §17–§21).

## 12. Errors and dispositions

Per-item processing is **graceful**: errors are captured via `error_key` / `on_error`, not
raised at call sites. Definition, configuration, and lifecycle boundaries may raise stable
typed errors (`UnsupportedModuleError`, `UnsupportedPipelineError`, `PipelineStateError`).

## 13. Filter semantics

`filter` provides `permit` / `combine` / `stop`. Each rule's `op` is validated once at prep;
a missing operand is treated as `None` and its comparison is skipped.

## 23. AnyIO and Twisted

AnyIO is the **sole** async runtime (`riko/bado/__init__.py`); backend selection is purely
"does `anyio` import?" (`backend = "empty" if run is None else "anyio"`). There is **no
Twisted** anywhere and **no `RIKO_ASYNC_BACKEND`** env var. `AsyncIterable` is the
pipeline-level abstraction and async iteration is pull-based. Runtime and network-protocol
support are orthogonal — protocols are source/sink adapters, which is roadmap.
