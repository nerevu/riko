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
- [14. Sort keys and feed dates (shipped)](#14-sort-keys-and-feed-dates-shipped)
- [23. AnyIO runtime (shipped)](#23-anyio-runtime-shipped)
- [24. Module discovery (shipped)](#24-module-discovery-shipped)
- [Subscription lifecycle — `subscribe` / `publish` (F5a, partial)](#subscription-lifecycle--subscribe--publish-f5a-partial)
- [Compiler graph index (shipped)](#compiler-graph-index-shipped)
- [Canonical value encoder (R2A, shipped)](#canonical-value-encoder-r2a-shipped)
- [Workflow v2 serialization — `serialize_workflow` / `parse_document` (R4A.5, shipped)](#workflow-v2-serialization--serialize_workflow--parse_document-r4a5-shipped)
- [25. Conversion — export converters (shipped)](#25-conversion--export-converters-shipped)
- [Private execution runtime — `SyncExecution` / `AsyncExecution` (R4B, shipped)](#private-execution-runtime--syncexecution--asyncexecution-r4b-shipped)
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

`Stream` and `AsyncStream` differ by iteration mechanism, not by whether the source is finite or
live.

* `Stream` is synchronous iteration.
* `AsyncStream` is asynchronous iteration.
* Boundedness is **not** a declared `Opts` field yet (`Opts.boundedness` / `require_bounded` are planned — [execution-semantics.md §5](gameplans/execution-semantics.md#5-execution-characteristics)); the bound that ships is behavioral, in the §6 async primitives.

The public cross-mode source union is:

```python
type Feed = Items | AsyncItems
```

`Feed` may therefore be a synchronous or asynchronous item source; `AsyncItems`
(`AsyncIterable[Item]`) is the asynchronous iterable type.

Each asynchronous execution resolves the source once and normalizes it to
`AsyncIterator[Item]`. `Awaitable[Items]` sources are awaited. `AsyncItems`
passed directly to an async operator now flows through the wrapper
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

Sync text decoding goes through `riko/io/_reencode.py::Reencoder` (generic over its output type; `join_char` is always the empty value of that type). An empty source reads as empty. A decoded source whose raw first line does not end in the encoded platform newline (a single unterminated line, carriage-return-only endings, or a multi-byte newline encoding such as UTF-16, whose `\n` byte falls mid-character) is re-split lazily by `_gen_lines`: decoded chunks are buffered and split at every `\r\n`/`\r`/`\n` (`LINE_BREAKS`), a trailing `\r` is held for the next chunk, every line but the last gets the platform newline, and an empty last line is dropped, so `read()`, `read(n)`, `readline`, and iteration agree. Any other source passes through untranslated, so a `\r` beside a `\n` stays raw on the sync path while async `TextIOWrapper` translates it (owned by [bado-anyio § 2c](gameplans/bado-anyio-alignment.md#2c-encoding-resolution-precedence-syncasync-parity)). Re-encoding to bytes passes the encoded stream through unsplit. `remove_BOM=True` strips one `U+FEFF` from the decoded text (`_strip_bom`, first non-empty chunk) rather than the raw bytes, so it works for any codec. Decode errors surface on read; a failure while the reencoder is opening closes its source/owner.

**Typing boundary.** Parser outputs are generic over `ItemOrValue`. Processor and operator
wrappers remain `Stream` / `AsyncStream` at the public boundary; splitters are the structural
exception and return cascades. Broader `StreamOrValueStream`-style types remain internal
implementation scaffolding rather than public pipe output contracts.

## 3. Pipe behavior (shipped)

> **Partial.** Remaining lazy-Feed-chaining gaps → [execution-semantics.md](gameplans/execution-semantics.md).

### Pipeline iteration

`SyncPipe`/`AsyncPipe`/`SyncCollection`/`AsyncCollection` and `PipeState` were deleted at
v1-cutover step 4 (2026-10-02, `54b53c29`). `Pipeline` is the one shipped execution
surface and is a reusable definition: each `iter(pipeline)` / `aiter(pipeline)` builds an
execution plan and runs it inside a fresh one-shot `SyncExecution` / `AsyncExecution`
that owns the run's resources for the lifetime of the returned iterator.

```python
for item in pipeline:
    ...

async for item in pipeline:
    ...
```

Both executions stream: the sync path pulls lazily; the async path streams items as the
plan yields them. The old `parallel`/`workers`/`threads`/`pool` arguments, the
`subscribe`/`publish` and `split` conveniences, and `udf(func=…)` through a pipeline have
no replacement yet; the old `parallel`/`workers`/`threads`/`pool` arguments are replaced by
`Pipeline.with_execution()` (since 2026-10-03; see the private execution runtime section
below), which consumes the pool mechanics in `riko/execution/_pools.py`.

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

## 14. Sort keys and feed dates (shipped)

`sort` builds its key with `build_sort_key` (`riko/modules/_iterutils.py`): a
`(present, value)` pair whose `value` comes from `def_itemgetter`. An item lacking the
field is `present=False`, so it is never compared with real values and groups first
ascending / last descending for every rule `type`. A rule `default` substitutes for the
missing field before casting and counts as present, so the item sorts among the rest.
`SORT_FILLER` (`-inf`) remains only for a present value that cannot be cast under the
`float`/`decimal`/date types; `int`/`bool` uncastables take the cast default and `text`
keeps the raw string. `def_itemgetter` keeps its scalar contract because `group_by`
(`count`/`sum`/`regex`) stringifies its result.

Feed entries resolve dates through `resolve_date` (`riko/rss/entries.py`): the first
usable value among the parser's `*_parsed` key and the raw string, parsed by
`normalize_tzinfo` when it is a string. A key is read only when the entry carries it
(so `feedparser`'s deprecated `updated`→`published` fallback is never triggered), a
blank string is skipped, and a string riko cannot parse is skipped with a warning so the
next key is tried; the result is `None` only when no key yields a date. `feedparser`
leaves `published_parsed=None` for formats such as `May 11, 2012 10:01:00 EST`, which
`fastfeedparser` parses itself, so the two parsers now yield the same `struct_time`.
`updated` falls back to the published keys.

## 23. AnyIO runtime (shipped)

> **Partial.** Protocol adapters + the `asyncioreactor` escape hatch → [twisted-protocol-servers.md](gameplans/twisted-protocol-servers.md).

AnyIO is the **sole** async runtime (`riko/bado/__init__.py`); backend selection is purely
"does `anyio` import?" (`backend = "empty" if run is None else "anyio"`). There is **no
Twisted** anywhere in the code and **no `RIKO_ASYNC_BACKEND` env var**. `AsyncItems` is
the asynchronous iterable source type, while `Feed = Items | AsyncItems` is the cross-mode
source union. Async iteration is pull-based (`__anext__` awaited by the consumer).

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
`ModuleSubtype`, and `ModuleCategory = Literal["source","transform","sink"]` (the `get_module_category`
return value) — so `list_modules(category="sink")` → `["write"]`. These are a **separate axis** from
the discovery-tree identifier enums (`Modules`/`Sources`/`Transforms`/`Sinks`, whose member `.value`
is the module id, for `SyncPipe(...)`/`|` chaining): don't confuse them. In particular
`category="Sinks"` (the bucket class name) returns `[]` — the value is `"sink"`, lowercase singular.
(The codegen maps the three category strings to the plural bucket **class** names via `_CATEGORY_CLASS`
= `{"source": "Sources", "transform": "Transforms", "sink": "Sinks"}`.)
`get_module_category` (`riko/ext/_names.py`) buckets each module by **data-flow capability only**.
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
`ModuleRegistry` (`riko/runtime/_module_registry.py`, re-exported via `riko/ext/registry.py`; built-ins
lazy per name, runtime `register_module`/`reset_module_registry`, entry
points under `[project.entry-points."riko.modules"]`; precedence runtime → entry-point → built-in),
`WorkflowResolver` + injectable `ModuleStore`/`DirectoryStore` (`riko/runtime/_workflows.py`; the
directory store parses each workflow document (`WorkflowDocument`) with `parse_document` and yields a `Workflow`,
which `load_definition` returns; core ships no locations; a `register(*, store, documents, replace=False)` / `reset()` lifecycle mirrors the
registry idiom — the process-global is shared by reference, so in-place mutation reaches the façade and
test imports at once), and the `PipeResolver` façade (`riko/runtime/_resolver.py`) doing one symmetric dispatch.
Named-workflow lookup resolves through the façade (`dispatcher.require`); the v1 compiler's
`resolve_module` delegate was deleted with it at cutover step 5 (2026-10-03). Workflow modules expose a stable `pipe`/`async_pipe` entry, so a named workflow resolves exactly
like a built-in. External packages add modules with **no core edit** (`examples/riko-example-ext/`).
The module registry and a private target registry (`riko/runtime/_target_registry.py`, built-in
`FileTarget`, entry points under `riko.targets`) share a generic `Registry[T]` base
(`riko/runtime/_registry.py`) — one three-tier runtime → entry-point → built-in lifetime, each keyed by a
per-domain `_key` hook (module `resolved_name`, target `backend`). The target registry stores target
classes keyed by `backend` and resolves a `Backends` to its target class. The target vocabulary (base
`Target` + `SupportsRead`/`SupportsWrite`/`SupportsActions`, `WriteCapabilities`, `FileTarget`,
`TargetRegistry`, `register_target`) is on the extension surface (`riko.ext`); the `Backends` enum is on
the stable `riko` surface alongside `Formats`. Pipeline-source registration is on `riko.ext` too:
`register_workflow_store(*, package, directory, replace=False)` (primitives only — the store classes and
`WorkflowResolver` stay private per `PRIVATE_RESOLUTION`), with `reset_workflow_resolver` alongside
`reset_module_registry`/`reset_target_registry` in the `riko.ext.registry` submodule.
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
async). Tests: `tests/internal/test_decorators.py`. The decorators must be called before
decorating: a bare `@processor` (no parentheses) would land the function in the positional
`defaults`, so `Module.__init__` rejects a callable `defaults` with `TypeError` at decoration.
Bare-form support (bare = configured with no options) is specified by
`_docs/gameplans/callable-pipes.md`; a strict-xfail tripwire in the same test module flips when
it lands, at which point the guard branch becomes the bare-wrap branch.

**Fluent surface (P9, partial — shipped):** value-taking chaining — `pipe | "name"`,
`pipe | ("name", conf)`, `pipe | SyncPipe(...)`, `items | SyncPipe(...)`, and `.pipe()`/`.async_pipe()`
— plus the `ModuleName` `StrEnum` base and `normalize_module_name` (`riko/ext/_names.py`); a name may
be a `str` or `ModuleName` member anywhere, normalized to its canonical string at the boundary. The
generated `Modules` tree (P9A) shipped — `pipe | Transforms.FILTER` resolves identically to
`pipe.filter()`; see §24.

## Workflow graph index (shipped)

`index_workflow` (`riko/runtime/_graph_index.py`) interprets a validated `Workflow`'s stream edges
into one immutable `GraphIndex` (`riko/types/_compiler.py`). Edge-level `edges`/`incoming`/`outgoing`
keep full port identity in the v2 grammar (`out`; `in`/`in:N`/named value ports); node-level
`order`/`dependencies`/`dependents`/`roots`/`leaves`/`outputs` carry scheduling facts (`leaves` is
derived from `dependents`; `outputs` are the workflow's named outputs). `build_graph_index` assembles
the frozen index (`MappingProxyType`/tuples/`frozenset`) from adjacency, edges, and outputs; `order`
is a strict topological sort, so a cyclic graph is rejected rather than silently reordered (and
`Workflow.validate()` rejects it earlier). Consumers are `build_execution_plan`
(`riko/runtime/_execution_plan.py`) and the sync/async executions, which read the index instead of
rescanning edges. Structure pinned by
`tests/internal/test_prepare_execution.py::test_index_workflow_orders_and_indexes`.

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
existing `normalize_tzinfo`; `struct_time` stays distinct from `datetime`; `-0.0`
canonicalizes with `+0.0`, and infinities/NaN carry stable tags. Cyclic structures raise
`CyclicIdentityError`; unsupported values raise `IdentityEncodingError` (both under the new
`IdentityError` branch of the `RikoError` tree).

`canonical_json(canonicalize(obj))` (via `canonical_bytes`) emits fixed UTF-8 JSON v1 with no
insignificant whitespace, and `digest(obj, domain)` returns a 32-character lowercase
BLAKE2b-128 hex string, domain/version-separated by the fixed `IdentityDomain`
(`fingerprint`/`generation`/`idempotency`/`state-key`) and `IDENTITY_FORMAT_VERSION` folded
into the hashed bytes but not the returned text. `repr_cache` now keys process-local
memoization on `canonical_bytes`, bypassing values that cannot be encoded, so the reversible
`_from_hashable` reconstruction machinery is gone. `NonNullHashable`/`Hashable`
(`riko/types/_scalars.py`) are the aligned static contracts. `Context(identity_encoder=...)`
backend selection is deferred (R3-adjacent); the stdlib encoder is the reference. Tests:
`tests/internal/test_canonical.py` (golden canonical bytes + golden digests + rule matrix) plus
module doctests.

## Canonical Workflow v2 model (R4A.1, shipped)

The structural v2 vocabulary (no execution runtime yet — R4B executes it). Pure contracts live in
`riko/types/_workflow.py` (`Endpoint`, the frozen `Edge` base with its `(node, port)` `port`
property, the `NodeFamily`/`EdgeFamily`/`PortDirection` discriminant literals, `InputRef`, the
`parse_port` grammar helper, and the `Raw*` TypedDicts); the immutable model lives in
`riko/definitions/_workflow.py` — the closed node union
`ModuleNode`/`ReadNode`/`WriteNode`/`CacheNode`/`ActionNode`/`SubscribeNode`, the edge families
`StreamEdge`/`PublishEdge`, the `Workflow` envelope, and the public generic `Pipeline[T]`.

The node/edge model, `Endpoint`, and `Workflow` are all `attrs @define(frozen, slots)` classes.
The six node families share a public **`Node`** base (`id`/`name`/`resources`/`label` + a `family`
`ClassVar` discriminant) and **self-normalize through `field(converter=…)`**: each field resolves its
enum (`Backends`/`Formats`/`WriteMode` via `normalize_enum`), normalizes resource bindings, or freezes
its `conf`/`policy`/`params` mapping — so constructing a node *is* canonicalizing it, and no separate
builder is required. `ReadNode`/`WriteNode`/`ActionNode` carry declarative
`backend`/`fmt`/`mode`/`keys`/`dest`/`params` intent only (no live resource or write session).
`Workflow`'s converters freeze the `nodes`/`outputs`/`inputs` mappings (`FreezeMapping`) and
normalize `edges`/`resources`; it also owns its own structural checks (see R4A.3). Field introspection
uses `riko.types._collections.field_names` (attrs-or-dataclass field names *including* `ClassVar`
discriminants like `family`, which `attrs.fields`/`dataclasses.fields` both drop), never
`dataclasses.*`; derive variants with `attrs.evolve`. `Pipeline` is STABLE (`riko`) and is an
`attrs @define(frozen, slots)` class like the rest of the model — generic `Pipeline[T]` via a
defaulted `TypeVar` (type-parameter defaults need Python 3.13; the floor is 3.12), with its `workflow`
field normalizing `None`/omitted to the empty `Workflow` through the shared `_optional_workflow` converter, so
`Pipeline()` is a valid empty template. The node/edge/`Workflow`/`Endpoint` model is EXTENSION
(`riko.ext`). Tests:
`tests/public/test_workflow.py` plus module doctests. Forward order and the clean-break deletion
ledger: [implementation-sequence.md](gameplans/implementation-sequence.md) R4A.

## Workflow v2 normalization — `normalize_workflow` (R4A.2, shipped)

The single authoring-sugar normalization boundary: `RawWorkflow` in, one `Workflow` out,
so no other subsystem reinterprets shorthand. Lives in `riko/runtime/_normalize.py`
(the runtime home the clean-break placement note assigns, superseding the original
`riko/workflow/normalize.py` sketch); exported EXTENSION as `riko.ext.normalize_workflow`.

It is the **structural, contract-free** pass — no `ModuleRegistry`/`TargetRegistry` lookup. It
assigns node ids, dispatches each `RawNode` to its node family, maps legacy ports to the
canonical grammar, rejects the `src`/`tgt` and `from`/`to` edge shorthands, materializes a `default`
output from a lone leaf, and normalizes shorthand inputs to JSON Schema; malformed structure raises
`InvalidPipelineError`. Dispatch is **dataclass-driven**: `_NODE_BUILDERS: Mapping[str, type[Node]]`
maps each family to its node class, `_build_node` splats the authoring fields into that constructor
(`builder(**fields)`), and `_reject_unknown` validates the keys against the class's
`__dataclass_fields__` — so the node dataclass is the single source of truth for accepted fields, and
the per-field enum/resource/mapping coercion is the node's own `__post_init__` (see R4A.1), not a
normalize-local builder. It reuses `normalize_binding`/`normalize_resources`, `normalize_strs`,
`listize`, and the `is_mapping`/`is_listlike` guards; legacy ports map through an open-ended
`_normalize_port` (`_OTHER<n>`→`in:n`, `_OUTPUT<n>`→`out:n-1`). Closed-schema rejection and the
remaining contract-dependent sugar (format inference from a locator, registered
conf/params/target-config validation) are deferred. The authoring grammar is owned by
[extensibility § E3](gameplans/extensibility.md#e3-canonical-workflow-v2-specification).

The input is typed `WorkflowLike` (`riko.types`) — the `*Like` union of the precise
`RawWorkflow` `TypedDict` (with `RawNode`/`RawEdge`/`RawEndpoint`) and a loose
`Mapping[str, object]`, so a literal gets editor key-completion while any dict still passes. The
`Raw*` TypedDicts are the one hand-written parallel to the canonical dataclasses; a drift guard
(`tests/internal/test_workflow_authoring.py`) derives the expected key set from each node/edge/
endpoint's `fields()` and fails if authoring omits a field (modulo the `type`/`family`/`format`
aliases), so a new node field cannot silently drop out of the authoring surface. Tests:
`tests/public/test_normalize.py` plus module doctests.

## Workflow v2 validation — `Workflow.validate()` (R4A.3, shipped)

Strict structural validation is a **method on the model**, not a standalone function: `Workflow`
owns `validate()` (raises `InvalidPipelineError` on the first violation) and an `isvalid` property
(the boolean wrapper), backed by the `ports()`/`endpoints`/`declared_resources` helpers on the same
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
(`cyclic_nodes` runs a Kahn pass and names the nodes no edge order can run, so a cyclic document
fails here instead of leaking the architecture sorter's error from the graph index); node resource
references resolving to declared top-level `resources`; and a non-empty graph exposing at least one
output (closing `normalize_workflow`'s deferred ambiguous-leaf case). The contract-aware E3.9 rules — undeclared
ports, fan-in arity, registered module/action/target schema validation — are **deferred** because
the module and target contracts declare no ports or configuration schemas yet; they land with that
metadata. Tests: `tests/public/test_validate.py` (builds `Workflow` graphs directly and asserts
`workflow.validate()`/`isvalid`) plus module doctests.

## Workflow v2 serialization — `serialize_workflow` / `parse_document` (R4A.5, shipped)

Deterministic byte-stable canonical serialization of a `Workflow` and its
round-tripping parser. Lives in `riko/runtime/_serialize.py`; exported EXTENSION as
`riko.ext.serialize_workflow` / `riko.ext.parse_document`.

`serialize_workflow(workflow, *, indent=4)` is a thin `json.dumps(workflow, cls=WorkflowEncoder,
sort_keys=True, indent=indent, ensure_ascii=False)` (plus a trailing newline; `indent=None` gives the
compact `separators=(",", ":")` form) — with `sort_keys` ordering map keys at every level, the
same `Workflow` always yields identical bytes for golden-fixture comparison; edge order follows the `Workflow`
while the semantic wiring lives in the endpoints, not the array order. `WorkflowEncoder` (a
`json.JSONEncoder`) renders **every** structural and value type: it emits the `Workflow` envelope
and each `Node`/`Edge` via **reflection** — `_serialize_dataclass` walks a frozen node/edge's
`fields()` and `_serialize_attrs` uses `attrs.asdict(recurse=False)` for the attrs `Workflow`,
both dropping empties (`_has_value`) while keeping required keys — and it coerces the remaining
structural leaves (`Mapping`/`mappingproxy`→dict, `tuple`→list, `Enum`→`.value`). Because node
serialization is field-reflection rather than a per-family branch, a new node field (e.g.
`WriteNode.dest`) serializes automatically with no serializer edit. Canonical
`conf`/`policy`/`params`/`inputs` values are JSON-native by construction: `normalize_workflow`
deep-freezes them through `freeze_value` (`riko/types/_collections.py`), which rejects `Decimal`,
`date`, `set`, `bytes`, non-finite floats, and non-string keys, and turns lists into tuples. The
encoder therefore needs no Python-only value branches and `serialize_workflow` uses `allow_nan=False`.
`parse_document(data)` reconstructs the `Workflow` by reusing `normalize_workflow` on the loaded JSON (a
`WorkflowDocument` is itself a valid `RawWorkflow`), so `parse_document(serialize_workflow(workflow)) == workflow` holds
by value equality and serialization is idempotent. A migrated pipe definition (`PipeDef`) serializes with no v1-only structure: no
`_INPUT`/`_OUTPUT`/`wires`/`src`/`tgt` tokens and no `type:"output"` node — the terminal `_OUTPUT`
pseudo-node lives only in top-level `outputs`. Tests: `tests/public/test_serialize.py` (golden bytes,
per-topology round-trip/idempotency, order-independence, JSON-native nested round-trip by equality,
non-JSON-native value rejection, migrate-emits-no-v1) plus module doctests.

The **CLI v1→v2 cutover** was deferred out of this slice to R4B and has since shipped there
(cutover step 3; see [v1-cutover.md](gameplans/v1-cutover.md)). Every console script was kept
and re-pointed at canonical v2 rather than deleted. `riko/cli/_workflow.py` is the shared
document front door (`DocumentFormat`, `read_document`, `get_document_format`, `normalize_document`,
`require_workflow`); `build-workflow` is the one lenient reader, taking a serialized `PipeDag`, a
serialized `PipeDef`, or a `WorkflowDocument` and always emitting a validated `WorkflowDocument`
(detection picks the reader; a `--format` pin is read as given, never re-detected, and a non-list
`wires`/`modules` falls through to the `PipeDag` reader's `InvalidPipelineError`);
`compile-workflow` and `run-pipe` go through `require_workflow` and refuse anything older. `run-pipe <id>` searches `./examples` and then the checkout's `ROOT_DIR / "examples"` (`get_example_dirs` in `riko/cli/runpipe.py`; listed once when they are the same directory), trying `<id>.py` then `workflows/<id>.json` in each, so example ids resolve from any directory in a checkout or editable install (the wheel ships no `examples`).
`riko/runtime/_codegen.py` is the v2 generator behind STABLE `compile_workflow`, and
`riko/runtime/_migrate.py::parse_dag` replaces `build_pipe_def` as the bare-bones DAG
entry point. `migrate_v1_to_v2` remains the one-shot offline conversion path, now reachable
from the command line through `build-workflow`. The v1 `PipeDef`/`wires` compiler itself
(`compile_pipe_def`, `parse_pipe_def`, `build_pipeline`, `pypipe*.txt`, `_compile_repr.py`,
`riko/types/_pipeline.py`, `tests/internal/test_compile.py`) was deleted at cutover step 5
(2026-10-03); STABLE `COMPILE` is now `compile_workflow` + `parse_dag`, and `extract_dependencies`
(released name) has no replacement beyond reading `Workflow` node names.

## Workflow v1→v2 migration — `migrate_v1_to_v2` (R4A.4, shipped)

A one-shot offline conversion of a `PipeDef` (`modules` plus `src`/`tgt`
`wires`) into `Workflow`. Lives in `riko/runtime/_migrate.py` (the runtime
home the clean-break placement note assigns, superseding the original `riko/workflow/migrate.py`
sketch); exported EXTENSION as `riko.ext.migrate_v1_to_v2`. It is **not** a live loader — v1 is not a
maintained runtime ingress, so it `logger.warning`s that a `PipeDef` was migrated, then emits v2
only.

It reuses `normalize_workflow` for the shared structural pass (port grammar, node families, id
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
name); any other module-level key folds into `conf` with registered `conf` keys winning; a wire target
port that is not an identifier is pythonised (`1_URL` → `_1_URL`) to match how module terminals are
looked up; fully-uppercase v1 `conf` keys (e.g. `URL`) are
lowercased through the compiler's `_lower_keys` so they keep v1's canonical casing. Orphan modules
are **retained** as nodes rather than silently erased — arity/reachability is validation's call.
Malformed structure raises `InvalidPipelineError`; an empty node set is left to
`Workflow.validate()` (the `migrate → normalize → validate` flow of E3.1).

Shared plumbing is reused, not reinvented: the legacy `_INPUT`/`_OUTPUT`/`_OTHER`/`output` tokens are
`riko/base/_config` constants (`INPUT_PORT`/`OUTPUT_PORT`/`OTHER_PORT`/`OUTPUT_MODULE`) also consumed
by `_normalize`; the module and edge splits use `partition` from `riko/base/_iterutils`. Tests: `tests/public/test_migrate.py` plus module doctests.

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

## Private execution runtime — `SyncExecution` / `AsyncExecution` (R4B, shipped)

> **Shipped.** The private execution package, its lifetime primitives, execution-local resource
> acquisition, the `EventSink` transport, canonical-workflow preparation (`build_execution_plan` resolves
> each node's callables once into a `PreparedNode`), and both the **sync** `iter(pipeline)` and **async**
> `aiter(pipeline)` runners — with multi-input port wiring, execution-owned resource injection, and
> node-level cross-mode adaptation (async-only under sync via the portal, sync-only under async on a
> worker) — ship now. The plan is a resolution snapshot: it carries no resolver and each execution picks
> native-vs-adapter from the pre-resolved callables (`PreparedNode.select`) without re-inspecting the
> registry. Non-default output ports fail closed (a reachable non-`out` source port or a selected
> non-`out` output raises), and a multi-output splitter node is refused when the plan is built, by
> its declared module type, before any node runs. Cross-mode work is lazy in both directions: a sync-only node under async
> execution runs on a worker thread, reads its async inputs from there, and hands back one item per
> `__anext__`; and a loop `embed` that exists only in the other mode is adapted at execution time into a
> metadata-preserving host-mode wrapper.
> The fluent authoring surface (`Pipeline.from_module(name, conf=…)`, `.pipe()`, attribute chaining,
> `|`, and `items | Pipeline(…)` source seeding) ships now too.
> `Pipeline.with_execution(...)` stores a frozen `ExecutionSettings`
> (`riko/definitions/_execution.py`; field checks are local `require_*` guards attached with
> `validator_from_require`, raising `TypeError`/`ValueError` because the values come from Python call
> sites, and a NaN `shutdown_timeout` is rejected); `with_context`/`with_resource` bind the run's
> `Context`. `riko/execution/_mapping.py` resolves the settings into a `SyncPolicy`/`AsyncPolicy`:
> sync maps loopable nodes over one shared pool (`open_pool` from `riko/execution/_pools.py`) with
> `apply_async` windows that pull the source no further ahead than the pool width (`Pool.imap`
> deadlocks when chained on the pool's single task-handler thread); async maps through
> `async_map_stream`/`async_map_ordered_stream` under one shared `Semaphore` budget, and the process
> executor is refused under async. Concurrent pulling of fan-in branches is deferred to R7.
> Cutover steps 2–5 are done (ordered checklist: [v1-cutover.md](gameplans/v1-cutover.md); step 5
> deleted the v1 compiler on 2026-10-03): the fixture trees hold `WorkflowDocument`s,
> the console scripts run, convert, and generate from canonical v2 through
> `riko/cli/_workflow.py` and `riko/runtime/_codegen.py`, and the v1 pipe/collection classes were
> deleted on 2026-10-02 (`54b53c29`), leaving `riko/runtime/collections.py` with `Formats`, `export`, and
> `list_formats`.

`riko/execution/` (the `execution` layer) hosts the one-shot executions a pipeline run
creates. Each owns three sibling lifetime primitives — a task group, an exit stack, and a sync/async
bridge — rather than deriving one from another. `riko/execution/_adapt.py` holds what the two
executions share across the mode boundary: `require_stream`/`require_async_stream` (the one boundary
that narrows a resolved pipe's raw output to an item stream, earned by the `is_splitter` guard on the
pipe's declared type rather than by reading its output), `drain_async(source, call)` (an async stream re-exposed as a lazy sync iterator; the sync execution's
portal drain and the worker-side upstream reader are the same function with a different `call`),
`pull_stream(...)` (a sync iterator re-exposed as a lazy async stream), and the
`adapt_embed_for_sync`/`adapt_embed_for_async` cross-mode loop-embed wrappers.

- **`SyncExecution`** runs synchronously behind an `ExitStack`; async-only components run through a
  lazily started `BlockingPortal` (memoized via `functools.cached_property`) that is entered onto the
  exit stack, so shutdown stops the portal (joining its tasks) as part of the stack's LIFO unwind.
  This is sound because sync execution rejects async-native teardown, so no owned cleanup ever needs
  the portal alive.
- **`AsyncExecution`** runs behind an `AsyncExitStack` with an eagerly entered root task group as the
  outermost cancel scope; blocking sync components run on a worker thread. Shutdown cancels owned
  tasks on failure, joins the group, then unwinds the stack behind a cancellation shield within an
  optional teardown budget. The join and unwind are sequenced `try: join / finally: unwind` — not one
  shield wrapping both — so ambient cancellation of the shutdown task can never skip teardown, and the
  task group's own `__aexit__` is never nested inside a child cancel scope.
- Shutdown order is explicit (stop spawning → cancel → join → shielded unwind), not generic exit-stack
  LIFO. The primary execution error is threaded into the exit stack's `__exit__` / `__aexit__`, so a
  resource context manager observes, replaces, or suppresses it under normal Python semantics and the
  execution surfaces the returned suppression. Plain cleanup callbacks (`callback`,
  `push_async_callback`, and every Riko-registered teardown built on them) are wrapped so a failure
  is recorded rather than raised, which is what keeps a callback from replacing the primary error;
  task-group join failures and an exhausted shutdown budget (`TimeoutError`) are recorded the same
  way. `_report_shutdown` then raises: a lone cleanup failure with no primary error bare; several
  with no primary as an `ExceptionGroup`; and any cleanup failures beside an unsuppressed primary
  (or beside the exception a native context manager replaced it with) as a `BaseExceptionGroup`
  led by that primary. A native replacement with no cleanup failures propagates bare.

**Resource acquisition.** `acquire` / `aacquire` resolve a `Resource` at most once (single-flight,
keyed by resource identity); a repeat returns the first value or replays the first failure.
Concurrent first-use of one lazy resource under `aacquire` is single-flight too — a per-resource
in-flight gate makes waiters await and replay the leader's outcome rather than resolving twice.
`build_resource_plan(resource)` (in `riko/execution/_plan.py`) is the one boundary that turns a
declaration into a `_ResourcePlan` carrying a `_ResourceStrategy` (`EXTERNAL` / `OWNED` /
`VALUE_FACTORY` / `LIFECYCLE`); the runtime consumes the plan and never re-inspects the original
generator/context-manager/instance shape. Teardown rides the exit stack: owned → `close`/`aclose`,
value-factory → cleanup callback, lifecycle → context-manager entry. Explicit `cleanup` is
authoritative. The two executions adapt cross-mode work as mirror images, classifying async-vs-sync
with the same predicates (`is_async_callable`/`is_async_closeable`/`is_sync_closeable`/`native_async`).
Under `SyncExecution`, async value *production* bridges through the portal, but async-native
*teardown* — an async cleanup callable, an async-native lifecycle, or an `aclose()`-only owned value —
is a permanent boundary: it raises `InvalidPipelineError` before the resource is acquired, so no value
is produced and no lifecycle entered behind the rejection. Under `AsyncExecution`, blocking sync work
is instead offloaded to a worker thread: a sync value factory, a sync cleanup callback, and an owned
sync `close()` run through `_arun_sync` (an unguarded worker seam, because teardown runs while the
execution is closing, when the guarded `run_sync` would refuse), and a sync context-manager lifecycle
is entered through a `_WorkerContext` async wrapper so both `__enter__` and `__exit__` run off-loop with
exception info preserved.

**Resource-model shape.** The owned/external/lifecycle/factory distinction is data on `Resource` —
the `external` flag plus `factory`/`kind`/`cleanup`/`args`/`kwargs` — not a private subclass
hierarchy. `OneShotResource` / `ReusableResource` remain as user-facing marker types (`reusable` is
`isinstance`, `external` is a field); construction routes through a private builder, and
`open`/`aopen`/`close`/`aclose` dispatch on the data. `FactoryKind` stays input classification only,
never a runtime ontology.

**External-resource proof.** `tests/internal/test_execution.py` proves the lifetime holds a
genuinely external resource — a real HTTP client against the loopback server
(`@pytest.mark.simulated_network`), not a synthetic object — under both sync and async execution,
across eager open + teardown, the async-under-sync rejection boundary, mid-run failure rollback, and
failure-induced task cancellation. The foundation semantics are proven directly: ambient cancellation
of the shutdown task still unwinds resources, a resource context manager receives and can suppress the
primary error, a lone cleanup failure raises bare, concurrent first-use is single-flight, and
async-native teardown is rejected before any value is produced. Deferred until lazy-resource wiring:
true lazy-open-on-first-use and early-consumer abandonment during iteration.

**EventSink transport.** Each execution owns an `EventSink` (`riko/execution/_events.py`) with a no-op
default; `execution.emit(event)` dispatches opaque event values. R4B owns dispatch and lifetime only;
later phases define the semantic events they carry (e.g. R5C `WriteResult` / `ActionResult`).

**Preparation and the sync runner.** A `Workflow` is built into an `ExecutionPlan`, then
run:

- `index_workflow(workflow)` builds the shared `GraphIndex` through `build_graph_index`, its only
  builder since the v1 compiler's `_index_pipe_def` was deleted at cutover step 5 (2026-10-03). Every declared node is kept
  (disconnected nodes retained) and all named outputs preserved.
- `build_execution_plan(workflow, dispatcher=...)` (runtime layer) validates the `Workflow`, builds the shared
  index, and resolves each node's synchronous and asynchronous callables once into a `PreparedNode`
  (`sync_pipe`/`async_pipe`, either `None` when that interface is absent), plus per-output required-node
  subgraphs (computed via `descendants`). The returned `ExecutionPlan` is a resolution snapshot: it holds
  no dispatcher, so a later registry change cannot alter what a built plan runs. No node runs and no
  resource is acquired at build; an unresolved module raises `UnsupportedModuleError` and a node family
  with no runtime raises `InvalidPipelineError`.
- Native-wins reads capabilities at build: `ResolverDispatcher.require_interfaces(name)` reports the
  available `pipe` / `async_pipe` interfaces (`ModuleDefinition.interfaces` for registered modules,
  `load_interfaces` for built-ins), and the chosen callables come from `resolve`. At run time
  `PreparedNode.select(is_async=...)` picks the native callable when present, else the other-mode callable
  tagged `ExecMode.ADAPTER`, touching no registry.
- `SyncExecution.run(plan, output="default")` runs only the selected output's dependency subgraph in
  topological order and returns that output's stream, seeding source nodes at one normalization
  boundary: a node with no default (`in`) edge receives the `{"forever": True}` seed unless it has a
  positional (`in:N`) edge, in which case its default input is empty (so `union` with only secondary
  inputs wired never sees the seed as data); named value ports alone do not suppress the seed. Every
  module node's `options` are forwarded as call kwargs, and a loop node's pipe receives its embed's
  `conf` (`PreparedNode.embed_or_self_conf`). An `ExecMode.ADAPTER` node (async-only pipe under sync execution) runs through the execution's
  blocking portal: `_drain_async` pulls the async stream one `__anext__` at a time on the portal loop and
  re-exposes it as a lazy sync `Stream`. A reachable non-`out` source port or a selected non-`out` output
  fails closed with `InvalidPipelineError` (executable port-keyed delivery is R7).
- `AsyncExecution.run(plan, output="default")` is the async counterpart, returning an `AsyncStream`.
  `ExecMode.NATIVE` async nodes chain natively; an `ExecMode.ADAPTER` node (sync-only pipe under async
  execution) runs off the event loop through the bridge and nothing is materialized. `_run_sync_node`
  starts the sync pipe on a worker thread through `run_sync` (asyncer's `asyncify`) and returns
  `pull_stream(...)`, which pulls one item per `__anext__` as the consumer demands it; the pipe reads its
  async primary source and every async secondary input (`others`, named ports — `_bridge_inputs`) lazily
  from the worker through `anyio.from_thread.run` (re-exposed by `riko/bado/_backend.py` as
  `run_from_thread`). There are no background tasks and no channels, so backpressure is pure demand, an
  error raises at the pull that hits it after every earlier item has been yielded, and abandoning or
  closing the async stream closes the sync pipe's generator off-loop through the unguarded `_arun_sync`
  seam (which still works while the execution is shutting down). Async source/inputs are typed
  `AsyncItems` (`AsyncIterable[Item]`) and outputs `AsyncStream`, matching `runtime/collections.py`.
  *Design note:* the earlier plan's "bounded channel" was replaced by this demand-driven pull because
  asyncer offers no iterator bridge and the pull shape needs no task-lifetime management; what it gives
  up — thread affinity across yields, and one item of producer/consumer overlap — was never promised by
  the runtime.
- Loop `embed` is the node field `ModuleNode.embed` (`Embed`: `name`, `conf`, optional `id` — a closed
  key set normalized at construction by `normalize_embed`, `conf` defaulting to `{}` and deep-frozen;
  `LoopConf` is deleted and a loop node's own `conf` is empty; documents carry a node-level `embed`
  key only when set; `Pipeline.pipe`/`from_module` take `conf=`/`options=`/`embed=` and `|` template
  chaining copies all three; generated modules render `embed=Embed({...})` through the shared
  `render_value` literal renderer, which keeps conf keys verbatim — no lowercasing), and the loop's
  `emit`/`count`/`assign`/`field` live in `ModuleNode.options`
  (`ModuleOptions`, a closed key set validated at construction; serialized only when non-empty). The
  build resolves the embed into a nested `PreparedNode.embed` (with empty options) and mode-selects it
  the same way; the runner forwards `embed=<callable>` plus the node's `options` to the loop wrapper. The embed is re-selected
  against the **host pipe's actual mode** (`_select_embed(embed, host_async=…)`, defined on both
  executions), so an adapter-mode loop node gets an embed matching the mode it really runs in. On
  `ExecMode.ADAPTER` the runner forwards a synthesized host-mode wrapper:
  `adapt_embed_for_sync(embed, drain)` / `adapt_embed_for_async(embed, run_sync)` copy the wrapper's
  discovery metadata (`name`, `type`, `subtype`, `subtypes`, `pollable`, `loopable`) and set `isasync`
  to the host mode, leaving `__wrapped__` unset, so `loop_embed_sync`/`loop_embed_async`, `is_subpipe`,
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
  from execution-owned `acquire`/`aacquire` (single-flight + exit-stack teardown), resolved against the
  execution Context; a name absent from the Context raises before any sibling is acquired. Providing
  resources into the `Pipeline` surface itself is deferred.
- `iter(pipeline)` (`Pipeline.__iter__`, returning an `ItemGenerator`) and `aiter(pipeline)`
  (`Pipeline.__aiter__`, returning an `AsyncItemGenerator`) own the execution lifetime
  (`with SyncExecution() as e: yield from e.run(plan)` / the `async with AsyncExecution()` analogue), so
  early close, exhaustion, or failure unwinds upstream feeds and the exit stack.
- **Source-only pipelines stream their source** (2026-10-04). A `Pipeline` with a `source` and no
  module nodes builds no plan: `__iter__`/`__aiter__` pass `plan=None`, and
  `SyncExecution.run(None, source=…)` / `AsyncExecution.run(None, source=…)` return the source
  through the same `_resolve_source`/`_aresolve_source` boundary a seeded plan uses (awaitables and
  async iterables resolve; a mapping is one record). `_require_source` raises `InvalidPipelineError`
  when neither a plan nor a source is given, and `Pipeline()` still fails `workflow has no nodes`.
- **`first(default=MISSING)` / `afirst(default=MISSING)`** read one item and close the run before
  returning (`closing(iter(self))` / `aclosing(aiter(self))`); with no item and no `default` they raise
  `EmptyPipelineError` (`PipelineError` + `LookupError`, exported from `riko`), so a bare
  `StopIteration` never leaks into an enclosing iterator. A bare `break` out of `async for` over a
  `Pipeline` is still unsafe: the abandoned generator is finalized from another task and cancels the
  caller's task group scope (strict xfail
  `test_async_pipe_lifecycle.py::TestAsyncClose::test_bare_break_leaves_the_callers_cancel_scope_intact`);
  the scoped `Pipeline.open()` is scheduled in R4C.
- **Fluent authoring** derives definitions immutably in the definitions layer, with no
  normalize/runtime import: the canonical constructor takes `(workflow, source=…)` — it accepts a
  `Workflow` (or defaults to the empty `Workflow`) and an optional seeded item stream, raising
  `TypeError` on any other positional value — while the `Pipeline.from_module(name, conf=…)`
  classmethod seeds one `ModuleNode`; `.pipe(name,
  conf=…)`, attribute chaining (`pipeline.sort(conf=…)` — underscore and mapping names raise
  `AttributeError`), and `|` (a name, a `(name, conf)` pair, or a one-module template) each mint a
  `<name>-<occurrence>` node id (`_mint_node_id`, matching `normalize_workflow`'s scheme), append the
  node plus a `StreamEdge` from the current default output, and re-point `outputs["default"]`
  (`_build_chained_workflow`); prior nodes/edges are shared by reference. `items | Pipeline(…)` /
  `Pipeline(source=items)` bind an external iterable as `Pipeline.source` — definition-level but
  `Workflow`-external, so serializing a seeded pipeline never captures items — and `__iter__`/`__aiter__`
  pass it to `run(plan, source=…)`, which delivers it to the subgraph's single open default input
  (`_seed_target`; two open roots raise `InvalidPipelineError`) while other roots keep the
  `{"forever": True}` seed. The seed is a `SourceLike` (`Item | Feed | Awaitable[Item | Feed]`,
  `riko/types/_streams.py`) resolved once per run — `SyncExecution._resolve_source` awaits an
  awaitable through the portal and drains an async stream through it, `AsyncExecution.
  _aresolve_source` awaits and wraps, both sharing `normalize_items` (`_adapt.py`: a mapping or
  primitive is one item, any other iterable is the stream) — so `Pipeline.source`, `__ror__`
  (`is_streamlike` or awaitable, never a `Pipeline`), and the generated module's `pipe(item)` hand
  the raw value through and the helpers below `run` keep their wide `Items`/`Feed` parameters. An
  async `processor` node fed an async stream maps it lazily and in order (`_aprocess_stream` in
  `riko/modules/_decorators.py`, a bounded ordered window) instead of treating the stream object as
  one item. `build_execution_plan` also refuses, before any node runs, a source port feeding more
  than one stream edge (`Workflow.require_executable()`), the fail-closed companion of the non-`out` port guard
  until R7's port-keyed delivery; the shape stays valid canonical structure under `validate()`.
  Sparse positional inputs (`in` + `in:2`, legacy `_OTHER2`) execute as an ordered `others` list,
  `in:0`/`out:0` are grammar errors in `parse_port`, and per-module fan-in arity waits on the
  module port contracts. Callable `.map`/`.flat_map` are deliberately not shipped —
  callable-pipes owns them; a strict-xfail tripwire in `tests/public/test_pipeline_fluent.py` flips
  when they land. Tests: `tests/public/test_pipeline_fluent.py` plus seeded-run and end-to-end
  coverage in `tests/internal/test_prepare_execution.py`.

## Write architecture — `write()` / `sink()` sessions (shipped)

> **Partial.** Sync and async write sessions both ship now with the compatibility pipe runtime; R4B moves
their lifetime ownership onto the `SyncExecution` / `AsyncExecution` exit stacks and adds explicit
execution-outcome propagation (including terminate/cancellation → abort), R5C adds the executable
`WriteNode` caller, and R11 adds provider-native targets/sessions →
[execution-semantics.md](gameplans/execution-semantics.md),
[effects.md](gameplans/effects.md), [implementation-sequence.md](gameplans/implementation-sequence.md).

The fluent `write()`/`sink()` verbs ride a private write-session mechanism (no hidden `send`/`on_receive`
pub/sub). Four durable layers:

- **declarative** — `WriteOperation` (frozen `mode` + unified `keys`), `SupportsWrite` (a destination
  that *reports write capabilities*, it does not itself deliver records; the protocol lives in
  `riko/types/_targets.py`), and `Formats` (`riko/definitions/_write.py`).
- **prepared** — `PreparedWrite` (target + normalized operation + resolved `WriteCapabilities`) is the
  validated object; `WriteOperation` on its own is unvalidated intent. `WriteCapabilities` stores only
  independent facts (`modes`, `fmt`, `incremental`, `match_keyed_modes`, `idempotent_modes`);
  `appendable`/`serializes`/`keyed_modes` are **derived** properties. `build_write` +
  `validate_target_mode` + local `normalize_strs` live in `riko/definitions/_targets.py` (`normalize_strs` is a
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
- **async** — the fluent `AsyncPipe.write()`/`sink()` passthroughs were deleted with the class at
  v1-cutover step 4 (2026-10-02); `Pipeline.write(dest)` declares the `WriteNode` and its execution is
  still pending, so the session path below is reached through the `write` module today, riding the
  `_AsyncFileWriteSession` / `async_file_write_session` path (the `AsyncWriteSession` protocol mirrors the
  sync `write` / `finalize` / `abort` / `teardown` surface). No pub/sub language remains in the error text.
- **runtime-only** — `PreparedWrite`, `WriteCapabilities`, and session strategy are execution-time facts
  and never serialize into the R4A workflow IR.

The layering the compatibility runtime hosts today, and where R4B moves it:

```
now
`write` module (the `AsyncPipe` host was deleted at cutover step 4)
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
