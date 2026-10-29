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
- [Logging (shipped)](#logging-shipped)
- [13. Filter semantics (shipped)](#13-filter-semantics-shipped)
- [14. Sort keys and feed dates (shipped)](#14-sort-keys-and-feed-dates-shipped)
- [23. AnyIO runtime (shipped)](#23-anyio-runtime-shipped)
- [24. Module discovery (shipped)](#24-module-discovery-shipped)
- [Subscription lifecycle — `subscribe` / `publish` (F5a, partial)](#subscription-lifecycle--subscribe--publish-f5a-partial)
- [Compiler graph index (shipped)](#compiler-graph-index-shipped)
- [Canonical value encoder (R2A, shipped)](#canonical-value-encoder-r2a-shipped)
- [Workflow v2 serialization — `Workflow.serialize` / `Workflow.parse` (R4A.5, shipped)](#workflow-v2-serialization--workflowserialize--workflowparse-r4a5-shipped)
- [25. Conversion — export converters (shipped)](#25-conversion--export-converters-shipped)
- [Private execution runtime — `SyncExecution` / `AsyncExecution` (R4B, shipped)](#private-execution-runtime--syncexecution--asyncexecution-r4b-shipped)
- [Callable nodes — `Pipeline.map` (R4C, shipped)](#callable-nodes--pipelinemap-r4c-shipped)
- [Write sessions — private seam awaiting `WriteNode`](#write-sessions--private-seam-awaiting-writenode)

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

`Stream` and `AsyncStream` differ by iteration mechanism, not by whether the source is finite or
live.

* `Stream` is synchronous iteration.
* `AsyncStream` is asynchronous iteration.
* Boundedness is **not** a declared `DecorationOptions` field yet (`DecorationOptions.boundedness` / `require_bounded` are planned — [execution-semantics.md §5](gameplans/execution-semantics.md#5-execution-characteristics)); the bound that ships is behavioral, in the §6 async primitives.

The public sync-or-async source union is:

```python
type AnyIterable[T] = Iterable[T] | AsyncIterable[T]
type Feed = AnyIterable[Item]
```

`Feed` may therefore be a synchronous or asynchronous item source; `AsyncItems`
(`AsyncIterable[Item]`) is the asynchronous iterable type. The private generic
`AnyIterable[T]` (`riko/types/_streams.py`) names the same union for non-item values; the
`riko.bado` primitives (`as_async`, `async_map_stream`, `async_merge(iterables, …)`), the
execution seed/source shapes, and `is_streamlike` use it instead of spelling the union out.

Each asynchronous execution resolves the source once and normalizes it to
`AsyncIterator[Item]`. `Awaitable[Items]` sources are awaited. `AsyncItems`
passed directly to an async operator now flows through the wrapper
as an `AsyncIterator[Item]` (via `operator.anormalize_input` + async-aware `operator.setup`), so
composer operators (e.g. `timeout`) consume it lazily via `async for` and can bound an
infinite `Feed`; the `AsyncPipe` collection path still buffers non-Feed-native parsers at
the `_materialize_legacy_source` seam.

Per-fetch source bodies are **eager-read, lazy-parse** under async iteration: `async_url_open`
buffers the full response (`response.content` / `Path.read_bytes`) into a `BytesIO` before
parsing, so there is no read-time backpressure. Streaming parsers pair `await
async_url_open(...)` with `_io.auto_close` (close-on-iteration), never `async with`.
Incremental `httpx.stream()` body reads and `AsyncClient` reuse are **Partial** (not
implemented). Sync `Fetch` differs — its non-memoized path streams `r.raw` incrementally.

Sync text decoding goes through `riko/io/_reencode.py`: `reencode()` builds a `TextReencoder` (decoding) or a `BytesReencoder` (re-encoding) over the abstract `Reencoder` base, whose `join_char` is the empty value of its output type. An empty source reads as empty. A decoded source whose raw first line does not end in the encoded platform newline (a single unterminated line, carriage-return-only endings, or a multi-byte newline encoding such as UTF-16, whose `\n` byte falls mid-character) is re-split lazily by `_gen_lines`: decoded chunks are buffered and split at every `\r\n`/`\r`/`\n` (`LINE_BREAKS`), a trailing `\r` is held for the next chunk, every line but the last gets the platform newline, and an empty last line is dropped, so `read()`, `read(n)`, `readline`, and iteration agree; iterating or calling `bytes()` after `read(n)` resumes with the rest of the current line. Any other source passes through untranslated, so a `\r` beside a `\n` stays raw on the sync path while async `TextIOWrapper` translates it (owned by [bado-anyio § 2c](gameplans/bado-anyio-alignment.md#2c-encoding-resolution-precedence-syncasync-parity)). Re-encoding to bytes passes the encoded stream through unsplit. `remove_BOM=True` strips one `U+FEFF` from the decoded text (`_strip_bom`, first non-empty chunk) rather than the raw bytes, so it works for any codec. Decode errors surface on read; a failure while the reencoder is opening closes its source/owner.

**Typing boundary.** Parser outputs are generic over `ItemOrValue`. Processor and operator
wrappers remain `Stream` / `AsyncStream` at the public boundary; splitters are the structural
exception and return cascades. Broader `StreamOrValueStream`-style types remain internal
implementation scaffolding rather than public pipe output contracts.

**Shared value helpers (2026-10-15).** `resolve_cast_type` (`riko/coercion/cast.py`) is the one
owner of the unknown-cast-type fallback: `None`/`""` resolve to `CastType.PASS` silently, an unknown
name logs one warning and resolves to `PASS`; `cast_value`, the decorator caster builder, the sort
key builder (`def_itemgetter`, which treats `PASS` as no casting so a sort rule never warns per
item), and typed-value sentinels all call it. `DotDict.__contains__` answers a plain key from the
case-insensitive store without constructing nested `DotDict`s, and a dotted `item["a.b.c"]` wraps
each nested plain mapping so it walks any depth case-insensitively, matching `get`; `match_key`
returns the stored spelling for every mapping kind. `alist` and `materialize` (`riko/bado/itertools.py`, on the stable
surface) collect any (a)sync iterable through `as_async`, into a list and an iterator. The item/value aliases live in
`riko/types/_values.py`; `Context` has no `verbose` field (verbosity is the `riko` logger's
level); `truncate_content` (`riko/coercion/_sequences.py`) shortens `bytes` like `str`.

## 3. Pipe behavior (shipped)

> **Partial.** Remaining lazy-Feed-chaining gaps → [execution-semantics.md](gameplans/execution-semantics.md).

### Pipeline iteration

`SyncPipe`/`AsyncPipe`/`SyncCollection`/`AsyncCollection` and `PipeState` were deleted at
v1-cutover step 4 (2026-10-02, `54b53c29`). `Pipeline` is the one shipped execution
surface and is a reusable definition that stores no items: each run (`pipeline(items)`,
`items | pipeline`, `pipeline.open(items)`, or `iter(pipeline)` / `aiter(pipeline)` for a
self-starting pipeline) builds an execution plan and runs it inside a fresh one-shot
`SyncExecution` / `AsyncExecution` that owns the run's resources for the lifetime of the run.

```python
for item in pipeline(items):
    ...

async with pipeline.open(items) as stream:
    async for item in stream:
        ...
```

Both executions stream: sync iteration pulls lazily; async iteration streams items as the
plan yields them. The old `parallel`/`workers`/`threads`/`pool` arguments are replaced by
`Pipeline.with_execution(executor=, concurrency=, ordered=)` (since 2026-10-03; see the
private execution runtime section below), which consumes the pool mechanics in
`riko/execution/_pools.py`. `Pipeline.map(func)` replaces `SyncPipe(Transforms.UDF, func=…)`
(a `Pipeline`'s `options` are JSON-native, so `udf`'s callable `func` cannot ride on them). The
`subscribe`/`publish` and `split` conveniences have no replacement yet.

A consumed, closed, or failed stream (`riko/runtime/_run.py` `_PipelineStream`, one `_finished`
flag) behaves like an exhausted Python generator (2026-10-26): another `for` yields nothing and
`next(stream, default)` returns the default. Only mixing sync and async iteration raises
`PipelineStateError`. Pinned by `TestPipelineStream` in `tests/public/test_pipeline.py`.

### Feed reuse

The asynchronous half of `Feed` (`AsyncItems`) behaves like ordinary async iterators. Riko
does **not** detect consumed async sources, recreate them automatically, or raise a custom
consumed-state exception — the underlying `StopAsyncIteration` behavior is authoritative.
Synchronous `Items` retain their ordinary iterable semantics.

## 6. Async execution and backpressure (shipped)

> **Partial.** Reorder-buffer indexing, `ordered=False` fix, cancellation/cleanup → [execution-semantics.md §6](gameplans/execution-semantics.md#6-async-execution-and-backpressure).

Async mapping uses **bounded worker concurrency**: it does not create one task per source
item, materialize the entire source, or permit unbounded result buffering. Order-preserving
streaming ships through `async_map_stream` / `async_map_ordered_stream`
(`riko/bado/itertools.py`). Async ordering currently uses batched windows rather than a true
indexed reorder buffer; the sync pool keeps order with a sliding `Executor.submit` look-ahead
window (`riko/execution/_pools.py`).

`async_map` reads `limit=0` as unlimited (the streaming variants take a fixed worker count of
at least 1) and preserves legitimate `None` results through the `MISSING` sentinel; eager
materialization is by design, with the streaming variants above as the bounded alternative.

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
arrival-order — but has no production caller since the collection classes were deleted. The
user-facing `merge` operator is not yet built.

## 9. Exit codes (shipped)

> **Partial.** The `RunStatus` enum + formal 4-code scheme are planned (no gameplan yet).

The CLI returns process exit codes (`riko/cli/manage.py`). The `RunStatus` enum and the
formal 4-code completed/failed/usage/partial scheme are not yet implemented.

## Logging (shipped)

riko has one pygogo configuration: `Gogo("riko")` in `riko/base/_logging.py`, with both its
low and high handlers on stderr. Each module takes `get_logger(__name__)`, a `riko.<module path>`
child left at `NOTSET`, so every riko logger inherits the `riko` parent's level. `set_log_level`
is the one knob; the default WARNING is applied when `riko.base._logging` is imported, so the
console scripts need no setup. `manage -v`/`-vv`/`-q` map to INFO/DEBUG/ERROR through
`resolve_log_level` in `riko/cli/_logging.py`, which also holds the `manage` uncaught-exception hook.

## 13. Filter semantics (shipped)

> **Partial.** Drop-policy / disposition semantics → [execution-semantics.md §13](gameplans/execution-semantics.md#13-filter-semantics).

`filter` ships `permit` / `combine` / `stop` semantics (`riko/modules/filter.py`). Each
rule's `op` is validated once at prep; missing operands are then treated as `None` and the
comparison is skipped. Drop-policy and disposition semantics are absent.

## 14. Sort keys and feed dates (shipped)

`sort` builds its key with `build_sort_key` (`riko/modules/_sortutils.py`): a
`(present, value)` pair whose `value` comes from `def_itemgetter`. An item lacking the
field is `present=False`, so it is never compared with real values and groups first
ascending / last descending for every rule `type`. A rule `default` substitutes for the
missing field before casting and counts as present, so the item sorts among the rest.
`SORT_FILLER` (`-inf`) remains only for a present value that cannot be cast under the
`float`/`decimal`/date types; `int`/`bool` uncastables take the cast default and `text`
keeps the raw string. `def_itemgetter` keeps its scalar contract because `group_by`
(`count`/`sum`/`regex`) stringifies its result.

Feed entries resolve dates through `resolve_date` (`riko/rss/feeds.py`): the first
usable value among the parser's `*_parsed` key and the raw string, parsed by
`resolve_aware_datetime` when it is a string. A key is read only when the entry carries it
(so `feedparser`'s deprecated `updated`→`published` fallback is never triggered), a
blank string is skipped, and a string riko cannot parse is skipped with a warning so the
next key is tried; the result is `None` only when no key yields a date. `feedparser`
leaves `published_parsed=None` for formats such as `May 11, 2012 10:01:00 EST`, which
`fastfeedparser` parses itself, so the two parsers now yield the same `struct_time`.
`updated` falls back to the published keys.

Feed parsing goes through `riko/parsing/documents.py::parse_feed`: with `fastfeedparser`
installed it reads a file source into memory first (it accepts only text or bytes);
otherwise `feedparser` receives the open file and reads it itself, so riko never reads the
feed twice. Its result is typed by the `ParsedFeed` protocol (`riko/types/_rss.py`).
Without `lxml` (the `perf` extra), `xml2etree` parses XML with the standard-library parser
and HTML with `html5lib`, and the module's `etree`/`html`/`html5parser`/`XML_PARSER` names
are `None`.

## 23. AnyIO runtime (shipped)

> **Partial.** Protocol adapters + the `asyncioreactor` escape hatch → [twisted-protocol-servers.md](gameplans/twisted-protocol-servers.md).

AnyIO is the **sole** async runtime (`riko/bado/__init__.py`); backend selection is purely
"does `anyio` import?" (`backend = "empty" if run is None else "anyio"`). There is **no
Twisted** anywhere in the code and **no `RIKO_ASYNC_BACKEND` env var**. `AsyncItems` is
the asynchronous iterable source type, while `Feed = Items | AsyncItems` is the sync-or-async
source union. Async iteration is pull-based (`__anext__` awaited by the consumer).

Runtime and protocol layers are orthogonal: network protocol support is a read/write
adapter concern, not a core-runtime concern. That adapter design (asyncio-native libraries;
the Twisted `asyncioreactor` escape hatch for server roles) is roadmap, in ROADMAP §23.

## 24. Module discovery (shipped)

Module discovery is the derived catalog. `list_modules()` /
`list_modules(show_metadata=True)` (defined in `riko/modules/_metadata.py`, re-exported from the stable
`riko` surface) discover built-in pipes via `pkgutil` and read `ModuleMetadata` off the
decorator-set wrapper attributes (`type`, `subtype`, `subtypes` as a `frozenset`, `pollable`); subtype is derived
(see `get_module_subtypes` in `riko/modules/_derive.py`). The catalog is derived, not declared. Since P8 it **overlays** registry
(runtime-registered + entry-point) modules via `gen_registry_catalog`, so extension modules are
discoverable too. Unqualified names are reserved for built-ins; dotted namespaces for extensions.

**Typed discovery (P9A, shipped).** `list_modules(*, type, subtype, category)` and
`describe_module(name) -> ModuleDefinition | None` (both in `riko/modules/_metadata.py`, both on the stable `riko` surface) give filtered runtime truth. **The three filter axes are all lowercase
`Literal` strings, not enums** — `ModuleType = Literal["operator","processor","splitter"]`,
`ModuleSubtype`, and `ModuleCategory = Literal["source","transform","sink"]` (the `get_module_category`
return value) — so `list_modules(category="sink")` → `["write"]`. These are a **separate axis** from
the discovery-tree identifier enums (`Modules`/`Sources`/`Transforms`/`Sinks`, whose member `.value`
is the module id, for `Pipeline.from_module(...)`/`|` chaining): don't confuse them. In particular
`category="Sinks"` (the bucket class name) returns `[]` — the value is `"sink"`, lowercase singular.
(The codegen maps the three category strings to the plural bucket **class** names via `_CANONICAL`
= `{"source": "Sources", "transform": "Transforms", "sink": "Sinks"}`.)
`get_module_category` (`riko/modules/_metadata.py`, on `riko.ext`) buckets each module by **data-flow capability only**.
`SINK_NAMES` (`{"output","write"}`) is the *criterion*, not the
membership: a module is a `Sink` iff its name is in that set. The one built-in match is `write`
(`riko/modules/write.py`) — a pass-through operator that serializes the stream to `conf['dest']` via a
`Formats` converter and yields items unchanged (`Modules.WRITE`/`Sinks.WRITE`). It is **not lazy** —
serializing needs the whole stream, so `parser`/`async_parser` do `items = list(stream)` and the
pass-through replays that list (contract §2/§3 streaming does not hold through a `write`). `output` stays
unmatched (compiler-local passthrough node, not a `riko/modules/*.py` pipe). `write` is the
in-pipeline counterpart of the one-shot `Formats`/`export` surface (see §25); it is distinct from the
private write-session architecture (see § Write sessions), and
is the module removed at the R5C clean-break once `Pipeline.write()` / `WriteNode` lands. `riko.ext.codegen` generates the byte-stable
`riko/modules/_names.py`: the flat `Modules` namespace (every pipe, aliasing bucket members so
`Modules.FILTER is Transforms.FILTER`) + `Sources`/`Transforms`/`Sinks` bucket enums (member
`.value` = canonical id; collisions raise). Regenerate with `gen-names`/`manage codegen` (drift guard
`test_generated_names_match`). Re-exported from `riko`, **not** `riko.modules`.
A module's **provider** is its namespace, derived from the name (`ModuleMetadata.provider` /
`get_module_provider` in `riko/types/modules.py`: the first dotted segment, `BUILTIN_PROVIDER` =
`"riko"` when unqualified). `NameEntry` (`riko/ext/codegen.py`) derives `provider`/`class_name`/
`member`/`alias` from its name and category: built-ins group by category into the bucket classes;
a provider's modules form one class per provider whose members drop the prefix (`Example.LOOKUP`),
and the flat `Modules` alias keeps the full name (`Modules.EXAMPLE_LOOKUP = Example.LOOKUP`).
Provider classes come from the extension package's own codegen run, never riko's `_names.py`;
`list_modules(provider=)` filters by provider.

## Module registry & pipe resolution (P8, shipped)

The runtime→compiler resolution coupling is inverted behind three **compiler-free** layers sharing
one overloaded `require(name, is_async)` contract (`riko/types/_wrappers.py::Resolver`):
`ModuleRegistry` (`riko/runtime/_module_registry.py`, re-exported via `riko/ext/modules.py` and `riko.ext`; built-ins
lazy per name, runtime `register_module`/`reset_module_registry`, entry
points under `[project.entry-points."riko.modules"]`; precedence runtime → entry-point → built-in),
`WorkflowResolver` (`riko/runtime/_workflow_resolver.py`) + injectable workflow stores (`riko/runtime/_workflow_stores.py`): every store is a
`WorkflowStore[T]` protocol (`load(name) -> T | None`); `ModuleStore = WorkflowStore[ResolvedWorkflow]`
(`PackageStore`, `MappingStore`, `CompositeStore`) and `DirectoryStore` is a `DocumentStore` (`WorkflowStore[Workflow]`) that
parses each workflow document (`WorkflowDocument`) with `Workflow.parse(text, shape="v2")`, which `load_workflow` returns (a miss raises
`UnsupportedWorkflowError` naming the reason; `DirectoryStore.load` treats only `FileNotFoundError` as a miss).
Stores take only `pipe_<id>` names: every resolver entry point (`load`, `load_workflow`, `require`,
`require_interfaces`) translates the `pipe:<id>` alias with `pythonise`, and both `is_compatible` checks use
`is_pipe_id` (`riko/types/_pipedef.py`, prefixes `PIPE_ID_PREFIXES` in `riko/base/_config.py`). A stored-workflow
miss raises `UnsupportedWorkflowError`, a built-in miss `UnsupportedModuleError`; both carry `reason`.
`ResolvedWorkflow` and `WorkflowModule` (`riko/types/_workflow.py`) are `NewType`s so type checkers show
their names. `WorkflowModule` is defined by shape (source defining `pipe`/`async_pipe` over an item, a
stream, or nothing, plus `context`), so hand-written `pyworkflows` modules qualify, but only
`compile_workflow` wraps the type. The pipes `build_workflow_pipes` returns branch on `Context.mode` with
`RUN` (or no context) first, so each mode matches one branch: `DESCRIBE` returns
`{"inputs": …, "dependencies": […]}` (the async pipe yields it once), `DESCRIBE_INPUTS` the declared inputs,
`DESCRIBE_DEPENDENCIES` the dependency names; the hand-written probes mirror this with module-level
`INPUTS`/`DEPENDENCIES`. Producers wrap (`compile_workflow`, `PackageStore.load`, `MappingStore`, the document-module
builder) while inputs stay wide (`MappingStore` takes plain `types.ModuleType`s). `PackageStore` accepts a
package or its import path and imports it at construction (`ModuleNotFoundError` for a bad path,
`ValueError` for a plain module); its lookups use `import_or_else(..., strict=True)`, so only the
`pipe_<id>` module itself may be missing (`import_or_else` also re-raises a `ModuleNotFoundError` that names
no module). Core ships no locations; a `register(*, module_store, document_store, replace=False)` / `reset()` lifecycle mirrors the
registry idiom — the process-global is shared by reference, so in-place mutation reaches the façade and
test imports at once), and the `ResolverDispatcher` façade (`riko/runtime/_resolver.py`) doing one symmetric dispatch.
Stored-workflow lookup resolves through the façade (`dispatcher.require`); the v1 compiler's
`resolve_module` delegate was deleted with it at cutover step 5 (2026-10-03). Workflow modules expose a stable `pipe`/`async_pipe` entry, so a stored workflow resolves exactly
like a built-in. External packages add modules with **no core edit** (`examples/riko-example-ext/`).
The module registry and a private target registry (`riko/runtime/_target_registry.py`, built-in
`FileTarget`, entry points under `riko.targets`) share a generic `Registry[T]` base
(`riko/runtime/_registry.py`) — one three-tier runtime → entry-point → built-in lifetime, each keyed by a
per-domain `_key` hook (module `name`, target `backend`). `ModuleDefinition` (`riko/definitions/_module_definition.py`) is a keyword-only
frozen attrs class holding plain data: `declared_name` holds the name as given (constructor
keyword `name=`), `name` is the derived registry key (declared name, else a non-generic pipe `__name__`),
and `sync_pipe`/`async_pipe`/`description` are stored as passed. `ModuleDefinition.from_module(module, *,
name="", description=None)` reads a module's `pipe`/`async_pipe`, the last part of its `__name__` (the
declared name unless `name` is given), and its docstring summary once, so the record never references the
module and mutating it afterwards never changes a definition; the registry builds a bare entry-point module
with `from_module(obj, name=ep.name)`. An entry-point definition with no declared name
takes the entry-point key; a declared one must match it. A runtime `register` of a built-in or
entry-point name raises unless `replace=True`. A registered `WorkflowDocument` directory resolves by
name: `WorkflowResolver` (given the dispatcher via `register_dispatcher` in `_resolver.py`) builds the document's
`pipe`/`async_pipe` with `build_workflow_pipes`, after the module store. The target registry stores target
classes keyed by `backend` and resolves a `Backends` to its target class. The target vocabulary (base
`Target` + `SupportsRead`/`SupportsWrite`/`SupportsActions`, `WriteCapabilities`, `FileTarget`,
`TargetRegistry`, `register_target`) is on the extension surface (`riko.ext`); the `Backends` enum is on
the stable `riko` surface alongside `Formats`. Workflow-store registration is on `riko.ext` too:
`register_workflow_store(*, package, directory, replace=False)` (`package` is a package or its import path;
primitives only — the store classes and
`WorkflowResolver` stay private per `PRIVATE_RESOLUTION`), with `reset_workflow_resolver` alongside
`reset_module_registry`/`reset_target_registry`, all on `riko.ext` (grouped in `riko/ext/modules.py`,
`riko/ext/targets.py`, and `riko/ext/workflows.py`).
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
async). Tests: `tests/internal/test_modules.py`. The bare form (`@processor` with no parentheses) is
handled by `Module.__new__`: a lone callable argument returns `cls()(fn)`, so it wraps exactly as
the option-free called form; a callable plus options raises `TypeError`; a no-argument
`cls.__new__(cls)` (pickle/copy) still returns an instance. Per-subclass `__new__` overloads type
the bare form as the wrapper and the called form as the decorator instance.

**Fluent surface (P9, partial — shipped):** value-taking chaining — `pipeline | "name"`,
`pipeline | other_pipeline` (associative composition), `items | Pipeline(...)`, and
`.pipe()` — plus the `ModuleName` `StrEnum` base (`riko/types/_enums.py`) and `normalize_module_name` (`riko/definitions/_module_definition.py`); a name may
be a `str` or `ModuleName` member anywhere, normalized to its canonical string at the boundary. The
generated `Modules` tree (P9A) shipped — `pipeline | Transforms.FILTER` resolves identically to
`pipeline.filter()`; see §24.

## Workflow graph index (shipped)

`Workflow.index` interprets a `Workflow`'s edges into one immutable `GraphIndex`
(`riko/types/_workflow.py`). Edge-level `edges`/`incoming`/`outgoing`
keep full port identity in the v2 grammar (`out`; `in`/`in:N`/named value ports); node-level
`order`/`upstream`/`downstream`/`roots`/`leaves`/`outputs`/`required` carry scheduling facts (`leaves` is
derived from `downstream`; `outputs` are the workflow's named outputs; `required` maps each output to
its node plus everything upstream, in `order`; `cyclic` names the nodes a
cycle passes through). The index derives and freezes itself: `GraphIndex` takes only node ids, `GraphEdge`s
(`Workflow.graph_edges`), and the named-output `Endpoint`s (converted with `tuple`/`FrozenDict`, the
`Workflow` converter pattern); every other attribute is a `functools.cached_property`
derived on first use, so even a hand-built index is internally consistent. `OutputRef` is gone —
outputs are plain `Endpoint`s. `order` comes
from `topological_sort` (`riko/base/_graph.py`): one-node groups in `graphlib` order for an acyclic
graph, strongly connected components for a cyclic one; `cyclic` is `cyclic_nodes` over those groups
(every multi-node or self-looping component), and `leaves` uses the same `leaves` helper as
`normalize_workflow`'s lone-leaf default output (both build the graph with `edges_to_graph`, keeping
edge-less nodes; normalization counts stream edges only). It
is the one topology interpretation: `Workflow.validate()` rejects a non-empty `cyclic`, and
`ExecutionPlan.from_workflow` (`riko/execution/_prepared.py`) and the sync/async executions read the same
index instead of rescanning edges. Structure pinned by
`tests/public/test_workflow.py::TestWorkflow::test_workflow_index_orders_and_indexes` and
`tests/internal/test_values.py::TestGraphIndex::test_graph_index_derives_and_freezes_from_its_inputs`.

> The index's v1 indexer (`parse_pipe_def`/`_index_pipe_def`, with `_OUTPUT` as a node, verbatim
> legacy ports, and dropped orphans) was deleted at cutover step 5 (2026-10-03); those deltas are
> resolved at the Workflow v2 boundary (`migrate_v1_to_v2` → `normalize_workflow` → `validate`), not
> in the index. Execution concepts never move onto it. See
> [extensibility § E3.11](gameplans/extensibility.md#e311-reuse-of-the-shipped-graph-index).

## Canonical value encoder (R2A, shipped)

The single deterministic value-freezing/encoding system that durable checkpoint identity,
per-item generation, idempotency, and semantic fingerprints share — no consumer invents its
own hashing. Lives in `riko/coercion/_canonical.py` (PRIVATE), generalizing the former
`_to_hashable()` machinery.

`canonicalize(obj)` canonicalizes a value into a JSON-safe tagged `CanonicalValue`, distinguishing
types Python conflates (`bool` before `int`; `int`/`float`/`Decimal`; `list` vs `tuple`;
`set` vs `frozenset`; `datetime` before `date`; enums before their scalar bases) and
handling `bytes`, `PurePath` (flavor-preserving), `UUID`, mappings, sets, and both dataclasses
and attrs classes (a shared representation-independent `record` tag keyed by type id, so swapping a
type between `@dataclass` and `attrs @define` leaves its digest unchanged).
Mappings and sets are order-independent and sort by canonical encoded key (heterogeneous
keys included); naive datetimes take a UTC fallback and aware ones normalize to UTC via the
existing `resolve_aware_datetime`; `struct_time` stays distinct from `datetime`; `-0.0`
canonicalizes with `+0.0`, and infinities/NaN carry stable tags. Cyclic structures raise
`CyclicIdentityError`; unsupported values raise `IdentityEncodingError` (both under the new
`IdentityError` branch of the `RikoError` tree).

`canonical_json(canonicalize(obj))` (via `canonical_bytes`) emits fixed UTF-8 JSON v1 with no
insignificant whitespace, and `digest(obj, domain)` returns a 32-character lowercase
BLAKE2b-128 hex string, domain/version-separated by the fixed `IdentityDomain`
(`fingerprint`/`generation`/`idempotency`/`state-key`) and `IDENTITY_FORMAT_VERSION` folded
into the hashed bytes but not the returned text. `repr_cache` now keys process-local
memoization on `canonical_bytes` (an all-scalar call keys on a type-tagged native tuple instead,
since a canonical key costs ~6 µs to build, more than the work most cached calls do), bypassing
values that cannot be encoded, so the reversible `_from_hashable` reconstruction machinery is gone.
`_parse_date_cached` (`riko/coercion/_dates.py`) is bounded by `settings.parsed_date_cache_size` (`RIKO_PARSED_DATE_CACHE_SIZE`): it is fed one
entry per distinct item date, so an unbounded cache grew with the stream. `NonNullHashable`/`Hashable`
(`riko/types/_scalars.py`) are the aligned static contracts. `Context(identity_encoder=...)`
backend selection is deferred (R3-adjacent); the stdlib encoder is the reference. Tests:
`tests/internal/test_values.py` (golden canonical bytes + golden digests + rule matrix) plus
module doctests.

## `Workflow` v2 model (R4A.1, shipped)

The structural v2 vocabulary (no execution runtime yet — R4B executes it). Pure contracts live in
`riko/types/_workflow.py` (`Endpoint`, the frozen `Edge` base with its `(node, port)` `port`
property, the `NodeFamily`/`EdgeFamily`/`PortDirection` discriminant literals, `InputRef`, the
`parse_port` grammar helper, and the `Raw*` TypedDicts); the immutable model lives in
`riko/definitions/` — the closed node union
`ModuleNode`/`ReadNode`/`WriteNode`/`CacheNode`/`ActionNode`/`SubscribeNode` and the edge families
`StreamEdge`/`PublishEdge` in `_nodes.py`, the `Workflow` envelope in `_workflow_definition.py`, and the generic
`PipelineDefinition[T_co]` in `_pipeline_definition.py`, which owns every pipeline field and composition method
(settings/context/write derive `Self`; chaining by module name returns `PipelineDefinition[Item]`, `map[R]`
and `|` with a pipeline retype to the last node's item type). The runnable STABLE `Pipeline` is its
subclass in `riko/runtime/_pipeline.py`, adding the run entry points and re-typing the chaining methods to
return `Pipeline[...]`, so no definition imports upward (the architecture lint fails function-local upward imports too).

The node/edge model, `Endpoint`, and `Workflow` are all `attrs @define(frozen, slots)` classes.
The six node families share a public **`Node`** base (`id`/`name`/`resources`/`label` + a `family`
`ClassVar` discriminant) and **self-normalize through `field(converter=…)`**: each field resolves its
enum (`Backends`/`Formats`/`WriteMode` via `resolve_enum`), normalizes resource bindings, or freezes
its `conf`/`policy`/`params` mapping — so constructing a node *is* canonicalizing it, and no separate
builder is required. `ReadNode`/`WriteNode`/`ActionNode` carry declarative
`backend`/`fmt`/`mode`/`keys`/`dest`/`params` intent only (no live resource or write session).
`Workflow`'s converters take `nodes` as an iterable of `Node`s and key them by id (rejecting a mapping or a
repeated id, so a node can never sit under the wrong key), require and freeze the `outputs`/`inputs` mappings
(`FrozenDict`, `freeze_json` for `inputs`), and
normalize `edges`/`resources`; it also owns its own structural checks (see R4A.3).
Omitted `Workflow` fields take module-level `_EMPTY_*` defaults; an explicit `None` raises for every
field (attrs applies the default before the converter, so a `None` reaching a converter was passed
explicitly; `nodes_converter` passes its own `_EMPTY_NODES` default through by identity, and
`resources` uses `normalize_strs(..., strict=True)`). Converter helpers advertise their input type
statically: `narrow_from_require`/`narrow_def_from_require` take a keyword-only `accepted` type form,
and a bound class (`InstanceRequire[T, R]`, `cls: type[R]`) infers the result for `require_instance`;
`def_from_require`'s overloads carry the `TypeRequire`/`InstanceRequire` narrowing while its body
calls `require(*args, value, ...)` (protocols that differ only in `__call__` cannot be told apart at
runtime). `isinstance_strict` returns `TypeIs[P]`; a callable method whose signature `inspect`
cannot read (a generator's built-in `close`/`aclose`) counts as compatible, so the closeable guards
in `riko/types/_io.py` accept generators. An owned `Resource` still refuses a generator object given
without `cleanup`, with an error pointing to `Resource.from_lifecycle`.
`require_from_form(form)` builds a guard for any type form: it flattens aliases, unions, and
`Annotated` with `gen_union_members` (`riko/base/_typing.py`, shared with return-kind inference),
sends a lone class to `require_instance` and a lone TypedDict to `require_from_typed_dict`, accepts a
union member by `isinstance` (any mapping matches a TypedDict member, keys unchecked), accepts a
`Literal` arm's values by type and equality (so `True` never passes for `1`; a pure `Literal` raises
`resolve_enum`-style "Expected one of"), and raises `TypeError` for any other form when the guard is
built. `CallOptions.count` and `fromdict`'s `Literal` fields both validate through it. `require_from_typed_dict` and
`require_from_attrs` both reduce to `require_from_keys(required, allowed)`; in both, `exclude=`
forbids a key and `not_required=` only drops it from the required set. The conf contracts' guards
(`require_module_conf`, `require_conf`) live beside them in `riko/types/modules.py`, off `__all__`.
Mapping fields use one converter callable, never a converter list: pyright types the generated
`__init__` parameter from a single converter's argument but falls back to the field annotation for a
list. The helpers live in `riko/types/_frozendict.py`: `mapping_converter` (required — `None` or a
non-mapping raises, `error=` selectable) and `optional_mapping_converter` (`None` → empty) wrap a
freezer, `freeze_json` for JSON fields or `instances_freezer(cls, what)` for `nodes`/`outputs`,
`ExecutionPlan.modules`/`embeds`, and `Context.resources` (`error=TypeError`). Their optional positional
`accepted` type form only sets the static input type (e.g. `ConfInput` keeps the conf vocabulary
visible while the stored `FrozenConf` is `FrozenDict[str, FrozenJSON]`); the runtime check is the
freezer's. `ModuleNode.options` is the exception: it stores the typed `CallOptions` record (below). `Node.resources` takes
`ResourcesLike` through the single `binding_converter`, which runs `require_binding` (beside it in `riko/definitions/_nodes.py`): it returns the normalized `FrozenDict` alias→Context-name binding and rejects non-string/empty names and repeated aliases. `Workflow.edges` requires `Edge` instances, `Endpoint`/`Edge`/`Node.id` validate their fields, `PipelineDefinition.context`/`settings` raise `TypeError` on a wrong type, and `ExecutionPlan` takes only what the `Workflow` cannot supply — `modules` (one `ResolvedModule` per node id) and `embeds` (one per loop embed) — derives `index` at init and `nodes` (the `PreparedNode` views) as a `cached_property`; `ExecutionPlan.validate()`, run from `__attrs_post_init__`, raises `InvalidPipelineError` at construction for a non-module node or when either key set does not match the workflow. `Context.inputs` and `ModuleNode.embed` still
use converter lists until R4D and R9 settle their value types. Field introspection
uses `riko.base._recordutils.field_names` (attrs-or-dataclass field names *including* `ClassVar`
discriminants like `family`, which `attrs.fields`/`dataclasses.fields` both drop), never
`dataclasses.*`; derive variants with `attrs.evolve`. `PipelineDefinition` (and so `Pipeline`) is an
`attrs @define(frozen, slots)` class like the rest of the model — generic `PipelineDefinition[T_co]` via a
defaulted covariant `TypeVar` (type-parameter defaults need Python 3.13; the floor is 3.12), with its `workflow`
field normalizing `None`/omitted to the empty `Workflow` through the shared `_optional_workflow` converter, so
`Pipeline()` is a valid empty pipeline to compose onto. The node/edge/`Workflow`/`Endpoint` model is EXTENSION
(`riko.ext`). Tests:
`tests/public/test_workflow.py` plus module doctests. Forward order and the clean-break deletion
ledger: [implementation-sequence.md](gameplans/implementation-sequence.md) R4A.

`Workflow` loads and saves itself: `Workflow.parse(document, *, shape=None)` reads a
`WorkflowDocument`, a `PipeDag`, or a `PipeDef` (bytes, text, or a mapping; the shape is detected
unless `shape` pins a `DocumentShape`) and validates the result, `Workflow.load(path)` reads a file
and parses it the same way, and `flow.serialize()` emits the byte-stable `WorkflowDocument`, so
`Workflow.parse(flow.serialize()) == flow`. `Workflow` and `Pipeline` print a compact repr (`Workflow(fetch-1 -> sort-1; outputs:
default)` for a chain, `Workflow(nodes: 3, edges: 2; outputs: default)` otherwise,
`Workflow(empty)`; `Pipeline(...)` appends `seed`/`context` when present).

## Workflow v2 normalization — `normalize_workflow` (R4A.2, shipped)

The single authoring-sugar normalization boundary: `RawWorkflow` in, one `Workflow` out,
so no other subsystem reinterprets shorthand. Lives in `riko/definitions/_normalize.py`
(`build_workflow_fields`, which returns the field values; the clean-break placement note
superseded the original `riko/workflow/normalize.py` sketch); the `normalize_workflow` delegate in
`riko/definitions/_workflow_definition.py` is exported EXTENSION as `riko.ext.normalize_workflow`.

It is the **structural, contract-free** pass — no `ModuleRegistry`/`TargetRegistry` lookup. It
assigns node ids, dispatches each `RawNode` to its node family, maps legacy ports to the
canonical grammar, rejects the `src`/`tgt` and `from`/`to` edge shorthands, materializes a `default`
output from a lone leaf, and normalizes shorthand inputs to JSON Schema; malformed structure raises
`InvalidPipelineError`. Dispatch is **model-driven**: `_NODE_BUILDERS: Mapping[str, type[Node]]`
maps each family to its node class, `_build_node` splats the authoring fields into that constructor
(`builder(**fields)`), and `require_from_attrs(builder)` validates the keys against the class's `field_names` —
so the attrs node class is the single source of truth for accepted fields, and the per-field
enum/resource/mapping coercion is the node's own `field(converter=…)` (see R4A.1), not a
normalize-local builder. It reuses `require_binding`, `normalize_strs`,
`listize`, and the `is_mapping`/`is_listlike` guards; legacy ports map through an open-ended
`_normalize_port` (`_OTHER<n>`→`in:n`, `_OUTPUT<n>`→`out:n-1`). Unknown top-level, node, edge,
and endpoint fields are already rejected; the remaining contract-dependent sugar (format inference from a locator, registered
conf/params/target-config validation) are deferred. The authoring grammar is owned by
[extensibility § E3](gameplans/extensibility.md#e3-canonical-workflow-v2-specification).

The input is typed `WorkflowLike` (`riko.types`) — the `*Like` union of the precise
`RawWorkflow` `TypedDict` (with `RawNode`/`RawEdge`/`RawEndpoint`) and a loose
`Mapping[str, object]`, so a literal gets editor key-completion while any dict still passes. The
`Raw*` TypedDicts are the one hand-written parallel to the canonical dataclasses; a drift guard
(`tests/internal/test_definitions.py`) derives the expected key set from each node/edge/
endpoint's `fields()` and fails if authoring omits a field (modulo the `family` key and the `format`
alias), so a new node field cannot silently drop out of the authoring surface. Tests:
`tests/public/test_workflow.py` plus module doctests.

## Workflow v2 validation — `Workflow.validate()` (R4A.3, shipped)

Strict structural validation is a **method on the model**, not a standalone function: `Workflow`
owns `validate()` (raises `InvalidPipelineError` on the first violation) and an `isvalid` property
(the boolean wrapper), backed by the `ports()`/`endpoints`/`referenced_resources` helpers on the same
class. The earlier standalone `riko/runtime/_validate.py` / `riko.ext.validate_workflow` was removed
in the refactor that moved validation onto the model — there is no separate validation module or
export. It answers "is this a valid graph?", not "can this run here?" — a structurally valid node
whose runtime capability has not landed still passes (E3.10).

Checks, all determinable from the `Workflow` alone: unsupported workflow version; empty node set;
node-id disagreeing with its map key; edge and output endpoints referencing a missing node; more
than one `StreamEdge` into one target port; publish/subscribe edge-family coherence (a `PublishEdge`
targets a `SubscribeNode`, a `StreamEdge` does not); port direction matching the endpoint's role (an
edge source and a named output are `out` ports, an edge target is an `in` port; a port that fails
the grammar is reported as `InvalidPipelineError` rather than `ValueError`); edges forming no cycle
(the graph index's `cyclic` names the nodes on each cycle, so a cyclic document fails here
with those nodes listed); node resource
references resolving to declared top-level `resources`; and a non-empty graph exposing at least one
output (closing `normalize_workflow`'s deferred ambiguous-leaf case). The contract-aware E3.9 rules — undeclared
ports, fan-in arity, registered module/action/target schema validation — are **deferred** because
the module and target contracts declare no ports or configuration schemas yet; they land with that
metadata. Tests: `tests/public/test_workflow.py` (builds `Workflow` graphs directly and asserts
`workflow.validate()`/`isvalid`) plus module doctests.

## Workflow v2 serialization — `Workflow.serialize` / `Workflow.parse` (R4A.5, shipped)

Deterministic byte-stable canonical serialization of a `Workflow` and its
round-tripping parser. Lives in `riko/definitions/_serialize.py` (`serialize_graph`/`parse_graph`);
the STABLE entry points are the `Workflow.serialize`/`Workflow.parse` methods in
`riko/definitions/_workflow_definition.py` (no separate `riko.ext` function forms).

`flow.serialize(*, indent=4)` is a thin `json.dumps(workflow, cls=WorkflowEncoder,
sort_keys=True, indent=indent, ensure_ascii=False)` (plus a trailing newline; `indent=None` gives the
compact `separators=(",", ":")` form) — with `sort_keys` ordering map keys at every level, the
same `Workflow` always yields identical bytes for golden-fixture comparison; edge order follows the `Workflow`
while the semantic wiring lives in the endpoints, not the array order. `WorkflowEncoder` (a
`json.JSONEncoder`) renders **every** structural and value type: it emits the `Workflow` envelope
and each `Node`/`Edge` via **reflection** — `serialize_attrs` (`riko/base/_recordutils.py`) uses `attrs.asdict(recurse=False)`
for the attrs `Workflow`, nodes, and edges, dropping empties (`_has_value`) while keeping required
keys — and it coerces the remaining
structural leaf, `Mapping`/`FrozenDict`→dict (`json` already writes tuples as arrays and `StrEnum`
members as strings). Because node
serialization is field-reflection rather than a per-family branch, a new node field (e.g.
`WriteNode.dest`) serializes automatically with no serializer edit. A node's or edge's kind
serializes as `family`; `RawNode`/`RawEdge` have no `type` key, and a node that gives one is
rejected with a hint naming `name` (the module) and `family` (the kind). Canonical
`conf`/`options`/`policy`/`params`/`embed`/`inputs` values are JSON-native by construction: their
field converters freeze them through `freeze_json` (`riko/types/_frozendict.py`), which rejects
`Decimal`, `date`, `set`, `bytes`, non-finite floats, non-string keys, and any other object, turns
lists into tuples, and builds every mapping as a `FrozenDict` (re-walking a `FrozenDict` so
permissively frozen values are still checked). The permissive `freeze` (definitions' `inputs`,
factory arguments, plans) freezes only built-in containers and keeps a `FrozenDict`, named tuple, or
any other object as is; `thaw` reverses it. `FrozenDict`
is the one frozen-mapping type for definitions, workflows, plans, and `Context`/`Resource`; as a frozen
slotted attrs class it pickles natively, so process-pool workers receive conf with no `copyreg` hook.
Because it is also an attrs class, structural dispatch tests `Mapping` before `attrs.has`. The
encoder therefore needs no Python-only value branches and `serialize` uses `allow_nan=False`.
`Workflow.parse(data)` reconstructs (and validates) the `Workflow` by reusing the shared normalization on the loaded JSON
(a `WorkflowDocument` is itself a valid `RawWorkflow`), so `Workflow.parse(flow.serialize()) == flow` holds
by value equality and serialization is idempotent. A migrated pipe definition (`PipeDef`) serializes with no v1-only structure: no
`_INPUT`/`_OUTPUT`/`wires`/`src`/`tgt` tokens and no `type:"output"` node — the terminal `_OUTPUT`
pseudo-node lives only in top-level `outputs`. Tests: `tests/public/test_workflow.py` (golden bytes,
per-topology round-trip/idempotency, order-independence, JSON-native nested round-trip by equality,
non-JSON-native value rejection, migrate-emits-no-v1) plus module doctests.

The **CLI v1→v2 cutover** was deferred out of this slice to R4B and has since shipped there
(cutover step 3; see [v1-cutover.md](gameplans/v1-cutover.md)). Every console script was kept
and re-pointed at canonical v2 rather than deleted. `riko/cli/_document.py` is the shared
document front door (`read_document`, `require_workflow`); `build-workflow` is the one lenient reader
(through `Workflow.parse`), taking a serialized `PipeDag`, a
serialized `PipeDef`, or a `WorkflowDocument` and always emitting a validated `WorkflowDocument`
(detection picks the reader; a `--format` pin is read as given, never re-detected, and a non-list
`wires`/`modules` falls through to the `PipeDag` reader's `InvalidPipelineError`);
`compile-workflow` and `run-pipe` go through `require_workflow` and refuse anything older. `run-pipe -p <file>.py` calls a `workflow`-stamped `pipe` (`is_subpipe`) with `Context(test=test)` and any other `pipe` with `test=test` (`build_pipe_kwargs` in `riko/cli/runpipe.py`), so `-t` reaches `compile-workflow` output while an undecorated hand-written module still prompts. `run-pipe <id>` searches `./examples` and then the checkout's `ROOT_DIR / "examples"` (`get_example_dirs` in `riko/cli/runpipe.py`; listed once when they are the same directory), trying `<id>.py` then `workflows/<id>.json` in each, so example ids resolve from any directory in a checkout or editable install (the wheel ships no `examples`).
`riko/runtime/_compile.py` is the v2 generator behind STABLE `compile_workflow`, and
`Workflow.parse` replaces `build_pipe_def` as the bare-bones DAG entry point (its interim
STABLE alias `parse_dag` was removed 2026-10-12 as a clean break). A `PipeDag` module names its module in `name` or the older `type`
(`_require_dag_name` in `riko/definitions/_migrate.py` rejects a missing or disagreeing pair). `migrate_v1_to_v2` remains the one-shot offline conversion path, now reachable
from the command line through `build-workflow`. The v1 `PipeDef`/`wires` compiler itself
(`compile_pipe_def`, `parse_pipe_def`, `build_pipeline`, `pypipe*.txt`, `_compile_repr.py`,
`riko/types/_pipeline.py`, `tests/internal/test_compile.py`) was deleted at cutover step 5
(2026-10-03); STABLE `COMPILE` is now `compile_workflow` alone, and `extract_dependencies`
(released name) has no replacement beyond reading `Workflow` node names.

## Workflow v1→v2 migration — `migrate_v1_to_v2` (R4A.4, shipped)

A one-shot offline conversion of a `PipeDef` (`modules` plus `src`/`tgt`
`wires`) into `Workflow`. Lives in `riko/definitions/_migrate.py`
(`migrate_pipe_def`, which returns a `RawWorkflow`; the clean-break placement note
superseded the original `riko/workflow/migrate.py` sketch); the `migrate_v1_to_v2` delegate in
`riko/definitions/_workflow_definition.py` is exported EXTENSION as `riko.ext.migrate_v1_to_v2`. It is **not** a live loader — v1 is not a
maintained runtime ingress, so it `logger.warning`s that a `PipeDef` was migrated, then emits v2
only.

It reuses `build_workflow_fields` for the shared structural pass (port grammar, node families, id
handling, lone-leaf outputs) so only the v1-specific translation lives here: each module's `type`
becomes the node `name`; a v1 `write` module becomes a `WriteNode` (`backend=file`, `fmt` from
`conf.fmt`, mode defaulting to `replace`) rather than executing the legacy Python module; `src`/`tgt`
wire endpoints become canonical `source`/`target` with `_INPUT`/`_OUTPUT`/`_OTHER<n>` ports mapped
(an absent or null port id takes the default port; `_OTHER1` aliases `_OTHER` as `in:1`);
and the terminal `_OUTPUT` pseudo-node plus its wire are consumed into top-level `outputs.default`
and dropped from the graph (no `type:"output"` node survives). A v1 module's call options
(`emit`/`assign`/`field`/`count`) become the node's `options`, so they never collide with a module's own
`conf` keys (`truncate.count`, `regex.field`); a v1 `loop`'s `embed: {id, type}` plus its `conf` become
the node's `embed = {name, conf}` the loop runs (a `pipe:`-prefixed type stays verbatim as the
name); a module key outside `PipeModule`'s closed set raises `InvalidPipelineError` (checked by
`require_from_typed_dict(PipeModule)`, the same rule `write` modules always had; a `write` conf takes
`WriteConf`'s keys plus `keys`, which is a `WriteNode` field rather than write-module conf, via
`extra={"keys"}`). `typed_dict_keys` (`riko/base/_require_guards.py`) reads `Required`/`NotRequired`
from each annotation's source text with `ast`, because CPython 3.12 ignores string-form qualifiers
under postponed annotations; it never evaluates the annotated types, so it needs no namespaces; a wire target
port that is not an identifier is pythonised (`1_URL` → `_1_URL`) to match how module extras are
looked up; fully-uppercase v1 `conf` keys (e.g. `URL`) are
lowercased through the private `_lower_keys` in `riko/definitions/_migrate.py` so they keep v1's canonical casing. Orphan modules
are **retained** as nodes rather than silently erased — arity/reachability is validation's call.
Malformed structure raises `InvalidPipelineError`; an empty node set is left to
`Workflow.validate()` (the `migrate → normalize → validate` flow of E3.1).

Shared plumbing is reused, not reinvented: the legacy `_INPUT`/`_OUTPUT`/`_OTHER`/`output` tokens are
`riko/base/_config` constants (`INPUT_PORT`/`OUTPUT_PORT`/`OTHER_PORT`/`OUTPUT_MODULE`) also consumed
by `_normalize`; the module and edge splits use `partition` from `riko/base/_iterutils`. Tests: `tests/public/test_workflow.py` plus module doctests.

## Subscription lifecycle — `subscribe` / `publish` (F5a, partial)

> **Partial.** The shipped compatibility behavior and the revised MVP/F5 staging boundary are
documented in [fanout-topology.md §14](gameplans/fanout-topology.md#14-relationship-to-current-send--receive),
especially [§14.1](gameplans/fanout-topology.md#141-revised-compatibility-mvp-boundary).

**Removed at v1-cutover step 4 (2026-10-02):** the `SyncPipe.subscribe`/`publish` conveniences
went with the class; the hub (`riko/runtime/_pubsub/`) and the `receive`/`send` modules stay, and
the replacement is orchestration-owned (`Pipeline.subscribe`/`publish` raise `NotImplementedError`
until it lands). What follows records the pair as it shipped.

`SyncPipe` shipped a subscribe/publish pair that hid the pub/sub hub from callers:
`SyncPipe.subscribe(name, func=…, wait=…, maxlen=…)` registers eagerly via
`receive.register_receiver`, so the old `next(receiver)` priming call — which leaked
generator-coroutine mechanics — is gone. `publish` is a single descriptor serving both
bindings: `SyncPipe.publish(source, *names)` on the class and `pipeline.publish(*names)` on an
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
`None` per item and `func=len` yields an `int`. Those scalar/value results are deliberately
representable by the parser contract:

```python
type OperatorParserOutput[T: ItemOrValue] = T | Iterator[T] | Stream
```

That does **not** widen the public wrapper/pipe boundary: processor and operator wrapper outputs
remain item-stream typed. Broader value-stream shapes used to represent `emit=True` behavior
remain internal implementation scaffolding and are not yet propagated into the public `Pipe`
output contract. The typing change represents the existing transformation rather than changing
it. Final F5 fanout work (R7) keeps the name `func` but changes **both** modes together to
receive-time semantics, where the callback return is discarded and the received item continues.

**Known lifecycle gap:** `receive.parser` calls `close(name)` on idle expiry as well as on DONE,
and `SyncPubSubHub.close` pops receiver, queue, and id together — so an empty drain destroys
the subscription rather than ending one pass, and the sender's bound id goes stale. This is
intentionally **not** repaired by extending the old DONE/`ids` mechanism. The compatibility
MVP fixes Feed-native incremental async `send`/`receive`; final F5 replaces lifecycle ownership
with execution-owned `Publisher`/`Subscription` handles so cleanup no longer depends on a user
drain. The strict xfail `TestSubscriptions::test_idle_drain_returns_promptly` in
`tests/public/test_pipeline.py` marks the gap for the replacement.

## 25. Conversion — export converters (shipped)

> **Partial.** Batch/dataframe path (Arrow/Polars/SQL) → [database-transforms.md §25](gameplans/database-transforms.md#25-conversion-and-dataframe-integration).

Meza-backed export converters ship as the typed `Formats` `StrEnum` (stable `riko` surface, renamed
from the earlier `Targets`): `csv` / `geojson` / `json` / `jsonl` / `ofx` / `qif` — serialized
representations only. `CONVERSION_FUNCS` (`riko/io/_serialization.py`) is keyed by `Formats` members (`jsonl`
maps to riko's `records2json(newline=True)` (`riko/io/_serialization.py`: meza's defaults with a `CustomEncoder` subclass that writes sets as sorted arrays), not bracket-stripped JSON); `list_formats()` lists
exactly these serialization formats. `export(items, Formats.JSON)` (or the plain string) serializes;
the `list` / `tuple` collection materializations are accepted only by `export()`
(`ExportType = Formats | Literal["list", "tuple"]`), never by `Formats` or `list_formats()`, because
they are not serialized representations. Drift-guarded by `TestExportFormats`. This is riko's
terminal-output surface, distinct from the discovery tree's `Sinks` bucket (sink modules, empty for
built-ins — see §24) and reused by the write-session architecture (see § Write sessions), which
serializes the same `Formats` at a destination. Meza owns conversion work. The Batch/dataframe path
(Arrow/Narwhals/Polars/SQL execution representations selected by capability) is deferred.

## Private execution runtime — `SyncExecution` / `AsyncExecution` (R4B, shipped)

> **Shipped.** The private execution package, its lifetime primitives, execution-local resource
> acquisition, the `EventSink` transport, canonical-workflow preparation (`ExecutionPlan.from_workflow` resolves
> each node's callables once into a `PreparedNode`), and both the **sync** `iter(pipeline)` and **async**
> `aiter(pipeline)` runners — with multi-input port wiring, execution-owned resource injection, and
> node-level sync/async adaptation (async-only under sync via the portal, sync-only under async on a
> worker) — ship now. The plan is a resolution snapshot: it carries no dispatcher and each execution picks
> native-vs-adapter from the pre-resolved callables (`PreparedNode.sync_interface`/`async_interface`, each a `PreparedInterface` whose `native` flag says whether an adapter is needed) without re-inspecting the
> registry. Non-default output ports fail closed (a reachable non-`out` source port or a selected
> non-`out` output raises), and a multi-output splitter node is refused when the plan is built, by
> its declared module type, before any node runs. Sync-under-async and async-under-sync work are both lazy: a sync-only node under async
> execution runs on a worker thread, reads its async inputs from there, and hands back one item per
> `__anext__`; and a loop `embed` that exists only as sync or only as async is adapted at execution time into a
> metadata-preserving wrapper matching the host.
> The fluent authoring surface (`Pipeline.from_module(name, conf=…)`, `.pipe()`, attribute chaining,
> `|`, and `items | Pipeline(…)` source seeding) ships now too.
> `Pipeline.with_execution(...)` stores a frozen `ExecutionSettings`
> (`riko/definitions/_settings.py`; field checks are `require_*` guards attached with
> `validator_from_require` — `ordered` is `validator_from_require(require_instance, bool,
> error=TypeError)`, `concurrency` a `def_from_require` converter that also accepts
> `"auto"` — raising `TypeError`/`ValueError` because the values come from Python call
> sites, and a NaN `shutdown_timeout` is rejected); `with_context`/`with_resource` set the run's
> `Context`. `concurrency=None` is sequential even beside an explicit `thread`/`process` executor (a
> one-worker pool, async limit 1); `concurrency="auto"` sizes the sync pool with `get_worker_cnt`
> (cores ×2 for threads) and the async limit from `concurrency_limit`. `ExecutionSettings`
> derives a `SyncPolicy`/`AsyncPolicy` (`sync_policy`/`async_policy`):
> sync maps loopable nodes over one shared pool (`_PoolLifetime.flat_map` in `riko/execution/_pools.py`) with
> sliding `submit` windows on a `concurrent.futures` executor that pull the source no further ahead
> than the pool width (a worker process that dies fails the run with `BrokenProcessPool`; an early close or a
> failure terminates and joins every still-busy worker process, read from the executor's `_processes`,
> since `cancel_futures` stops only queued work, and waits out busy threads, which cannot be stopped; the
> execution releases the pool before unwinding its exit stack, so no worker outlives a resource); async maps through
> `async_map_stream`/`async_map_ordered_stream` (fixed ordered batches; the sliding window waits on
> R7's dedicated-task hosting) under one shared `Semaphore` budget, and the process
> executor is refused under async. Concurrent pulling of fan-in branches is deferred to R7.
> Cutover steps 2–5 are done (ordered checklist: [v1-cutover.md](gameplans/v1-cutover.md); step 5
> deleted the v1 compiler on 2026-10-03): the fixture trees hold `WorkflowDocument`s,
> the console scripts run, convert, and generate from canonical v2 through
> `Workflow.parse`, `riko/cli/_document.py`, and `riko/runtime/_compile.py`, and the v1 pipe/collection classes were
> deleted on 2026-10-02 (`54b53c29`), leaving `riko/runtime/_export.py` with `Formats`, `export`, and
> `list_formats`.

`riko/execution/` (the `execution` layer) hosts the one-shot executions a pipeline run
creates. Each owns an exit stack and a sync/async bridge as sibling lifetime primitives rather than
deriving one from another. `AsyncExecution` owns no task group: nothing on the run path spawns tasks,
and a group entered in the consumer's task would sit open across every `yield` of
`Pipeline.__aiter__`, so a bare `break` (finalized later from another task) would cancel the
caller's scope. Task hosting for fan-out belongs to R7. `riko/execution/_adapt.py` holds what the two
executions share across the sync/async boundary: `require_stream`/`require_async_stream` (the one boundary
that narrows a resolved pipe's raw output to an item stream, earned by the `is_splitter` guard on the
pipe's declared type rather than by reading its output), `async_drain(source, call)` (an async stream re-exposed as a lazy sync iterator; the sync execution's
portal drain and the worker-side upstream reader are the same function with a different `call`),
`pull_stream(...)` (a sync iterator re-exposed as a lazy async stream), and the
`adapt_embed`/`async_adapt_embed` sync/async loop-embed wrappers.

- **`SyncExecution`** runs synchronously behind an `ExitStack`; async-only components run through a
  lazily started `BlockingPortal` (memoized via `functools.cached_property`) that is entered onto the
  exit stack, so shutdown stops the portal (joining its tasks) as part of the stack's LIFO unwind.
  This is sound because sync execution rejects async-native cleanup, so no owned cleanup ever needs
  the portal alive.
- **`AsyncExecution`** runs behind an `AsyncExitStack`; blocking sync components run on a worker
  thread. Shutdown unwinds the stack behind a cancellation shield within the optional shutdown timeout,
  so ambient cancellation of the shutdown task can never skip cleanup.
- Shutdown order is explicit (stop accepting work → shielded unwind), not generic exit-stack
  LIFO. The primary execution error is threaded into the exit stack's `__exit__` / `__aexit__`, so a
  resource context manager observes, replaces, or suppresses it under normal Python semantics and the
  execution surfaces the returned suppression. Plain cleanup callbacks (`callback`,
  `push_async_callback`, and every Riko-registered cleanup built on them) are wrapped so a failure
  is recorded rather than raised, which is what keeps a callback from replacing the primary error;
  an exhausted shutdown timeout (`TimeoutError`) is recorded the same way. `_report_shutdown` then raises: a lone cleanup failure with no primary error bare; several
  with no primary as an `ExceptionGroup`; and any cleanup failures beside an unsuppressed primary
  (or beside the exception a native context manager replaced it with) as a `BaseExceptionGroup`
  led by that primary. A native replacement with no cleanup failures propagates bare.

**Resource acquisition.** `acquire` / `aacquire` resolve a `Resource` at most once (single-flight,
keyed by resource identity); a repeat returns the first value or replays the first failure.
Concurrent first-use of one lazy resource under `aacquire` is single-flight too — a per-resource
in-flight gate makes waiters await and replay the leader's outcome rather than resolving twice.
A `Resource` stores the plan its constructor classified: `ExternalPlan` / `OwnedPlan` /
`ValueFactoryPlan` / `SyncLifecyclePlan` / `AsyncLifecyclePlan` (`riko/types/_resource.py`, private;
`Resource._plan`), built by `build_factory_plan`/`build_lifecycle_plan`. `strategy`
(`ResourceStrategy`), `async_native`, `external`, and `value` derive from it. The executions `match`
on `resource._plan` inside the recorded acquisition (so a failing factory is replayed like any other
outcome); the records are passive data, and `call_factory`/`build_context_manager`
(`riko/execution/_resource_acquisition.py`) thaw fresh argument copies each time. A generator function's `enter` is a module-level partial, so the plan pickles. Cleanup rides the exit stack: owned → `close`/`aclose`,
value-factory → cleanup callback, lifecycle → context-manager entry. Explicit `cleanup` is
authoritative. The two executions adapt work across sync/async as mirror images, classifying async-vs-sync
with the same predicates (`is_async_callable`/`is_async_closeable`/`is_sync_closeable`, read through the plan records' `is_async`/`requires_async_cleanup`).
Under `SyncExecution`, async value *production* bridges through the portal, but async-native
*cleanup* — an async cleanup callable, an async-native lifecycle, or an `aclose()`-only owned value —
is a permanent boundary: it raises `InvalidPipelineError` before the resource is acquired, so no value
is produced and no lifecycle entered behind the rejection. Under `AsyncExecution`, blocking sync work
is instead offloaded to a worker thread: a sync value factory, a sync cleanup callback, and an owned
sync `close()` run through `aclose_with` over `_asyncify_call` (an unguarded worker seam, because cleanup runs while the
execution is closing, when the guarded `run_sync` would refuse; an awaitable the sync cleanup returns is then
awaited on the loop, while `SyncExecution`'s `close_with` refuses one with `InvalidPipelineError`), and a sync context-manager lifecycle
is entered through a `_WorkerContext` async wrapper so both `__enter__` and `__exit__` run off-loop with
exception info preserved.

**Resource-model shape.** `Resource` stores `_plan`, `credential`, and `lazy` — no private subclass
hierarchy and no field-pair invariants. `OneShotResource` / `ReusableResource` remain as user-facing
marker types (`reusable` is `isinstance`); `Resource(value, cleanup=)` builds an `OwnedPlan` in its own
`__init__` and the alternate constructors set fields through a private builder. `Resource` itself has
no open/close behavior: the execution's `acquire`/`aacquire` drive its `_plan` and clean up (owned
values through `close_resource`/`aclose_resource` in `riko/execution/_resource_cleanup.py`).
`Resource`, `ReusableResource`, and `OneShotResource` are on the stable `riko` surface; `ResourceStrategy`
is on `riko.types`, and the plan records are private (2026-10-28 ruling). A `contextmanager`/`asynccontextmanager` factory is
recognized by the decorator's shared helper code anywhere in its `__wrapped__` chain, so another
`functools.wraps` decorator around a generator function leaves it a generator lifecycle.

**External-resource proof.** `tests/internal/test_execution.py` proves the lifetime holds a
genuinely external resource — a real HTTP client against the loopback server
(`@pytest.mark.simulated_network`), not a synthetic object — under both sync and async execution,
across eager open + cleanup, the async-under-sync rejection boundary, and mid-run failure rollback;
failure-induced cancellation of execution-spawned tasks moves to R7 with the task hosting it needs.
The foundation semantics are proven directly: ambient cancellation
of the shutdown task still unwinds resources, a resource context manager receives and can suppress the
primary error, a lone cleanup failure raises bare, concurrent first-use is single-flight, and
async-native cleanup is rejected before any value is produced. Deferred to R11
(provider sessions): true lazy-open-on-first-use — `lazy=` is recorded but every bound resource is
acquired, used or not — and resource-to-resource dependency ordering.

**EventSink transport.** Each execution owns an `EventSink` with a no-op default (`riko/execution/_execution.py`); `execution.emit(event)` dispatches opaque event values. R4B owns dispatch and lifetime only;
later phases define the semantic events they carry (e.g. R5C `WriteResult` / `ActionResult`).

**Preparation and the sync runner.** A `Workflow` is built into an `ExecutionPlan`, then
run:

- `Workflow.index` builds the shared `GraphIndex`, its
  only builder since the v1 compiler's `_index_pipe_def` was deleted at cutover step 5 (2026-10-03)
  and `Workflow.validate()`'s separate cycle walk folded into it (2026-10-05). Every declared node is
  kept (disconnected nodes retained) and all named outputs preserved.
- `Context` and `Resource` are frozen, slotted attrs classes with `eq=False` (identity equality: the
  execution caches key on `Resource` identity). Field converters freeze `inputs` and the plan records' `args` and
  `kwargs` into `FrozenDict`/tuples (a non-mapping `Context` `inputs` raises `TypeError`); the
  resource plan `thaw`s factory arguments into fresh dicts/lists/sets for each call, so a factory
  sees plain mutable values; a `FrozenDict` passes through unchanged, so `attrs.evolve` in
  `Context.replace`/`with_resource` re-freezes nothing. Set-only-internally fields use private init
  aliases (`Context(_resources=...)`) while staying public attributes. `Resource` has a hand-written
  `__init__` that validates the owned-value path and stores an `OwnedPlan`; the alternate
  constructors set `_plan`/`credential`/`lazy` through `_from_plan`; `Context` accepts only
  `ReusableResource` values in `_resources`.
- One run loop: `run_pipeline`/`arun_pipeline` (`riko/runtime/_run.py`) back
  `Pipeline` iteration, and `build_workflow_pipes` (`riko/runtime/_workflow_pipes.py`) builds on them
  for both generated workflow modules and named `WorkflowDocument`s, which the resolver binds to
  the dispatcher that loaded them.
- `ExecutionPlan.from_workflow(flow, dispatcher)` (`riko/execution/_prepared.py`; the dispatcher is required — any `Dispatcher`, which runtime's `ResolverDispatcher` satisfies) resolves each node's synchronous and asynchronous callables once,
  then the constructor's `ExecutionPlan.validate()` validates the `Workflow` and shares its index; the plan pairs each with its
  graph node into a `PreparedNode` — the graph `ModuleNode` plus a `ResolvedModule` (`name`, `conf`, `sync_pipe`/`async_pipe`, either
  `None` when that interface is absent) and, for a loop node, a second `ResolvedModule` for its embed
  (the embed is an implementation, not a graph node, so it carries no id/options/resources) — and reads each output's required
  subgraph from the index (`GraphIndex.required`, the output node plus its `descendants` over
  `upstream`, derived inside `GraphIndex`). The returned `ExecutionPlan` is a resolution snapshot: it holds
  no dispatcher, so a later registry change cannot alter what a built plan runs. No node runs and no
  resource is acquired at build; an unresolved module raises `UnsupportedModuleError` and a node family
  with no runtime raises `InvalidPipelineError`.
- Native-wins reads capabilities at build: `ResolverDispatcher.require_interfaces(name)` reports the
  available `pipe` / `async_pipe` interfaces (`ModuleDefinition.interfaces` for registered modules,
  `load_interfaces` for built-ins), and the chosen callables come from `resolve`. At run time
  `ResolvedModule.select_sync()`/`select_async()` return the native callable when present, else the
  sync or async counterpart's callable (`AnyModuleWrapper`), touching no registry. A `ResolvedModule` whose two callables disagree on `loopable` or
`sequential_inputs` raises `InvalidPipelineError` (`_is_consistent`), so either slot answers for the
module. `ResolvedModule.is_async_pipe(pipe)` is a
  `TypeIs[AsyncModuleWrapper]` guard keyed on slot identity (`pipe is self.async_pipe`), so it narrows the
  callable with no cast and works for undecorated callables (documented `ModuleDefinition(sync_pipe=plain)`
  carries no `isasync`). `WorkflowResolver.require` tags a stored workflow's interface with the `isasync` of the
  slot it loaded rather than guessing from the callable; the `workflow` decorator
  (`riko/runtime/_workflow_pipes.py`), which tags a copy of a hand-written workflow module's pipe and
  leaves the original untouched, alone defaults it from `is_async_callable`/`isasyncgenfunction`. A callable filling both slots is rejected at
  construction, since slot identity could not tell its mode.
- `SyncExecution.run(plan, output="default", *, seed=None)` runs only the selected output's dependency
  subgraph in topological order and returns that output's stream, feeding unwired default inputs at one
  normalization boundary: a node with no default (`in`) edge receives the internal one-item default seed
  unless it has a positional (`in:N`) edge, in which case its default input is empty (so `union` with
  only secondary inputs wired never sees the default seed as data); named value ports alone do not
  suppress it (`PreparedNode.takes_default_seed`). Unseeded, every node that takes the default seed must be self-starting
  (`ExecutionPlan.require_self_starting`, 2026-10-24) — a source module (`ResolvedModule.is_source`:
  declared `subtype == "source"`; missing metadata is not a source, a `CallableNode` never is) or a value
  feeder (no output's node, at least one outgoing edge, all entering named `in:<name>` ports) — so the
  default seed never reaches output; any other node that takes it raises `InvalidPipelineError`
  ("requires a seed"). Every
  module node's `options` are applied as call options when the node is prepared, and a loop node's pipe receives its embed's
  `conf` (`PreparedNode.embed_or_self_conf`). An adapted node (async-only pipe under sync execution) runs through the execution's
  blocking portal: `_async_drain` pulls the async stream one `__anext__` at a time on the portal loop and
  re-exposes it as a lazy sync `Stream`. A reachable non-`out` source port or a selected non-`out` output
  fails closed with `InvalidPipelineError` (executable port-keyed delivery is R7).
- `AsyncExecution.arun(plan, output="default")` is the async counterpart, returning an `AsyncStream`.
  Native async nodes chain natively; an adapted node (sync-only pipe under async
  execution) runs off the event loop through the bridge and nothing is materialized. `_run_sync_node`
  starts the sync pipe on a worker thread through `run_sync` (asyncer's `asyncify`) and returns
  `pull_stream(...)`, which pulls one item per `__anext__` as the consumer demands it; the pipe reads its
  async primary source and every async secondary input (`others`, named ports — `_bridge_inputs`) lazily
  from the worker through `anyio.from_thread.run` (re-exposed by `riko/bado/_backend.py` as
  `run_from_thread`). There are no background tasks and no channels, so backpressure is pure demand, an
  error raises at the pull that hits it after every earlier item has been yielded, and abandoning or
  closing the async stream closes the sync pipe's generator off-loop through the unguarded `_asyncify_call`
  seam (which still works while the execution is shutting down). Async source/inputs are typed
  `AsyncItems` (`AsyncIterable[Item]`) and outputs `AsyncStream`.
  *Design note:* the earlier plan's "bounded channel" was replaced by this demand-driven pull because
  asyncer offers no iterator bridge and the pull shape needs no task-lifetime management; what it gives
  up — thread affinity across yields, and one item of producer/consumer overlap — was never promised by
  the runtime.
- Loop `embed` is the node field `ModuleNode.embed` (`Embed`: `name`, `conf`, optional `id` — a closed
  key set checked at construction by the field's converter chain against the `Embed` TypedDict, an
  omitted `conf` filled with `{}` first so `Embed.conf` stays required for its readers, then deep-frozen;
  `LoopConf` is deleted and a loop node's own `conf` is empty; documents carry a node-level `embed`
  key only when set; `Pipeline.pipe`/`from_module` take `conf=`/`options=`/`embed=` and `|`
  composition copies all three; generated modules render `embed=Embed({...})` through the shared
  `render_value` literal renderer, which keeps conf keys verbatim — no lowercasing), and the loop's
  `emit`/`count`/`assign`/`field` live in `ModuleNode.options`
  (a `CallOptions` record; serialized only when an option is set). The
  build resolves the embed into `PreparedNode.embed` (a `ResolvedModule`) and mode-selects it
  the same way; the loop wrapper is prepared with the node's `options` and the runner forwards `embed=<callable>` with each call. The embed is re-selected
  against **whether the host pipe actually runs sync or async** (`select_embed(embed, host_isasync=, run_sync=, drain=)` in `_adapt.py`, which each
  execution calls with its own adapters), so an adapted loop node gets an embed matching how it really runs. On
  adaptation the runner forwards a synthesized wrapper matching the host:
  `adapt_embed(embed, drain)` / `async_adapt_embed(embed, run_sync)` copy the wrapper's
  discovery metadata (`name`, `type`, `subtype`, `subtypes`, `pollable`, `loopable`) and set `isasync`
  to match the host, leaving `__wrapped__` unset, so `loop_embed_sync`/`loop_embed_async`, `is_subpipe`,
  and `bind_subpipe` treat the adapter as a native embed. An async-only embed under a sync host is
  drained per item — through the portal on the main thread, or through `run_from_thread` when the host
  pipe itself runs on a worker; a sync-only embed under an async host runs per parent item off the event
  loop and returns its results as a list, bounded by the per-parent result count. The loop's
  `count="first"` early-close therefore does not stop a sync-only embed under an async host early
  (accepted; strict-xfail tripwire `test_arun_count_first_stays_lazy_for_a_sync_only_embed`), while an
  async-only embed under a sync host stays lazy and closes promptly. Loop stays a registered
  module — there is no `LoopNode` (R9 forbids one).
- Each node's incoming edges are wired by port grammar: bare `in` is the positional source, `in:N` ports
  become the ordered `others=[...]` list, and `in:<name>` ports pass as the named stream kwarg.
- A node's declared `{slot: name}` resource binding is injected as a `resources` view whose values come
  from execution-owned `acquire`/`aacquire` (single-flight + exit-stack cleanup), resolved against the
  execution's `Context`; a name absent from the Context raises before any sibling is acquired. Providing
  resources into the `Pipeline` surface itself is deferred.
- `run_pipeline` / `arun_pipeline(definition, dispatcher, *, seed=None)` (`riko/runtime/_run.py`, plain
  generators) own the execution lifetime (`with SyncExecution() as e: yield from e.run(plan, seed=seed)` /
  the `async with AsyncExecution()` analogue), so early close, exhaustion, or failure unwinds upstream
  feeds and the exit stack.
- **Per-run seeds and `Pipeline.open()` (R4C, 2026-10-24).** `pipeline(seed=None, /)` and
  `seed | pipeline` return a private `_PipelineStream` (`riko/runtime/_run.py`) behind the public
  `riko.types.PipelineStream[T]` protocol: single-use, sync- *and* async-iterable, and its own iterator
  in both modes, so `for x in pipeline(items)` keeps the run object alive for the
  loop and its `__del__` cannot fire mid-iteration. It creates the `run_pipeline`/`arun_pipeline`
  generator on first `iter`/`aiter`; a second `iter()` on a sync-started stream returns itself;
  iterating after close yields nothing; iterating in the other colour after starting raises
  `PipelineStateError`. Started
  and garbage-collected unclosed, it emits a `ResourceWarning` (the `io.FileIO` / asyncio event-loop
  precedent). It is not a context manager: its runtime `__enter__`/`__aenter__` raise `TypeError`
  pointing at `open()`, and the protocol omits `__enter__`/`__exit__`/`__aenter__`/`__aexit__` so
  pyright reports `with pipeline(items)` (pyright 1.1.414 does not report a `@deprecated` dunder used
  through `with`). `pipeline.open(seed=None, /)` returns a private `_PipelineRun` behind
  `riko.types.PipelineRun[T]`: `with` yields the stream as an `Iterator[T]`, `async with` as an
  `AsyncIterator[T]`, and block exit closes it in the opening task, including on `break`.
  `__iter__`/`__aiter__` are the unseeded run (`iter(self())`). `__ror__` accepts what `_is_seed` admits
  (`is_streamlike` or awaitable, never a `PipelineDefinition`; Python tries a subclass right operand's
  `__ror__` first and a `Pipeline` is iterable), so `pipeline_a(items) | pipeline_b` feeds one run into
  another. A seed of `None` means no seed; `Pipeline()(items)` is the identity stream. The seed type is
  `InputLike` (renamed from `SourceLike`). `Pipeline(source=…)`, `PipelineDefinition.source`, and
  `replace(source=)` are deleted (unreleased, no deprecation).
- **A node-less pipeline streams its seed** (2026-10-04; one execution model since 2026-10-05). A
  seeded run of a `Pipeline` with no module nodes runs the **identity plan**: `ExecutionPlan.from_workflow`
  accepts a completely empty workflow (no nodes, edges, or outputs — `Workflow.is_empty`) without
  `Workflow.validate()`, and `SyncExecution.run(plan, seed=…)` / `AsyncExecution.arun(plan, seed=…)`
  stream the seed unchanged as the plan's `default` output, through the same
  `_open_seed`/`_aopen_seed` boundary a seeded plan uses (awaitables and async iterables
  resolve; a mapping is one record; under sync execution a value that is both sync- and async-iterable is read synchronously).
  `run` always takes a plan (there is no `plan=None` path). `_require_seed` raises
  `InvalidPipelineError` for any other output name, and for an empty plan without a seed, so an unseeded
  `Pipeline()` still fails `workflow has no nodes`; a node-less workflow that
  declares outputs or edges is not empty and still fails validation.
- **One index per workflow** (2026-10-05). `Workflow.index` is a `cached_property`, so
  `ExecutionPlan.validate()` (which runs `Workflow.validate()`) and the plan's `index`
  share one `GraphIndex` (`test_execution_plan_indexes_the_workflow_once`); `evolve` yields a fresh
  workflow with its own cache.
- **`first(seed=None, /, *, default=MISSING)` / `afirst(...)`** read one item and close the run before
  returning (`with self.open(seed)` / `async with self.open(seed)`); with no item and no `default` they raise
  `EmptyPipelineError` (`PipelineError` + `LookupError`, exported from `riko`), so a bare
  `StopIteration` never leaks into an enclosing iterator. A bare `break` out of `async for` over a
  `Pipeline` is safe but releases the run only when the abandoned generator is garbage collected
  (regression
  `tests/public/test_pipeline.py::TestPipelineStream::test_bare_break_leaves_the_callers_cancel_scope_intact`)
  and warns with a `ResourceWarning`; `async with pipeline.open()` is the prompt-release form.
- **Fluent authoring** derives definitions immutably in the definitions layer, with no
  normalize/runtime import: the canonical constructor takes `(workflow)` — it accepts a
  `Workflow` (or defaults to the empty `Workflow`), raising `TypeError` on any other positional
  value — while the `Pipeline.from_module(name, conf=…)`
  classmethod seeds one `ModuleNode`; `.pipe(name,
  conf=…)`, attribute chaining (`pipeline.sort(conf=…)` — underscore and mapping names raise
  `AttributeError`), and `|` with a name each mint a
  `<name>-<occurrence>` node id (`Workflow.get_node_id`, the id `normalize_workflow` gives an appended node without one; both use `get_free_occurrence`),
  append the node plus a `StreamEdge` from the current default output, and re-point
  `outputs["default"]` (`Workflow.with_node`); prior nodes/edges are shared by reference. `a | b`
  appends `b`'s whole workflow (`Workflow.with_workflow`): a clashing `b` id gets the next free
  `<name>-<occurrence>` (so `|` is associative), `a`'s default output feeds `b`'s single node with an
  open default `in` port, and every node field carries over through `evolve`. `b`'s context may only
  add resources (combined by name, a different definition under one name raises); its mode/inputs/test
  flag or non-default execution settings raise `InvalidPipelineError`. A function or `(name, conf)`
  tuple on the right raises `TypeError` (the function hint names `.map`), and `stream | "name"`
  raises a compose-first `TypeError` (`_PipelineStream.__or__` returns `NotImplemented` otherwise, so
  `stream | pipeline` still seeds). A run's
  seed (`pipeline(items)` / `items | pipeline`) never touches the definition, so serializing a
  pipeline never captures items; `run(plan, seed=…)` delivers it to one node
  (`ExecutionPlan.require_seed_target`: an open node is one with no edge into its bare default `in`
  port — `GraphIndex.is_open`, 2026-10-23; the seed feeds the single open node that is not
  self-starting, else the single open node; otherwise `InvalidPipelineError`) while other open nodes take the
  default seed and must be self-starting. The seed is an `InputLike` (`Item | ValueFeed | Awaitable[Item | ValueFeed]`, a `ValueFeed` being any sync/async iterable of item values,
  `riko/types/_streams.py`) opened once per run — `SyncExecution._open_seed` awaits an
  awaitable through the portal and drains an async-only stream through it, `AsyncExecution.
  _aopen_seed` awaits and wraps, both sharing `normalize_items` (`_adapt.py`: a mapping or
  primitive is one item, any other iterable is the stream) and both registering a generator seed's
  `close` on the execution's exit stack (the async side also an async generator seed's `aclose`), so
  a seed abandoned mid-run is closed when the execution exits — so `Pipeline.__call__`, `__ror__`
  (`is_streamlike` or awaitable, never a `PipelineDefinition`), and the generated module's `pipe(item)` hand
  the raw value through and the helpers below `run` keep their wide `Items`/`Feed` parameters. An
  async `processor` node fed an async stream maps it lazily and in order (`_aprocess_stream` in
  `riko/modules/_decorators.py`, a bounded ordered window) instead of treating the stream object as
  one item. Closing the node's stream (`_AsyncWrapperStream.aclose`) closes that window and its
  source at once, not at garbage collection. `ExecutionPlan.from_workflow` also refuses, before any node runs, a source port feeding more
  than one stream edge (`Workflow.require_executable()`), the fail-closed companion of the non-`out` port guard
  until R7's port-keyed delivery; the shape stays valid canonical structure under `validate()`.
  Sparse positional inputs (`in` + `in:2`, legacy `_OTHER2`) execute as an ordered `others` list,
  `in:0`/`out:0` are grammar errors in `parse_port`, and per-module fan-in arity waits on the
  module port contracts. Callable `.map`/`.flat_map` are deliberately not shipped —
  callable-pipes owns them; a strict-xfail tripwire in `tests/public/test_pipeline.py` flips
  when they land. Tests: `tests/public/test_pipeline.py` plus seeded-run and end-to-end
  coverage in `tests/internal/test_execution_plan.py`.

**Node-thread budget** (2026-10-16). Under `AsyncExecution` a node without an async implementation
holds a worker thread while it pulls its upstream, so a sync-only chain needs threads at once. All
async executions on one event loop share one budget (`RIKO_NODE_THREADS`, default 40; an AnyIO
`RunVar` in `riko/execution/_async_execution.py`). Each run reserves its whole demand
(`ExecutionPlan.get_thread_demand(output, mapped=)`: a thread holder scores one plus the most any one
input holds; a node whose module reads its inputs one at a time (`sequential_inputs`, derived for
`union`/`join` by `has_sequential_inputs` in `riko/modules/_derive.py` and stamped on the wrapper) the
most any one input holds; other nodes the sum of their inputs) before reading anything, so runs never hold part of
a chain while waiting for the rest. A run needing more than the budget, or more than this execution's
own open output streams leave free, raises `InvalidPipelineError`; other executions' runs wait.
`_ReleasingStream` returns the threads when the output stream ends, fails, or is closed (even before its
first item), and the execution's exit stack returns any it still holds.

**Process executor ships each call once** (2026-10-16). `build_item_call`
(`riko/execution/_concurrency.py`) pickles a mapped node's prepared call once on first pull; each task
carries those bytes and `run_shipped_item` unpickles them through a per-worker `lru_cache`
(`settings.shipped_call_cache_size`, `RIKO_SHIPPED_CALL_CACHE_SIZE`), so a call is rebuilt once per worker rather than once per item (measured
~22–30% faster per item on a four-worker pool). The thread executor maps the call directly.

**Prepare once per plan** (2026-10-13). A node's module is prepared once per execution plan, not
once per item: `PreparedNode.sync_interface`/`async_interface` (cached `PreparedInterface`s) call
`ModuleWrapper.prepare(*extras, conf=, **options)` — implemented for every wrapper kind — and the
executions call `interface.call(item, context=..., **extra)`, supplying only the per-item
context and the secondary input streams, `resources`, or `embed`. The decorators' call records
`_PreparedProcessor`/`_PreparedOperator`/`_PreparedSplitter` share the generic attrs base
`_PreparedCall[M_co]` (the decorator, wrapper, prepared module, and prepared options, plus derived
`field`/`count`/`parser`), which subclasses the `PreparedCall` protocol. `M_co` is an explicitly
covariant `TypeVar` so each decorator's `call_record: type[_PreparedCall[Module[bool]]]` accepts its
subclass: PEP 695 inferred variance turns invariant when pyright targets 3.13+, where the frozen
record gains a `__replace__` taking `module`. A
plain wrapper (a stored-workflow pipe, a sync/async adapter) is prepared by `prepare_call`/`build_call`
(`riko/definitions/_wrapping.py`), and `stamp_wrapper_meta` attaches a default `prepare`. `PreparedModule`
(`riko/modules/_prepare.py`) is a frozen attrs record of plain values (name, merged conf, options,
extras, defaults; all but the name default) whose `assign`/`emit` (read from the options), `is_conf_parsed`/`is_dynamic`/`static_conf`/`parsers`/`casters`/
`static_casted` are cached derivations, so it pickles and the process executor ships it. Dynamic-conf
detection sees the node's extras, which `PreparedNode.extras` derives from its incoming edges
(named ports, `others`, `resources`, `embed`). Call
options are typed: `RawCallOptions` (emit/assign/field/count, the `**options` keyword form) and
`ContextOverrides` (mode/inputs/test, mirroring `Context.replace`; `_resolve_context` is
`base.replace(**overrides)`) live in `riko/types/_options.py` (re-exported from
`riko.types.modules`), and the decorators derive their option-name sets from them with
`typed_dict_keys`. `RawCallOptions`, `CallOptions`, and `CallOptionsLike` are on the supported
`riko.types` surface. `ModuleNode.options` stores the frozen attrs
`CallOptions` record (each field `| None`, `None` = unset, type-checked per field at construction;
`from_raw` accepts a record or any mapping; `kwargs` returns the set fields as `RawCallOptions`, which
the plan splats into `build_call` and the serializer/codegen emit). `serialize_attrs` leaves out a
nested record with no set fields, so an option-less node stays byte-stable. A drift test in
`TestRawWorkflowFields` keeps the record's fields and types equal to `RawCallOptions` (`| None`).
Direct wrapper calls share `Module._call_direct`, which still prepares with every keyword name as a
per-item input: a direct call cannot tell an input port named like a call option (`tail`'s `count`)
from the option. A decoration option (`skip_if`, `ftype`, …) handed to a direct call or to
`prepare` raises `TypeError` (`Module._validate_call_keywords`) instead of being dropped. One
precedence nuance: when a node both sets a call option and receives a
secondary input stream under the same name (e.g. `count`), the stream wins, as it already did on a
direct call. Measured: `Module.prepare` ran 50 times for 50 items before and once per plan after; a
2,000-item inline `strtransform` run takes ~46 ms. Regressions:
`tests/internal/test_execution_plan.py::TestPreparedCall` and `tests/internal/test_modules.py::TestPrepare`. A loop's embed is prepared the same way once per stream: `bind_subpipe`
(`riko/modules/_assignment.py`) runs the embed's conf and call options through `build_call` and
calls the prepared call per parent item, so the embed is no longer re-prepared per parent
(2026-10-20; conf-parse memoization in `riko/parsing/config.py` went with it).

## Callable nodes — `Pipeline.map` (R4C, shipped)

`PipelineDefinition.map(fn, *, resources, version, identity, **kwargs)` appends a `CallableNode`
(`riko/definitions/_nodes.py`): `fn` (compared by identity), `version`, `identity` (`IdentityMode`
or `None`, inert until R5A), and the keyword arguments frozen JSON-native in `kwargs`. The node is
named after `fn.__name__` when that is an identifier, else `map`; its id comes from `Workflow.get_node_id`.
Construction checks that resource aliases are identifiers and disjoint from the keyword arguments.
Keyword arguments reach `fn` frozen, like `ModuleNode.options`/`ActionNode.params`: a list arrives as a
tuple and a dict as a `FrozenDict`.

- **Resolution.** `ExecutionPlan.from_workflow` resolves every callable node to the built-in `udf`
  module through the dispatcher (`_resolve_callable` in `riko/execution/_prepared.py`), so the
  node's flags (`loopable`), wrapper identity (`require_stream`/`require_async_stream`), and
  interface selection are `udf`'s. Plan validation and `PreparedNode` use
  `Workflow.runnable_nodes` and `require_runnable_only("execution")`; code generation refuses
  callable nodes through `normalize_workflow`, which has no document form for them.
- **Adapter preparation.** `udf`'s parser is not called. `PreparedNode._build_native` builds two
  prepared calls: `call = partial(_gen_stream_results | _agen_stream_results, fn, kwargs)` for the
  stream path and `item_call = partial(_gen_item_result | _agen_item_result, fn, kwargs)` for the
  mapped paths; all four are module-level, so both calls pickle by reference. They pass each value to `fn` as is, splat the
  keyword arguments and then the `ResourceView`, drop `context`, and yield each return value as one
  result. `udf` is resolved but its parser does not run (the gameplan's `fn` riding into `udf` as a
  per-call extra) for two reasons: execution sits below `modules` in the layer DAG, so it cannot import an
  adapter from `riko/modules/udf.py`; and the processor's `_start` (`normalize_input` →
  `setup`/`get_skip`/`get_field`) assumes a `DotDict` item, so skipping `_wrap_item` would mean a
  parallel `_start` branch behind a hidden keyword. Direct `udf.pipe` is untouched.
- **One value vs. a stream.** `PreparedInterface.item_call` is the call an execution maps over
  items one at a time (the sync thread/process pools via `build_item_call`, the async mapped path in
  `AsyncExecution._build_item_call`) and the one `require_process_safe` pickles; it equals `call`
  for a module node. A callable node's `item_call` applies `fn` to exactly one item and its `call`
  iterates the stream one level, so neither inspects an item for list-likeness: a list, tuple, or
  iterator item reaches `fn` whole under every executor.
- **Async `fn`.** When `is_async_callable(fn)`, `_resolve_callable` drops `udf`'s sync pipe, so sync
  iteration takes the existing async-only bridge (`SyncExecution._build_stream` else-branch through
  the portal) and the node is never sync-mapped. Async iteration awaits `fn` via `maybe_async`; a
  sync `fn` under async iteration runs inline like `udf.async_pipe`.
- **Process executor.** `require_process_safe` pickles `node.sync_interface.item_call`, so a lambda or
  closure `fn` fails at planning ("cannot be pickled") and a bound resource fails with "live
  resource values cannot cross a process boundary".
- **Resources.** `Workflow.with_node` declares each appended node's bound Context names on
  `Workflow.resources` (order-stable, de-duplicated), so `Workflow.validate` accepts them; a missing
  binding still fails in `_require_bindings` before acquisition.
- **No document form.** `validate_document_nodes` refuses a callable node in `serialize_graph` and
  `build_raw_graph` (so `Workflow.serialize`, `normalize_workflow`/`Workflow.parse` of a `Workflow`,
  and `compile_workflow` all raise); a raw node with family `"callable"` raises in `_build_node`.
- **Typing.** `map[R]` takes `Callable[[T_co], R] | Callable[Concatenate[T_co, ...], R]` and builds a
  `PipelineDefinition[R]` directly (no cast); `Pipeline.map` builds a `Pipeline[R]` the same way.

Regressions: `tests/public/test_callable_nodes.py::TestCallableNodes`,
`tests/public/test_workflow.py::TestCallableNode`, and
`tests/public/test_workflow.py::TestCallableNodeDocuments`.

## Write sessions — private seam awaiting `WriteNode`

> **Not a user-facing capability yet.** The private sync/async write sessions and `build_write` exist,
> but no production code drives a session: `Pipeline.write(dest)` only declares a validated `WriteNode`,
> and `WriteNode` execution (R5C) will be the sessions' first caller, run under the
> `SyncExecution`/`AsyncExecution` exit stacks. R11 adds provider-native targets/sessions →
> [execution-semantics.md](gameplans/execution-semantics.md),
> [effects.md](gameplans/effects.md), [implementation-sequence.md](gameplans/implementation-sequence.md).
> The shipped `riko.modules.write` module does not use them: it serializes with `serialize_items`
> and writes directly through meza's `io.write` (sync) or `async_write` (async).

The fluent `write()`/`sink()` verbs of the v1 pipe classes were deleted with those classes at
v1-cutover step 4 (2026-10-02). What remains is four durable layers:

- **declarative** — `WriteOperation` (frozen `mode` + unified `keys`), `SupportsWrite` (a destination
  that *reports write capabilities*, it does not itself deliver records; the protocol lives in
  `riko/types/_target_protocols.py`), and `Formats` (`riko/definitions/_write.py`).
- **prepared** — `PreparedWrite` (target + normalized operation + resolved `WriteCapabilities`) is the
  validated object; `WriteOperation` on its own is unvalidated intent. `WriteCapabilities` stores only
  independent facts (`modes`, `fmt`, `incremental`, `match_keyed_modes`, `idempotent_modes`);
  `appendable`/`serializes`/`keyed_modes` are **derived** properties. `build_write` +
  `validate_target_mode` live in `riko/definitions/_targets.py`; `normalize_strs` lives in
  `riko/base/_require_guards.py` so `WriteOperation` can normalize its own `mode`/`keys` (it is a
  dedicated helper, *not* a widened `_iterutils.listize`). `Pipeline.write(dest)` calls `build_write`
  to validate the destination when it declares the `WriteNode`.
- **runtime** — the `SyncWriteSession`/`AsyncWriteSession` protocols (`write` / `finalize` / `abort` /
  `close`) and the `_FileWriteSession` state machine (`_SessionState` OPEN/FINALIZED/ABORTED/CLOSED,
  acquire-once) in `riko/runtime/_write_session.py`. `finalize` commits (idempotent), `abort` abandons,
  `close` **never commits**; the `file_write_session`/`async_file_write_session` CMs only acquire +
  clean up, and `build_write_resource` wraps the sync one as a one-shot `Resource`.
- **host adapters** — `write_through`/`awrite_through` map full-exhaust/graceful-close →
  `finalize` and terminate/failure → `abort`; they are exercised by tests only until `WriteNode`
  execution uses them.

Invariants worth stating:

- **keys are unified** — the caller supplies a single `keys` list because a target's `match_keyed_modes`
  and `idempotent_modes` are disjoint (`match_keyed_modes & idempotent_modes == ∅`, enforced in
  `__post_init__`), so `(target, mode)` alone fixes whether keys mean record-match identity or
  idempotency/dedup identity. There is no separate `idempotency_key`.
- **incremental is a `target × format` capability**, not a global format trait — `File` owns private
  `_FILE_APPEND_FORMATS` / `_FILE_INCREMENTAL_FORMATS`; there are no global `APPENDABLE_FORMATS` /
  `STREAMABLE_FORMATS`. `appendability` derives from `WriteMode.APPEND in modes`.
- **converters own framing, the session owns the destination boundary** — CSV/JSONL converters keep
  their own row/record terminators (no bracket-stripping; JSONL uses riko's `records2json(newline=True)` +
  one final terminator), and the session only repairs an existing append file's missing newline via a
  **binary** tail check.
- `abort` promises no rollback for incremental targets (CSV/JSONL); it only discards staged content for
  framed targets (JSON/GeoJSON). An empty append never mutates the destination.
- the durable public verbs are `read()` / `write()` (terminality is a graph-position property, not a
  verb); there is no `sink()`.
- **runtime-only** — `PreparedWrite`, `WriteCapabilities`, and session strategy are execution-time facts
  and never serialize into the R4A workflow IR.

The target ownership once `WriteNode` executes:

```
AsyncExecution / SyncExecution
   ├── owns the session via its exit stack
   ├── exhaustion       → finalize
   ├── graceful close   → finalize
   ├── failure          → abort
   └── terminate/cancel → abort
```
