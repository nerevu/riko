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
- [Canonical value encoder (R2A, shipped)](#canonical-value-encoder-r2a-shipped)
- [Workflow v2 serialization — `serialize_workflow` / `parse_workflow` (R4A.5, shipped)](#workflow-v2-serialization--serialize_workflow--parse_workflow-r4a5-shipped)
- [25. Conversion — export converters (shipped)](#25-conversion--export-converters-shipped)
- [Private execution runtime — `SyncExecution` / `AsyncExecution` (R4B, partial)](#private-execution-runtime--syncexecution--asyncexecution-r4b-partial)
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

**Typing boundary.** Parser outputs are generic over `ItemOrValue`. Processor and operator
wrappers remain `Stream` / `AsyncStream` at the public boundary; splitters are the structural
exception and return cascades. Broader `StreamOrValueStream`-style types remain internal
implementation scaffolding rather than public pipe output contracts.

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
`PipelineResolver` + injectable `ModuleStore`/`DirectoryStore` (`riko/runtime/_pipelines.py`; core ships
no locations), and the `PipeResolver` façade (`riko/runtime/_resolver.py`) doing one symmetric dispatch.
`riko/runtime/collections.py` resolves through the façade; `riko.runtime._compile.resolve_module`
delegates to it. Generated pipelines expose a stable `pipe`/`async_pipe` entry, so a sub-pipeline resolves exactly
like a built-in. External packages add modules with **no core edit** (`examples/riko-example-ext/`).
The module registry and a private target registry (`riko/runtime/_target_registry.py`, built-in
`FileTarget`, entry points under `riko.targets`) share a generic `Registry[T]` base
(`riko/runtime/_registry.py`) — one three-tier runtime → entry-point → built-in lifetime, each keyed by a
per-domain `_key` hook (module `resolved_name`, target `backend`). The target registry stores target
classes keyed by `backend` and resolves a `Backends` to its target class. The target vocabulary (base
`Target` + `SupportsRead`/`SupportsWrite`/`SupportsActions`, `WriteCapabilities`, `FileTarget`,
`TargetRegistry`, `register_target`) is on the extension surface (`riko.ext`); the `Backends` enum is on
the stable `riko` surface alongside `Formats`.
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
`parse_port` grammar helper, and the authoring TypedDicts); the immutable model lives in
`riko/definitions/_workflow.py` — the closed node union
`ModuleNode`/`ReadNode`/`WriteNode`/`CacheNode`/`ActionNode`/`SubscribeNode`, the edge families
`StreamEdge`/`PublishEdge`, the `WorkflowSpec` envelope, and the public generic `Pipeline[T]`.

The node/edge model, `Endpoint`, and `WorkflowSpec` are all `attrs @define(frozen, slots)` classes.
The six node families share a public **`Node`** base (`id`/`name`/`resources`/`label` + a `family`
`ClassVar` discriminant) and **self-normalize through `field(converter=…)`**: each field resolves its
enum (`Backends`/`Formats`/`WriteMode` via `resolve_enum`), normalizes resource bindings, or freezes
its `conf`/`policy`/`params` mapping — so constructing a node *is* canonicalizing it, and no separate
builder is required. `ReadNode`/`WriteNode`/`ActionNode` carry declarative
`backend`/`fmt`/`mode`/`keys`/`dest`/`params` intent only (no live resource or write session).
`WorkflowSpec`'s converters freeze the `nodes`/`outputs`/`inputs` mappings (`FreezeMapping`) and
normalize `edges`/`resources`; it also owns its own structural checks (see R4A.3). Field introspection
uses `riko.types._collections.field_names` (attrs-or-dataclass field names *including* `ClassVar`
discriminants like `family`, which `attrs.fields`/`dataclasses.fields` both drop), never
`dataclasses.*`; derive variants with `attrs.evolve`. `Pipeline` is STABLE (`riko`) and stays a
dataclass; the node/edge/`WorkflowSpec`/`Endpoint` model is EXTENSION (`riko.ext`). Tests:
`tests/public/test_workflow.py` plus module doctests. Forward order and the clean-break deletion
ledger: [implementation-sequence.md](gameplans/implementation-sequence.md) R4A.

## Workflow v2 normalization — `normalize_workflow` (R4A.2, shipped)

The single authoring-sugar normalization boundary: a flexible Workflow v2 authoring mapping in,
one strict canonical `WorkflowSpec` out, so no other subsystem reinterprets shorthand. Lives in
`riko/runtime/_normalize.py` (the runtime home the clean-break placement note assigns, superseding
the original `riko/workflow/normalize.py` sketch); exported EXTENSION as `riko.ext.normalize_workflow`.

It is the **structural, contract-free** pass — no `ModuleRegistry`/`TargetRegistry` lookup. It
assigns node ids, dispatches each authoring mapping to its node family, maps legacy ports to the
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

The input is typed `WorkflowSpecLike` (`riko.types`) — the `*Like` union of the precise
`WorkflowAuthoring` `TypedDict` (with `NodeAuthoring`/`EdgeAuthoring`/`EndpointAuthoring`) and a loose
`Mapping[str, object]`, so a literal gets editor key-completion while any dict still passes. The
authoring TypedDicts are the one hand-written parallel to the canonical dataclasses; a drift guard
(`tests/internal/test_workflow_authoring.py`) derives the expected key set from each node/edge/
endpoint's `fields()` and fails if authoring omits a field (modulo the `type`/`family`/`format`
aliases), so a new node field cannot silently drop out of the authoring surface. Tests:
`tests/public/test_normalize.py` plus module doctests.

## Workflow v2 validation — `WorkflowSpec.validate()` (R4A.3, shipped)

Strict structural validation is a **method on the model**, not a standalone function: `WorkflowSpec`
owns `validate()` (raises `InvalidPipelineError` on the first violation) and an `isvalid` property
(the boolean wrapper), backed by the `ports()`/`endpoints`/`declared_resources` helpers on the same
class. The earlier standalone `riko/runtime/_validate.py` / `riko.ext.validate_workflow` was removed
in the refactor that moved validation onto the spec — there is no separate validation module or
export. It answers "is this a valid graph?", not "can this run here?" — a structurally valid node
whose runtime capability has not landed still passes (E3.10).

Checks, all determinable from the spec alone: unsupported workflow version; empty node set;
node-id disagreeing with its map key; edge and output endpoints referencing a missing node; more
than one `StreamEdge` into one target port; publish/subscribe edge-family coherence (a `PublishEdge`
targets a `SubscribeNode`, a `StreamEdge` does not); node resource references resolving to declared
top-level `resources`; and a non-empty graph exposing at least one output (closing
`normalize_workflow`'s deferred ambiguous-leaf case). The contract-aware E3.9 rules — undeclared
ports, fan-in arity, registered module/action/target schema validation — are **deferred** because
the module and target contracts declare no ports or configuration schemas yet; they land with that
metadata. Tests: `tests/public/test_validate.py` (builds `WorkflowSpec` graphs directly and asserts
`spec.validate()`/`isvalid`) plus module doctests.

## Workflow v2 serialization — `serialize_workflow` / `parse_workflow` (R4A.5, shipped)

Deterministic byte-stable canonical serialization of a `WorkflowSpec` and its
round-tripping parser. Lives in `riko/runtime/_serialize.py`; exported EXTENSION as
`riko.ext.serialize_workflow` / `riko.ext.parse_workflow`.

`serialize_workflow(spec)` is a thin `json.dumps(spec, cls=WorkflowEncoder, sort_keys=True,
separators=(",", ":"), ensure_ascii=False)` — with `sort_keys` ordering map keys at every level, the
same spec always yields identical bytes for golden-fixture comparison; edge order follows the spec
while the semantic wiring lives in the endpoints, not the array order. `WorkflowEncoder` (a
`json.JSONEncoder`) renders **every** structural and value type: it emits the `WorkflowSpec` envelope
and each `Node`/`Edge` via **reflection** — `_serialize_dataclass` walks a frozen node/edge's
`fields()` and `_serialize_attrs` uses `attrs.asdict(recurse=False)` for the attrs `WorkflowSpec`,
both dropping empties (`_has_value`) while keeping required keys — and it coerces the remaining
structural leaves (`Mapping`/`mappingproxy`→dict, `tuple`→list, `Enum`→`.value`). Because node
serialization is field-reflection rather than a per-family branch, a new node field (e.g.
`WriteNode.dest`) serializes automatically with no serializer edit. Canonical
`conf`/`policy`/`params`/`inputs` values are JSON-native by construction: `normalize_workflow`
deep-freezes them through `freeze_value` (`riko/types/_collections.py`), which rejects `Decimal`,
`date`, `set`, `bytes`, non-finite floats, and non-string keys, and turns lists into tuples. The
encoder therefore needs no Python-only value branches and `serialize_workflow` uses `allow_nan=False`.
`parse_workflow(data)` reconstructs the spec by reusing `normalize_workflow` on the loaded JSON (the
canonical form is valid strict authoring), so `parse_workflow(serialize_workflow(spec)) == spec` holds
by value equality and serialization is idempotent. A migrated v1 document serializes with no v1-only structure: no
`_INPUT`/`_OUTPUT`/`wires`/`src`/`tgt` tokens and no `type:"output"` node — the terminal `_OUTPUT`
pseudo-node lives only in top-level `outputs`. Tests: `tests/public/test_serialize.py` (golden bytes,
per-topology round-trip/idempotency, order-independence, JSON-native nested round-trip by equality,
non-JSON-native value rejection, migrate-emits-no-v1) plus module doctests.

The **CLI v1→v2 cutover** (`convert-dag`/`compile-pipe` emitting v2, plus deletion of the v1
`PipeDef`/`wires` compiler consumption and the v1 fixture trees) is **not** part of this
slice: the E3.10 CLI-emission acceptance bullet is superseded by the R4A clean-break policy,
which completes that cutover at R4B (the first phase v2 executes). `migrate_v1_to_v2` remains
the one-shot offline conversion path.

## Workflow v1→v2 migration — `migrate_v1_to_v2` (R4A.4, shipped)

A one-shot offline conversion of a released Workflow v1 `PipeDef` (`modules` plus `src`/`tgt`
`wires`) into one strict canonical `WorkflowSpec`. Lives in `riko/runtime/_migrate.py` (the runtime
home the clean-break placement note assigns, superseding the original `riko/workflow/migrate.py`
sketch); exported EXTENSION as `riko.ext.migrate_v1_to_v2`. It is **not** a live loader — v1 is not a
maintained runtime ingress, so it `logger.warning`s that a v1 document was migrated, then emits v2
only.

It reuses `normalize_workflow` for the shared structural pass (port grammar, node families, id
handling, lone-leaf outputs) so only the v1-specific translation lives here: each module's `type`
becomes the node `name`; a v1 `write` module becomes a `WriteNode` (`backend=file`, `fmt` from
`conf.fmt`, mode defaulting to `replace`) rather than executing the legacy Python module; `src`/`tgt`
wire endpoints become canonical `source`/`target` with `_INPUT`/`_OUTPUT`/`_OTHER<n>` ports mapped;
and the terminal `_OUTPUT` pseudo-node plus its wire are consumed into top-level `outputs.default`
and dropped from the graph (no `type:"output"` node survives). Non-structural v1 module fields
(`emit`/`assign`/`field`/`count`/`embed`) fold into the node's `conf` so migration is lossless, with
registered `conf` keys winning on collision; fully-uppercase v1 `conf` keys (e.g. `URL`) are
lowercased through the compiler's `_lower_keys` so they keep v1's canonical casing. Orphan modules
are **retained** as nodes rather than silently erased — arity/reachability is validation's call.
Malformed structure raises `InvalidPipelineError`; an empty node set is left to
`WorkflowSpec.validate()` (the `migrate → normalize → validate` flow of E3.1).

Shared plumbing is reused, not reinvented: the legacy `_INPUT`/`_OUTPUT`/`_OTHER`/`output` tokens are
`riko/base/_config` constants (`INPUT_PORT`/`OUTPUT_PORT`/`OTHER_PORT`/`OUTPUT_MODULE`) also consumed
by `_compile`/`_normalize`; the module and edge splits use `partition` from `riko/base/_iterutils`
(now shared with `_compile`). Tests: `tests/public/test_migrate.py` plus module doctests.

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
`None` per item and `func=len` yields an `int`. Those scalar/value results are deliberately
representable by the parser contract:

```python
type OperatorParserOutput[T: ItemOrValue] = T | Iterator[T] | Stream
```

That does **not** widen the public wrapper/pipe boundary: processor and operator wrapper outputs
remain item-stream typed. Broader value-stream shapes used to represent `emit=True` behavior
remain internal implementation scaffolding and are not yet propagated into the public `Pipe`
output contract. Chaining (`subscribe("x", func=…).sort()`) still yields `{'content': None}`;
the typing change represents the existing transformation rather than changing it. Final F5 fanout
work changes **both** modes together to `on_receive=` semantics, where the callback return is
discarded and the received item continues.

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

## Private execution runtime — `SyncExecution` / `AsyncExecution` (R4B, partial)

> **Partial.** The private execution package, its lifetime primitives, and execution-local resource
> acquisition ship now. Not yet wired: `iter(flow)`/`aiter(flow)`, source normalization, native-wins
> resolution, `with_execution(...)`, `EventSink`, the P10 migration out of `collections.py`, and the
> `SyncPipe`/`AsyncPipe`/v1-compiler clean-break cutover.

`riko/runtime/_execution/` (the `execution` layer) hosts the one-shot executions a pipeline run
creates. Each owns three sibling lifetime primitives — a task group, an exit stack, and a sync/async
bridge — rather than deriving one from another.

- **`SyncExecution`** runs synchronously behind an `ExitStack`; async-only components run through a
  lazily started `BlockingPortal`. Shutdown stops the portal (joining its tasks) before the exit
  stack unwinds.
- **`AsyncExecution`** runs behind an `AsyncExitStack` with an eagerly entered root task group as the
  outermost cancel scope; blocking sync components run on a worker thread. Shutdown cancels owned
  tasks on failure, joins the group, then unwinds the stack behind a cancellation shield within an
  optional teardown budget.
- Shutdown order is explicit (stop spawning → cancel → join → shielded unwind → group failures as an
  `ExceptionGroup`), not generic exit-stack LIFO.

**Resource acquisition.** `acquire` / `aacquire` resolve a `Resource` at most once (single-flight,
keyed by resource identity); a repeat returns the first value or replays the first failure.
`build_resource_plan(resource)` (in `_execution/_plan.py`) is the one boundary that turns a
declaration into a `_ResourcePlan` carrying a `_ResourceStrategy` (`EXTERNAL` / `OWNED` /
`VALUE_FACTORY` / `LIFECYCLE`); the runtime consumes the plan and never re-inspects the original
generator/context-manager/instance shape. Teardown rides the exit stack: owned → `close`/`aclose`
callback, value-factory → cleanup callback, lifecycle → `enter_context` / `enter_async_context`.
Explicit `cleanup` is authoritative; async factory results are awaited once (portal on sync,
`maybe_deferred` on async). Async-native lifecycle/cleanup under sync execution raises
`InvalidPipelineError` — a permanent boundary (the portal closes before the stack).

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
cancellation. Deferred until `iter(flow)` wiring: true lazy-open-on-first-use and early-consumer
abandonment during iteration.

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
