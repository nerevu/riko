# Riko Implemented Runtime (as-built)

This is the **as-built companion** — everything that **ships today**, verified against the
code. It documents both stable core sections (from [RUNTIME_CONTRACT.md](RUNTIME_CONTRACT.md))
and the shipped parts of feature topics (owned by gameplans). **This file is the single source
for build-completeness:** each section is tagged **Implemented** (fully ships) or **Partial**
(ships in part; its remaining/planned work is linked per section). A topic **absent here is
Planned** (nothing ships yet). Find any `§N` via the [ROADMAP §-index](ROADMAP.md#index).

> **Provenance.** These are shipped facts, not aspirations. If code and this document
> disagree, the code is authoritative and this document is the bug. Planned semantics live in
> their owning gameplans; [ROADMAP.md](ROADMAP.md) routes to those owners.

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
- [Subscription lifecycle — `subscribe` / `publish` (F5a, partial)](#subscription-lifecycle--subscribe--publish-f5a-partial)
- [Compiler graph index (shipped)](#compiler-graph-index-shipped)
- [25. Conversion — export converters (shipped)](#25-conversion--export-converters-shipped)
- [Write architecture — `write()` / `sink()` sessions (shipped)](#write-architecture--write--sink-sessions-shipped)

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

The core item and stream types exist as described, in `riko/types/_streams.py`:

```python
type Item = RikoDict | dict[str, RikoValue] | RSSEntry | DotDict[RikoValue]

type Items = Iterable[Item]
type Stream = Iterator[Item]
type Feed = AsyncIterable[Item]
```

`Stream` and `Feed` differ by iteration mechanism, not by whether the source is finite or
live.

* `Stream` is synchronous iteration.
* `Feed` is asynchronous iteration.
* Boundedness is **not** a declared `Opts` field yet (`Opts.boundedness` / `require_bounded` are planned — [execution-semantics.md §5](gameplans/execution-semantics.md#5-execution-characteristics)); the bound that ships is behavioral, in the §6 async primitives.

The public asynchronous source type is:

```python
type AsyncSource = Items | Feed | Awaitable[Items | Feed]
```

Each asynchronous execution resolves the source once and normalizes it to
`AsyncIterator[Item]`. `Awaitable[Items]` sources are awaited. A `Feed`
(`AsyncIterable[Item]`) passed directly to an async operator now flows through the wrapper
as an `AsyncIterator[Item]` (via `operator.aparse` + async-aware `operator.setup`), so
composer operators (e.g. `timeout`) consume it lazily via `async for` and can bound an
infinite `Feed`; the `AsyncPipe` collection path still buffers non-Feed-native parsers at
the `_materialize_legacy_source` seam.

Per-fetch source bodies are **eager-read, lazy-parse** on the async path: `async_url_open`
buffers the full response (`response.content` / `Path.read_bytes`) into a `BytesIO` before
parsing, so there is no read-time backpressure. Streaming parsers pair `await
async_url_open(...)` with `_io.auto_close` (close-on-iteration), never `async with`.
Incremental `httpx.stream()` body reads and `AsyncClient` reuse are **Partial** (not
implemented). Sync `Fetch` differs — its non-memoized path streams `r.raw` incrementally.

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
source submission. `pool_scope` selects pool lifetime: `"pipe"` (a per-pipe pool,
released after each pipe's iteration) or the default `"pipeline"` (one pool shared
across the run). The `"pipe"` value was renamed from `"stage"`.

### Asynchronous pipes

`AsyncPipe` supports lazy iteration and a compatibility await terminal:

```python
async for item in pipe:
    ...

result = await pipe  # collects output, returns the historical sync-style result
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

Module discovery is the derived catalog. `list_modules()` /
`list_modules(show_metadata=True)` (defined in `riko/modules/_metadata.py`, re-exported from
`riko/modules/__init__.py`) discover built-in pipes via `pkgutil` and read `ModuleMetadata` off the
decorator-set wrapper attributes (`type`, `subtype`, `subtypes`, `pollable`); subtype is derived
(see `_derive_subtypes`). The catalog is derived, not declared. Since P8 it **overlays** registry
(runtime-registered + entry-point) modules via `gen_registry_catalog`, so extension modules are
discoverable too. Unqualified names are reserved for built-ins; dotted namespaces for extensions.

**Typed discovery (P9A, shipped).** `list_modules(*, type, subtype, category)` and
`describe_module(name) -> ModuleDefinition | None` (`riko/modules/_metadata.py`, on the stable
`riko` surface) give filtered runtime truth. **The three filter axes are all lowercase
`Literal` strings, not enums** — `ModuleType = Literal["operator","processor","splitter"]`,
`ModuleSubtype`, and `ModuleCategory = Literal["source","transform","sink"]` (the `derive_category`
return value) — so `list_modules(category="sink")` → `["write"]`. These are a **separate axis** from
the discovery-tree identifier enums (`Modules`/`Sources`/`Transforms`/`Sinks`, whose member `.value`
is the module id, for `SyncPipe(...)`/`|` chaining): don't confuse them. In particular
`category="Sinks"` (the bucket class name) returns `[]` — the value is `"sink"`, lowercase singular.
(The codegen maps the three category strings to the plural bucket **class** names via `_CATEGORY_CLASS`
= `{"source": "Sources", "transform": "Transforms", "sink": "Sinks"}`.)
`derive_category` (`riko/ext/_names.py`) buckets each module by **data-flow capability only**.
`SINK_NAMES` (`{"output","write"}`) is the *criterion*, not the
membership: a module is a `Sink` iff its name is in that set. The one built-in match is `write`
(`riko/modules/write.py`) — a pass-through operator that serializes the stream to `conf['url']` via a
`Formats` converter and yields items unchanged (`Modules.WRITE`/`Sinks.WRITE`). It is **not lazy** —
serializing needs the whole stream, so `parser`/`async_parser` do `items = list(stream)` and the
pass-through replays that list (contract §2/§3 streaming does not hold through a `write`). `output` stays
unmatched (compiler-local passthrough node, not a `riko/modules/*.py` pipe). `write` is the
in-pipeline counterpart of the one-shot `Formats`/`export` surface (see §25); it is distinct from the
fluent `write()`/`sink()` verbs and their write-session architecture (see § Write architecture), and
is the module removed at the R5C clean-break once `Pipeline.write()` / `WriteNode` lands. `riko.ext.codegen` generates the byte-stable
`riko/modules/_names.py`: the flat `Modules` namespace (every pipe, aliasing bucket members so
`Modules.FILTER is Transforms.FILTER`) + `Sources`/`Transforms`/`Sinks` bucket enums (member
`.value` = canonical id; collisions raise). Regenerate with `gen-names`/`manage codegen` (drift guard
`test_generated_names_match`). Re-exported from `riko`, **not** `riko.modules`.

## Module registry & pipe resolution (P8, shipped)

The runtime→compiler resolution coupling is inverted behind three **compiler-free** layers sharing
one overloaded `resolve(name, interface)` contract (`riko/types/_wrappers.py::Resolver`):
`ModuleRegistry` (`riko/ext/registry.py`; built-ins lazy per name, runtime `register`/`reset`, entry
points under `[project.entry-points."riko.modules"]`; precedence runtime → entry-point → built-in),
`PipelineResolver` + injectable `ModuleStore`/`DirectoryStore` (`riko/runtime/_pipelines.py`; core ships
no locations), and the `PipeResolver` façade (`riko/runtime/_resolver.py`) doing one symmetric dispatch.
`riko/runtime/collections.py` resolves through the façade; `riko.runtime._compile.resolve_module`
delegates to it. Generated pipelines expose a stable `pipe`/`async_pipe` entry, so a sub-pipeline resolves exactly
like a built-in. External packages add modules with **no core edit** (`examples/riko-example-ext/`).
P9A discoverability (generated `Modules` tree, `list_modules`/`describe_module`) shipped — see
§24 above. Remaining P9 (non-P9A): the installed-env aggregate `riko.generated.Modules` + `.pyi`
stubs → [module-enums.md](gameplans/module-enums.md).

**Pipe authoring:** the `processor`/`operator`/`splitter` decorators infer `isasync`
(`riko/modules/_decorators.py::_resolve_isasync`) — from an `async def` or the conventional
`async_pipe` name — so authors rarely pass it. Explicit `isasync=True` is needed only where the
name signal can't reach the type checker: a sync async-interface callable not named `async_pipe`
(e.g. a lambda), or a sync `def async_pipe` handed to a typed API such as
`ModuleDefinition(async_pipe=…)`. A function named `pipe` that resolves async raises `TypeError`.
The typed `__call__` overloads track the `async def` case (`@operator()` on a coroutine is statically
async). Tests: `tests/internal/test_decorators.py`.

**Fluent surface (P9, partial — shipped):** value-taking chaining — `pipe | "name"`,
`pipe | ("name", conf)`, `pipe | SyncPipe(...)`, `items | SyncPipe(...)`, and `.pipe()`/`.async_pipe()`
— plus the `ModuleName` `StrEnum` base and `normalize_module_name` (`riko/ext/_names.py`); a name may
be a `str` or `ModuleName` member anywhere, normalized to its canonical string at the boundary. The
generated `Modules` tree (P9A) shipped — `pipe | Transforms.FILTER` resolves identically to
`pipe.filter()`; see §24.

## Compiler graph index (shipped)

`parse_pipe_def` interprets a pipe's wiring into one immutable `_GraphIndex`
(`riko/types/_compiler.py`) in place of the former `ParsedPipeDef` `graph`+`wires` mappings.
Wire-level `edges`/`incoming`/`outgoing` keep full port identity (ports verbatim — `_INPUT`/`_OTHER`/
`_OUTPUT` or a named kwarg); node-level `order`/`dependencies`/`dependents`/`roots`/`leaves`/`outputs`
carry scheduling facts, with the embed→loop relationship folded into `order`. It is built once,
deterministically, and frozen (`MappingProxyType`/tuples/`frozenset`). Consumers — `_get_input_module`,
`_gen_pykwargs`, and `build_pipeline`/`abuild_pipeline`/`stringify_pipe` ordering — read the index
rather than rescanning wires; `order` uses a strict topological sort, so a cyclic pipe is rejected up
front instead of silently SCC-reordered. Generated output stays byte-identical (drift guards
`test_codegen_matches_expected_file` / `test_example_pipes`); the index structure is pinned by
`tests/internal/test_compile.py` (`test_parse_pipe_def_replaces_wires_with_graph_index`,
`test_graph_index_indexes_wire_ports`, `test_graph_index_orders_embed_before_its_loop`).

> **Foundation for R4A/R4B.** The v1-behavior-preserving deltas the index still carries — `_OUTPUT`
> as a node, verbatim ports, dropped orphans — are resolved at the Workflow v2 boundary, not in the
> index. Execution concepts never move onto it. See
> [extensibility § E3.11](gameplans/extensibility.md#e311-reuse-of-the-shipped-graph-index).

## Subscription lifecycle — `subscribe` / `publish` (F5a, partial)

> **Partial.** The shipped compatibility behavior and the revised MVP/F5 staging boundary are
documented in [fanout-topology.md §14](gameplans/fanout-topology.md#14-relationship-to-current-send--receive),
especially [§14.1](gameplans/fanout-topology.md#141-revised-compatibility-mvp-boundary).

`SyncPipe` ships a subscribe/publish pair that hides the pub/sub hub from callers:
`SyncPipe.subscribe(name, func=…, wait=…, maxlen=…)` registers eagerly via
`receive.register_receiver`, so the old `next(receiver)` priming call — which leaked
generator-coroutine mechanics — is gone. `publish` is a single descriptor serving both
bindings: `SyncPipe.publish(source, *names)` on the class and `flow.publish(*names)` on an
instance (chaining to `send`).

**The subscribed drain is non-blocking and marker-free.** `subscribe` pins
`conf["max_wait"] = 0`, which makes `receive.parser`'s PENDING branch structurally
unreachable — `total_waited` starts at 0, so an empty queue always takes the stop branch
before the sleep-and-yield branch. Callers never see a `StreamState` marker and nothing
filters the stream. This is sound because the sync backend has no producer/consumer
concurrency: `send` pushes only when the sender pipe is advanced, on the same thread, so a
blocking idle wait could never be satisfied anyway. Per
[release-readiness.md § 2](gameplans/release-readiness.md), blocking is a property of the
`Subscription` rather than of `receive`, so this is the permanent in-process compatibility
default.

The raw `SyncPipe("receive", conf=…)` path is unchanged and still emits PENDING for
interleaved manual stepping. The two behaviors coexist transitionally on the compatibility
surface.

**`func` queues its return value, not the received item.** So `func=archived.append` yields
`None` per item and `func=len` yields an `int` — neither an `Item`, which is why
`receive.pipe`'s declared return does not satisfy `SyncOperatorParser`, and why chaining
(`subscribe("x", func=…).sort()`) yields `{'content': None}`. This transformation behavior is
preserved during the revised compatibility MVP so sync and async do not diverge. Final F5
changes **both** modes together to `on_receive=` semantics, where the callback return is discarded
and the received item continues. Do not silence the current typing symptom by widening
`OperatorParserOutput`.

**Known lifecycle gap:** `receive.parser` calls `close(name)` on idle expiry as well as on DONE,
and `SyncPubSubHub.close` pops receiver, queue, and id together — so an empty drain destroys
the subscription rather than ending one pass, and the sender's bound id goes stale. This is
intentionally **not** repaired by extending the old DONE/`ids` mechanism. The compatibility
MVP fixes Feed-native incremental async `send`/`receive`; final F5 replaces lifecycle ownership
with execution-owned `Publisher`/`Subscription` handles so cleanup no longer depends on a user
drain. A `strict` xfail in `tests/public/test_collections.py` marks the shipped gap.

## 25. Conversion — export converters (shipped)

> **Partial.** Batch/dataframe path (Arrow/Polars/SQL) → [database-transforms.md §25](gameplans/database-transforms.md#25-conversion-and-dataframe-integration).

Meza-backed export converters ship as the typed `Formats` `StrEnum` (stable `riko` surface, renamed
from the earlier `Targets`): `csv` / `geojson` / `json` / `jsonl` / `ofx` / `qif` — serialized
representations only. `CONVERSION_FUNCS` (`riko/io/_serialization.py`) is keyed by `Formats` members (`jsonl`
maps to meza's `records2json(newline=True)`, not bracket-stripped JSON); `list_formats()` lists
exactly these serialization formats. `export(items, Formats.JSON)` (or the plain string) serializes;
the `list` / `tuple` collection materializations are accepted only by `export()`
(`ExportType = Formats | Literal["list", "tuple"]`), never by `Formats` or `list_formats()`, because
they are not serialized representations. Drift-guarded by `TestExportFormats`. This is riko's
terminal-output surface, distinct from the discovery tree's `Sinks` bucket (sink *pipes*, empty for
built-ins — see §24) and reused by the write-session architecture (see § Write architecture), which
serializes the same `Formats` at a destination. Meza owns conversion work. The Batch/dataframe path
(Arrow/Narwhals/Polars/SQL execution representations selected by capability) is deferred.

## Write architecture — `write()` / `sink()` sessions (shipped)

> **Partial.** Sync and async write sessions both ship now with the compatibility pipe runtime; R4B moves
their lifetime ownership onto the `SyncExecution` / `AsyncExecution` exit stacks and adds explicit
execution-outcome propagation (including terminate/cancellation → abort), R5C adds the executable
`WriteNode` caller, and R11 adds provider-native targets/sessions →
[execution-semantics.md](gameplans/execution-semantics.md),
[effects.md](gameplans/effects.md), [implementation-sequence.md](gameplans/implementation-sequence.md).

The fluent `write()`/`sink()` verbs ride a private write-session mechanism (no hidden `send`/`on_receive`
pub/sub). Four durable layers:

- **declarative** — `WriteOperation` (frozen `mode` + unified `keys`), `WriteTarget` (a destination
  that *reports write capabilities*, it does not itself deliver records), and `Formats`
  (`riko/definitions/_write.py`).
- **prepared** — `PreparedWrite` (target + normalized operation + resolved `WriteCapabilities`) is the
  validated object; `WriteOperation` on its own is unvalidated intent. `WriteCapabilities` stores only
  independent facts (`modes`, `fmt`, `incremental`, `match_keyed_modes`, `idempotent_modes`);
  `appendable`/`serializes`/`keyed_modes` are **derived** properties. `prepare_write` +
  `validate_target_mode` + local `normalize_keys` live in `riko/definitions/_targets.py` (`normalize_keys` is a
  dedicated helper, *not* a widened `_iterutils.listize`).
- **runtime** — the `SyncWriteSession` protocol (`write(Item | Items)` / `finalize` / `abort` /
  `teardown`) and the `_FileWriteSession` state machine (`_SessionState` OPEN/FINALIZED/ABORTED/CLOSED,
  acquire-once) in `riko/runtime/_write_session.py`. `finalize` commits (idempotent), `abort` abandons,
  `teardown` **never commits**; the `file_write_session` CM only acquires + tears down.
- **surface** — `write()` is passthrough (yields each item unchanged via an identity `_passthrough_pipe`
  host — no `_prime()`, so a preceding module never re-runs); `sink()` is the interim terminal verb
  returning a `WriteResult` (passes the whole stream to one converter call). Both default to
  `WriteMode.REPLACE`. The legacy `_write_through` adapter maps full-exhaust/graceful-close → `finalize`,
  terminate/failure → `abort`.

Invariants worth stating:

- **keys are unified** — the caller supplies a single `keys` list because a target's `match_keyed_modes`
  and `idempotent_modes` are disjoint (`match_keyed_modes & idempotent_modes == ∅`, enforced in
  `__post_init__`), so `(target, mode)` alone fixes whether keys mean record-match identity or
  idempotency/dedup identity. There is no separate `idempotency_key`.
- **incremental is a `target × format` capability**, not a global format trait — `File` owns private
  `_FILE_APPEND_FORMATS` / `_FILE_INCREMENTAL_FORMATS`; there are no global `APPENDABLE_FORMATS` /
  `STREAMABLE_FORMATS`. `appendability` derives from `WriteMode.APPEND in modes`.
- **converters own framing, the session owns the destination boundary** — CSV/JSONL converters keep
  their own row/record terminators (no bracket-stripping; JSONL uses `records2json(newline=True)` +
  one final terminator), and the session only repairs an existing append file's missing newline via a
  **binary** tail check.
- `abort` promises no rollback for incremental targets (CSV/JSONL); it only discards staged content for
  framed targets (JSON/GeoJSON). An empty append never mutates the destination.
- `sink()` is **interim**: it is removed at the R5C clean-break once `write()` at a graph leaf provides
  the same terminal consumption — the durable public verbs are `read()` / `write()` (terminality is a
  graph-position property, not a verb).
- **async** — fluent `AsyncPipe.write()` passthrough and `AsyncPipe.sink()` both ship now, riding the
  `_AsyncFileWriteSession` / `async_file_write_session` path (the `AsyncWriteSession` protocol mirrors the
  sync `write` / `finalize` / `abort` / `teardown` surface). No pub/sub language remains in the error text.
- **runtime-only** — `PreparedWrite`, `WriteCapabilities`, and session strategy are execution-time facts
  and never serialize into the R4A workflow IR.

The layering the compatibility runtime hosts today, and where R4B moves it:

```
now
AsyncPipe
   ↓ compatibility host
AsyncWriteSession
   ├── write
   ├── finalize
   ├── abort
   └── teardown

R4B
AsyncExecution
   ├── owns session via AsyncExitStack
   ├── exhaustion       → finalize
   ├── graceful close   → finalize
   ├── failure          → abort
   └── terminate/cancel → abort
```
