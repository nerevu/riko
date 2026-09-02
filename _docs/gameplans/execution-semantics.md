# Execution semantics gameplan

> **Provenance.** Extracted from `docs/ROADMAP.md` so the roadmap stays a high-level overview. This gameplan is the authoritative detail for the runtime execution-semantics contract. It reconciles the reusable `Pipeline` definition model, sync/async execution, resources, fan-out, metadata/state propagation, checkpointing, durable identity, batching, retry/error policy, timeout, merge, and memory limits. Numbered `## N.` headings are retained where other documents reference the corresponding runtime-contract sections.
>
> **Status vocabulary.** Existing/shipped behavior is identified explicitly. Everything described as the target contract is planned API/runtime behavior and must not be presented as already shipped until implementation lands.

## Canonical definition and execution model

`Pipeline[T]` is the sole reusable public pipeline definition. A pipeline is an immutable DAG; fluent chaining is shorthand for creating a new definition that shares prior structure.

```python
flow = Pipeline("fetchdata", conf={"url": url}).filter(conf=filter_conf).map(normalize)
```

Execution is deliberately separate from definition:

```python
list(flow)  # fresh private SyncExecution
aiter(flow)  # fresh private AsyncExecution
```

`iter(flow)` creates a new one-shot private `SyncExecution`; `aiter(flow)` creates a new one-shot private `AsyncExecution`. Reusing the same pipeline definition creates independent executions with independent resource, portal, state-store-adapter, and fan-out lifetimes. There is no normal public `Execution(...)` construction API.

The same `Pipeline` definition may run in either mode. Native implementations win and the runtime adapts only where the matching implementation is absent.

| Module implements | Sync execution | Async execution |
|---|---|---|
| sync + async | native sync | native async |
| sync only | native sync | sync on a worker unless explicitly inline-safe |
| async only | async on the execution portal | native async |

Legacy `SyncPipe` / `AsyncPipe` / collection classes remain migration surfaces only; they are not the target architecture.

### Definition configuration vs execution configuration

Step configuration is fixed when that step is declared. `with_config()` does not mutate the last/current step.

Execution-wide settings use a separate immutable definition operation:

```python
flow = flow.with_execution(executor="thread", concurrency=8, ordered=False)
```

There are no executing `collect()` / `first()` terminals in the target API. Normal execution remains Python iteration (`list(flow)`, `for`, `async for`). `take()` remains a transform.

Pipeline immutability does not imply source replayability. One-shot iterators, lazy generators, subscriptions, and other one-shot sources preserve their native semantics; a second execution may therefore observe an already-consumed external source unless the source itself is replayable.

## Context and resources

There is one public `Context`; there is no public `ExecutionContext`. `Context` is an immutable environment/configuration definition. Runtime handles belong to the private execution.

```python
ctx2 = ctx.with_module(...)
ctx3 = ctx2.with_resource(...)
```

Child contexts may shadow parent modules/resources; names must be unique within one scope. Built-ins remain static/global defaults, while Context-local module definitions may shadow them.

### Resource ownership

An owned resource is declared as a **(sync or async) generator / context manager** — the idiomatic Python lifecycle shape used by `contextlib`, pytest fixtures, FastAPI `yield` dependencies, `dependency-injector`, and Dagster resources: setup runs before `yield`, the handle is injected, teardown runs after (guaranteed, even on error).

```python
def db(ctx):  # owned: setup -> yield handle -> teardown
    pool = create_pool(...)
    try:
        yield pool
    finally:
        pool.close()


ctx.with_resource("db", db)
ctx.with_resource(
    "client", Resource.from_external(client)
)  # caller owns; Riko never closes
```

`Resource.from_external(...)` is a distinct type that always resolves to the supplied handle and never closes it (rather than an `external=True` flag); it is inherently eager and takes no `lazy` because the value is already supplied by the caller. `Resource(handle, cleanup=...)` remains a low-level convenience for wrapping an already-live handle with an explicit closer; the generator/CM is the ergonomic primary and subsumes `from_factory` (the generator *is* the factory-with-teardown).

A referenced owned resource is entered eagerly during execution preparation by default. An unreferenced resource is not entered. `lazy=True` validates eagerly but defers entry until first use.

Each `Resource` resolves at most once per execution. Re-executing the same `Pipeline` resolves a fresh owned handle.

Opening rules:

- independent eager resources enter in deterministic declaration order;
- resource generators may depend on other declared resources;
- dependencies are resolved dynamically with cycle detection;
- lifecycle is managed by a single `AsyncExitStack` (sync generators/CMs bridged), so if eager entry fails, all successfully entered owned resources unwind in reverse order;
- external resources are never closed by Riko.

Teardown is the generator's post-`yield`/`finally` body (or the context manager's `__exit__`/`__aexit__`); an explicit `cleanup=` applies only to the low-level `Resource(handle)` form. The common sync/async bridge adapts a sync generator/CM into the async execution mode and vice versa. Cleanup always attempts all required closes: a single cleanup error is raised directly; multiple are grouped with `ExceptionGroup`.

### Execution-bound resource view

Parsers and factories receive resolved handles through an execution-bound view:

```python
resources.db
resources["db"]
```

`Context.resources.db` continues to denote the immutable `Resource` definition, not the live handle.

Nodes declare resources using the common metadata input:

```python
resources = "db"
resources = ("db", "cache")
resources = {"db": "primary_db", "cache": "redis"}
```

The accepted public form is:

```python
type ResourcesLike = str | Iterable[str] | Mapping[str, str]
```

and is normalized immediately to an immutable local-name -> Context-name binding. The local alias is identity-significant; the Context lookup name is not. The resolved effective resource definition and its transitive dependencies are identity-significant.

Resource arguments are prepared by the existing module wrapper/preparation machinery in the same way that stream/objconf/tuples arguments are prepared today. This is not a separate signature-based dependency-injection system. Only declared direct resource bindings are visible to the parser/factory. Transitive dependencies participate in lifecycle and fingerprinting but are not automatically exposed.

Missing resource bindings fail compilation/preparation before resources are opened or source consumption begins. Initially all declared resource bindings are required.

## Feed results, metadata, and per-item provenance

The existing async stream type remains:

```python
type Feed = AsyncIterable[Item]
```

Rich parser/source results use one immutable envelope:

```python
@dataclass(frozen=True)
class FeedResult[ItemsT]:
    items: ItemsT
    metadata: Metadata
    state: FeedState | None = None
```

`SyncFeedResult` and `AsyncFeedResult` are aliases over iterable and async-iterable item containers. `Metadata` is a typed Objectify-like mapping with both attribute and mapping access.

Metadata is preserved through ordinary transforms when still truthful. Operators that invalidate or replace metadata must say so explicitly. A common result-level `metadata.generation` may seed item generations; if output items no longer share one truthful generation, result-level generation is invalidated and private per-item provenance remains authoritative.

`assign=` / `emit=` remain the common wrapper behavior over Feed-native parser output; introducing `FeedResult` does not change those semantics.

Per-item execution identity is carried privately rather than exposed as a second public result model. Conceptually:

```python
@dataclass
class _FeedItem[T]:
    value: T
    item_key: Hashable | MissingType
    generation: Hashable | MissingType
    observation: Metadata | None
```

Normal parsers and users continue to see ordinary values.

## Fan-out and pub/sub

The public vocabulary is object-first:

```python
class Publisher[T](Protocol): ...


class Subscription[T](Protocol): ...


class Channel[T](Publisher[T], Subscription[T], Protocol): ...
```

Low-level compatibility modules may remain named `send` / `receive`; the final Pipeline API uses `publish` / `subscribe`.

Local declaration:

```python
events = Pipeline.subscribe("events")
flow = flow.publish(events)
```

An external subscription is an ordinary source:

```python
flow = Pipeline(source=subscription)
```

`publish()` accepts a local subscription pipeline or an external `Publisher`. A published local subscription branch is attached to the owning execution. The user does not drain that branch to make cleanup occur; branch terminal values are discarded unless the branch has an explicit sink/tap/routing effect.

Calling `list(events)` independently creates a fresh execution; subscriptions are not replay buffers.

Multiple subscriptions may share a display name. Python object identity distinguishes them. Serialized configuration may use the concise declaration:

```json
{"name": "events"}
```

and a target name resolves all same-name declarations unless an explicit serialized id selects one.

### Subscriber scheduling and buffering

Sync subscribers execute inline by default. Execution concurrency is an explicit opt-in. Async orchestration is execution-owned; the MVP may use `asyncio.create_task()` while the final execution layer owns cancellation and teardown.

Async subscriptions default to rendezvous behavior:

```python
buffer_size = 0
overflow = "block"
```

For bounded buffering:

```python
overflow: Literal["block", "drop"] = "block"
```

`drop` drops the oldest buffered item and keeps the newest, matching the current sync behavior. Per-subscription item order is guaranteed. Ordering between independent subscriptions is unspecified.

Subscription errors use only:

```python
Literal["raise", "ignore"]
```

with `"raise"` the default. `"ignore"` is per-item continuation.

A subscriber `tap=` may be sync or async; its return value is discarded and the original item continues. This tap contract must be changed for sync and async together rather than creating mode-specific semantics.

When multiple publishers target one subscription, the subscription completes only after all attached publishers complete. Concurrent publishers preserve actual delivery order; no artificial global ordering is imposed.

### `split()`

`split()` is streaming fan-out, not whole-source `deepcopy`:

- upstream is consumed once;
- only reachable/used outputs become active branches;
- active branches receive items incrementally;
- unused outputs allocate no queue and exert no backpressure;
- per-branch buffers are bounded and default to zero-buffer/rendezvous semantics;
- split is never lossy and has no drop overflow mode.

Branch isolation is observable, but the runtime chooses the cheapest safe copy/share strategy. There is no public copy-mode knob initially.

`publish(..., isolate=True)` similarly isolates a branch by default, with `isolate=False` as the explicit escape hatch.

Shared ancestry alone never implies fan-out. Fan-out must be represented by `split()` or `publish()`.

## Identity, fingerprints, and idempotency

Durable checkpoint identity, per-item generation, idempotency, and semantic fingerprints share one canonical freezing/encoding system. They must not each invent independent serialization or hashing rules.

### Hashable identity values

The existing Riko `Hashable` type is extended rather than duplicated:

```python
type NonNullHashable = ...
type Hashable = NonNullHashable | None
```

`NonNullHashable` includes the supported scalar identity types plus recursive tuples. The canonical system distinguishes types that Python normally conflates (`bool`/`int`, `int`/`float`, `float`/`Decimal`) and handles `datetime`, `date`, `struct_time`, `PurePath`, `bytes`, UUID, enums, mappings, dataclasses, sets/frozensets, lists, and tuples according to the durable rules below.

Key canonicalization rules:

- `bool` is handled before `int`; `datetime` before `date`; enums before their scalar bases;
- finite floats use a deterministic representation, infinities use explicit tags, all NaNs share a stable tag, and `-0.0` canonicalizes with `+0.0`;
- Decimal equivalent representations normalize within the Decimal type;
- naive datetimes use `ensure_tzinfo(..., try_local_tz=False)` and therefore UTC fallback; aware datetimes normalize to UTC;
- mappings are order-independent and sort by canonical encoded key, including heterogeneous key types;
- sets/frozensets are order-independent while preserving the set/frozenset distinction;
- list and tuple remain distinct; only tuple participates in logical `Hashable` identity;
- mapping wrappers such as Objectify/DotDict canonicalize by contents, not wrapper type;
- dataclasses/enums include stable `module.qualname` type identity; local/non-import-stable definitions require explicit versioning when used durably;
- paths are lexical and preserve path flavor; no filesystem resolution occurs;
- bytes use lowercase hex; mutable bytearray/memoryview may be freezeable for fingerprints but are not logical hashable identity values;
- UUID uses lowercase 32-digit hex;
- strings preserve exact Unicode code points; no NFC/NFKC normalization is applied;
- cyclic structures are rejected for durable identity.

A shared internal `_freeze(obj) -> FrozenValue` generalizes the current `_to_hashable()` machinery. Durable consumers raise on unsupported values; process-local representation caching may instead treat a value as uncacheable.

### Canonical bytes and digest

Canonical frozen values encode to fixed UTF-8 JSON bytes. `Context(identity_encoder="auto")` may select the fastest installed Riko-supported/conformance-tested encoder, but every supported encoder must emit byte-for-byte identical canonical output. Explicitly requesting an unavailable backend fails preparation. Encoder acceleration belongs to the existing `perf` extra and the selected backend is not semantically fingerprinted.

Durable digests are domain/version separated and use one fixed algorithm for the identity-format version:

```python
hashlib.blake2b(data, digest_size=16).hexdigest()
```

The result is a 32-character lowercase hex string. Domains are fixed Riko-owned values (for example fingerprint, generation, idempotency, state-key encoding); callers do not supply arbitrary digest-domain strings. The domain/version participate in the hashed bytes but are not embedded in the returned hex text.

### Callable and resource fingerprints

Inspectable Python callables are fingerprinted from normalized AST, excluding formatting, comments, source locations, docstrings, and annotations. Defaults, kwdefaults, closure nonlocals, durably freezeable referenced globals, decorators, and relevant captured configuration participate.

`functools.partial` includes its wrapped callable and bound args/kwargs. Bound methods/callable instances include durable instance configuration. Stable builtins/stdlib callables use qualified identity; opaque third-party/native implementations may use owning distribution version when resolvable and otherwise require an explicit node version.

Callable-accepting nodes support a common:

```python
version: NonNullHashable | MissingType = MISSING
```

`MISSING` means automatic inspection. `None` is invalid. An explicit version replaces automatic callable implementation inspection for callables owned by that node while stable callable/type namespace and non-callable node configuration still participate.

Resource definitions, not live handles, are fingerprinted. `Resource.version` overrides automatic resource implementation identity only; ownership, lazy/eager lifecycle, cleanup, dependencies, and other semantic resource configuration still participate. Resolved resource dependency fingerprints propagate transitively. Opaque external resources that affect a resumable scope require an explicit resource version.

Structural compilation may be cached process-locally with a bounded internal cache, but execution-sensitive semantic fingerprints are recomputed during execution preparation. Captured/global callable configuration is sampled then and is assumed semantically stable for that execution; Riko does not continuously mutation-watch it.

### Provenance propagation

Root identity is automatically namespaced by the source node identity. A generated source node id is sufficient within one compiled definition; use explicit `id=` where identity must remain stable across structural edits that would otherwise change the generated id.

Generation propagation follows operator semantics:

- 1 -> 1: preserve;
- 1 -> N: derive deterministic child generation, preferring semantic child identity over position;
- N -> 1: derive from contributors plus relevant operator/group identity;
- N -> N: derive from the exact contributing input generations.

Positional derivation is allowed only when stable ordering is guaranteed. N-to-1 contributor generation is accumulated incrementally rather than retaining all contributor values.

Built-ins infer identity behavior from known semantics/module metadata. Ambiguous custom operators have only:

```python
identity: Literal["preserve", "derive", "combine"]
```

A custom derive operator may additionally need `stable_order=True` before positional fallback is safe. Combine semantics may declare whether contributor order is significant. Execution `ordered=True` and operator semantic `stable_order=True` are distinct concepts.

`union()` preserves each input item's provenance; it does not combine identities.

### Idempotency

Every Riko side-effecting module supports idempotency where its destination permits it; pure transforms require none. Execution derives and injects a key centrally rather than asking modules to reconstruct provenance:

```text
(node_id, fingerprint, item_key, generation, iteration)
```

Generation remains stable across retries and comes from source/upstream semantics, never a random retry UUID.

If a retryable/resumable workflow reaches a side effect whose backend cannot honor idempotency, validation fails unless that node explicitly opts out:

```python
.write(..., require_idempotency=False)
```

Riko does not add a generic distributed lease/lock abstraction to this contract.

## Stateful execution and checkpoints

State persistence uses one `StateStore` capability for recovery checkpoints and source/observation state. The existing `hash` module is not a checkpoint mechanism because Python hash values are not a durable identity contract.

### Public state values

```python
@dataclass(frozen=True)
class FeedState[T]:
    checkpoint: T | MissingType = MISSING
    observation: Metadata | None = None


@dataclass(frozen=True)
class StateRecord[T]:
    state: FeedState[T]
    version: StateVersion
    boundary_id: str | None = None


@dataclass(frozen=True)
class StateKey[T]:
    node_id: str
    fingerprint: str
    item_key: NonNullHashable | None = None
    generation: Hashable = None
```

`StateKey[T]` is a phantom generic linking the key to the payload type for static checking. The generic parameter has no runtime, serialization, equality, or fingerprint significance. `StateStore` itself is not generic because one store naturally contains heterogeneous records.

`item_key=None` denotes owner-level state and requires `generation=None`. Per-item recovery uses a non-null item key. Nested tuple identity components may still contain `None`.

`StateVersion = NonNullHashable` is an opaque CAS token. Riko never increments or interprets it.

### Store protocols and CAS

Sync and async stores use the same operation names; awaitability differs:

```python
class StateStore(Protocol):
    def load[T](self, key: StateKey[T]) -> StateRecord[T] | None: ...

    def save[T](
        self,
        key: StateKey[T],
        state: FeedState[T],
        *,
        boundary_id: str | None = None,
        expected_version: StateVersion | MissingType = MISSING,
    ) -> StateVersion: ...

    def delete[T](
        self,
        key: StateKey[T],
        *,
        expected_version: StateVersion,
    ) -> None: ...


class AsyncStateStore(Protocol):
    async def load[T](self, key: StateKey[T]) -> StateRecord[T] | None: ...
    async def save[T](...) -> StateVersion: ...
    async def delete[T](...) -> None: ...


type StateStoreLike = StateStore | AsyncStateStore
```

Stores must be uniformly sync or uniformly async; mixed method modes fail preparation. Each execution resolves one private mode-specific state-store adapter and applies sync/async bridging once when the adapter is prepared.

All mutations are CAS-protected:

```python
save(..., expected_version=MISSING)  # create only
save(..., expected_version=version)  # update exact revision
delete(..., expected_version=version)  # delete exact revision
```

There is no unconditional mutation escape hatch. A missing actual record conflicts with an expected existing version; an existing record conflicts with expected `MISSING`. `CheckpointConflictError` carries the key, expected version, and actual version (`MISSING` when absent). CAS conflicts propagate; Riko does not automatically reload and rerun the operation.

Backends must prevent stale resurrection across delete/recreate races with their own monotonic revision/tombstone mechanism as needed. That mechanism is not exposed in the public checkpoint model.

`save()` returns only the resulting `StateVersion`; `delete()` returns `None`.

### Store capabilities and state serialization

Physical serialization of `StateKey` and `FeedState[T]` is backend-owned. Riko does not impose one universal state codec. To help users choose stores without creating an exhaustive Python type registry, configured store instances expose coarse capabilities plus concrete preflight validation.

```python
StateSerializationId = NewType("StateSerializationId", str)


class StateSerialization(StrEnum):
    PYTHON = "python"
    JSON = "json"
    PICKLE = "pickle"
    MSGPACK = "msgpack"
    CBOR = "cbor"
    PROTOBUF = "protobuf"
    AVRO = "avro"


type StateSerializationLike = str | StateSerialization | StateSerializationId


class StateStoreCapabilitiesRaw(TypedDict):
    serialization: StateSerializationLike
    persistent: bool
    portable: bool


@dataclass(frozen=True, slots=True)
class StateStoreCapabilities:
    serialization: StateSerializationId
    persistent: bool
    portable: bool


type StateStoreCapabilitiesLike = StateStoreCapabilities | StateStoreCapabilitiesRaw
```

Known formats use Riko's canonical identifiers. Third-party formats use `<provider>:<name>`, for example `acme:state-v2`. `"memory"` is not a serialization format; an in-memory Python-object store reports `serialization="python"`.

Capabilities describe the configured store **instance**, not merely what its backend class could support. For example, SQLite `:memory:` may report `persistent=False` while a file-backed instance reports `persistent=True`; JSON and pickle instances of the same backend may differ in portability.

`persistent=True` means the configured store is intended to make saved state available to a later independent Riko execution after the current process ends. It does not claim a particular fsync, replication, HA, or disaster-recovery guarantee. `portable=True` means the configured representation is intended to be independently interpretable rather than tied to this Python/backend implementation; a concrete state must still validate.

Stores expose:

```python
store.capabilities
store.validate_state(state)
```

with:

```python
def validate_state[T](self, state: FeedState[T]) -> None: ...
```

Validation returns `None` on success and raises `StateSerializationError` on failure. The exception should identify useful location/reason information when the backend can provide it. There is no exhaustive public `supported_types` list.

Preflight is a convenience only. `save()` performs authoritative validation itself. Serialization must succeed before any mutation occurs; a `StateSerializationError` leaves the existing record unchanged. A CAS failure likewise leaves the record unchanged.

### `checkpoint()`

A generic checkpoint is a side-effecting identity/durability boundary that persists the current logical value and then passes that value through unchanged:

```python
flow = flow.checkpoint(id="normalized")
```

Conceptually the payload is:

```python
FeedState(checkpoint=current_value, observation=current_observation)
```

Checkpointing commits state; it does not independently decide how to restore. Restore belongs to an enclosing resumable/stateful owner such as `loop`, polling, or a stateful source.

A reachable checkpoint requires a configured `state_store` before source consumption begins. `Context(state_store=Resource.from_factory(...))` is a first-class Context capability, not a magic ordinary resource binding.

A checkpoint may exist in a reusable/unbound pipeline fragment, but compilation of a concrete graph requires every reachable checkpoint to resolve to exactly one enclosing resumable owner. Nested scopes bind to the nearest enclosing owner. The compiled graph records that owner explicitly.

One `(stateful owner, item_key, generation)` has one active recovery frontier. Multiple independently advancing checkpointed branches are invalid unless they reconverge into one explicit logical recovery state. Plain `union()` is a stream merge and does not perform that collapse.

`boundary_id` records the compiled checkpoint node id. An explicit `.checkpoint(id=...)` stabilizes this boundary identity across edits when required. `boundary_id` is not part of `StateKey`; advancing to a later boundary CAS-updates the same active recovery record.

Restore resumes **after** the successfully crossed boundary with the stored logical value. Recovery records are not history. Each stateful scope owns and cleans up its active recovery checkpoint when that resumable scope completes successfully; nested owners clean up independently.

A stateful semantic fingerprint covers the full resumable scope owned by the stateful node: embedded logic, checkpoint placement, termination policy, relevant callable versions, and the statically declared reachable resource dependency graph. Unrelated downstream graph structure is excluded. A fingerprint mismatch is treated as no compatible recovery checkpoint; execution starts fresh under the new fingerprint and old persisted data may remain available for inspection/migration.

The configured state-store implementation itself is infrastructure and is excluded from the semantic fingerprint. The canonical identity format/version matters; the selected performance encoder implementation does not.

### Item/generation key configuration

Stateful owners use three-way key semantics:

```python
item_key = MISSING  # infer
item_key = None  # explicit owner-level/no per-item identity
item_key = "id"  # or callable

generation_key = (
    MISSING  # infer; fail when stable generation is required but unavailable
)
generation_key = None  # item_key itself uniquely identifies the logical occurrence
generation_key = "version"  # or callable
```

Python APIs may accept callables directly. Serialized forms use symbolic Context references rather than serialized arbitrary Python callables.

`StateKey` performs canonical identity validation once when constructed; state-store operations do not repeat the same logical validation. Invalid identity uses Riko-specific exceptions rooted at `IdentityError` (for example `InvalidIdentityError`, `StateKeyError`, `IdentityEncodingError`, `CyclicIdentityError`).

`StateKey` equality compares cached canonical identity, not Python's raw numeric equality. Its `__hash__()` is only process-local and may use Python hashing over the canonical value; durable digests are a separate concern. `StateRecord` is immutable but is not required to be canonically hashable.

## Loop/resumable iteration

Agents reuse `Pipeline`; there is no separate `AgentGraph`. Agent runtime protocols reuse `Publisher`, `Subscription`, and `StateStore`.

The existing `loop` construct gains iterative state semantics while the Pipeline DAG itself remains acyclic. In iterative mode:

- each iteration's single embedded result becomes the next state;
- zero or multiple embedded results raise `LoopStateError`;
- existing non-iterative loop behavior may continue to permit zero/many results;
- `until(state, iteration)` receives the latest state and a zero-based iteration index;
- `until` is checked before the first iteration (while semantics) and remains sync-only initially;
- `max_iterations: int | None = None`;
- `max_iterations` without an explicit `until` means fixed-count iteration;
- if an explicit `until` remains false when `max_iterations` is exhausted, raise `LoopIterationError`;
- the default termination behavior preserves today's one-run loop semantics.

Loop checkpointing is explicit rather than automatic. A checkpoint crossed after a successful iteration commits before the next iteration begins. Resume persists both application state and the iteration counter so `max_iterations` remains a total bound across restarts. `LoopState[T](value, iteration)` is the checkpoint payload shape used for this purpose.

An explicit loop `id=` stabilizes the stateful owner's logical identity when structural edits would otherwise change its generated node id.

---

## 5. Execution characteristics

> **Current gap:** the present `Opts` surface does not yet contain the complete planned execution metadata below. These declarations describe semantic planning characteristics; they do not replace the concrete execution settings configured with `with_execution()`.

### 5.1 Boundedness

```python
boundedness: Literal["preserve", "finite", "unbounded", "unknown"]
```

Examples:

| pipe | characteristic |
|---|---|
| `map` | `preserve` |
| `filter` | `preserve` |
| `truncate` | `finite` |
| total timeout | `finite` |
| polling source | `unbounded` |
| arbitrary `flat_map` | `unknown` |
| finite-expansion `flat_map` | `preserve` |

Blocking operators may declare `require_bounded=True`; `unbounded` and `unknown` inputs are rejected when a finite input is required.

### 5.2 Ordering

```python
ordering: Literal["preserve", "destroy", "establish"]
```

| pipe | ordering |
|---|---|
| sequential map | preserve |
| ordered concurrent map | preserve |
| unordered concurrent map | destroy |
| merge | destroy |
| sort | establish |

Sort details come from the existing normalized `SortConfRule` rather than a duplicate metadata model. For multiple rules, the first configured rule is primary, so stable sorts are applied in reverse configuration order.

Semantic `stable_order` metadata used for deterministic identity derivation is distinct from execution `ordered=True`.

### 5.3 Side effects

Side-effect metadata must be strong enough for execution to determine whether a node requires idempotency support and whether retries/resume are safe. Pure nodes require no idempotency contract; side-effecting nodes declare their capability and accept the execution-derived idempotency key.

### 5.4 Determinism

Determinism metadata influences replay/retry safety, semantic identity, caching, and planner diagnostics. It must not be inferred from arbitrary source inspection heuristics.

---

## 6. Async execution and backpressure

> **Shipped:** see [IMPLEMENTED.md §6](../IMPLEMENTED.md#6-async-execution-and-backpressure-shipped) for current bounded-concurrency primitives. **Target:** the reusable `Pipeline` execution layer owns the sync/async adaptation and lifecycle described here.

### 6.1 Bounded concurrency

Bound concurrency rather than spawning work proportional to source size. Backpressure is structural: bounded queues/reorder buffers pause producers instead of silently dropping or relaxing ordering.

### 6.2 Ordering

```python
ordered = True
```

preserves input order for operators whose semantics permit it.

```python
ordered = False
```

emits completion order.

The current `async_map()` documentation/implementation discrepancy must be corrected; public documentation and behavior must agree.

### 6.3 Reorder buffer

Ordered concurrent execution uses a bounded reorder buffer. When the buffer fills, producers/workers pause until missing earlier positions permit progress. Ordering is never silently relaxed.

### 6.4 Cancellation

The final execution owns cancellation and teardown. On cancellation it stops accepting new work, cancels queued work where supported, allows unavoidable running threads to finish, and deterministically tears down execution-owned resources/channels/portal state.

A future explicit cancellation policy may distinguish draining from cancelling pending work, but cancellation correctness must not depend on users draining published subscription branches.

### 6.5 Cleanup

When downstream execution stops early, active feeds are closed with `aclose()` when available. This applies to truncation, timeout, failure, cancellation, and consumer abandonment.

Execution resource cleanup follows the resource rules above. If both execution and cleanup fail, cleanup is still attempted comprehensively; multiple independent failures use `ExceptionGroup`.

### Execution-mode adaptation (`Pipeline` sync <-> async)

A single `SyncExecution` owns one lazily-created AnyIO `BlockingPortal` if async-only components are encountered. It is reused for async steps, async sources, async resources, and async pub/sub for that execution. Never create one portal per item. The portal closes on exhaustion, explicit close, or exception. Independent executions get independent portals.

If the async extra is absent and sync execution requires an async-only component, raise a Riko-level installation/capability error rather than leaking a deep AnyIO/Asyncer import failure.

Unknown synchronous extension code under async execution is treated as potentially blocking. Riko does not inspect names, bytecode, imports, or timing to guess whether a function blocks.

| execution policy | behavior |
|---|---|
| `auto` | native async inline; unknown sync under async -> worker |
| `inline` | explicitly safe on event-loop thread |
| `thread` | worker thread |
| `process` | existing process machinery; no new contract implied here |

Built-in pure transforms may be marked inline because Riko owns/tests them. A future planner may combine consecutive compatible sync-only steps into a worker "sync island" as an internal optimization; this must not change the public API or cross operator/resource/side-effect boundaries unsafely.

---

## 7. Timeout

> **Shipped:** see [IMPLEMENTED.md §7](../IMPLEMENTED.md#7-timeout-shipped) for the current total-timeout primitive. **Remaining:** complete idle/item semantics and ensure a blocked `anext()` itself is bounded.

```python
timeout(seconds, mode="total" | "idle" | "item", on_timeout="stop" | "error")
```

Default:

```python
on_timeout = "stop"
```

Definitions:

- `total`: maximum lifetime of the timeout pipe;
- `idle`: maximum interval between emitted items;
- `item`: maximum wait for the next upstream item.

`on_timeout="stop"` is normal completion. `on_timeout="error"` enters the configured error policy.

### 7.1 Async receive timeout

The current sync and async compatibility `receive` implementations do not have equivalent timeout behavior: sync polling honors `max_wait`, while the async path can block indefinitely. Feed-native async receive must bound the wait itself and map expiry to the common timeout policy rather than inventing separate receive-only semantics.

### 7.2 A blocked `anext()` must not outlive the deadline

Checking a deadline only before/after `await anext(...)` does not bound a stalled source. The async implementation must put the awaited next-item operation inside the cancellation/deadline scope using the remaining timeout and map expiration to the same `on_timeout` contract.

---

## 8. Union and merge

> **Shipped:** see [IMPLEMENTED.md §8](../IMPLEMENTED.md#8-union-shipped) for sequential `union` and the current internal async merge primitive. **Remaining:** user-facing concurrent merge policy.

### 8.1 Union

`union()` is a stream concatenation/merge operation that preserves each input item's provenance. It does not combine logical identities merely because streams reconverge. Consequently, plain `union()` is not sufficient to collapse independently advancing checkpoint frontiers into one recovery state.

### 8.2 Merge

A future async-native concurrent merge may expose bounded source queues and explicit scheduling/error policy, for example:

```python
merge(
    feeds,
    scheduling="fair" | "ready",
    on_source_error="fail" | "continue",
    buffer_budget=128,
    per_source_limit=32,
)
```

The top-level input collection is fixed at plan time. Per-source buffers remain bounded. `fair` rotates among ready sources; `ready` emits the next available source result. Failure-continuation semantics must preserve independent source provenance/state domains.

---

## 11. Retry policy

> **Current gap:** no general retry policy in code.

```python
@dataclass(frozen=True)
class RetryPolicy:
    max_retries: int = 0
    backoff: Literal["none", "constant", "exponential"] = "exponential"
    retry_on: tuple[type[BaseException], ...] = ()
```

Default `max_retries=0`; there are no hidden automatic retries.

```text
operation fails
-> configured retries
-> retries exhausted
-> final error/disposition policy
```

Rules:

- provenance/generation does not advance during retry;
- ordered execution holds the affected position;
- an execution-derived idempotency key is reused across retries;
- only one layer owns retrying a given operation;
- a side effect in a retryable/resumable scope must genuinely support idempotency unless the node explicitly opts out;
- `CheckpointConflictError` is **not** automatically reloaded/rerun by the state-store adapter; CAS conflicts propagate to the caller/runtime policy.

Codec/identity/configuration errors are not transient merely because retry exists. Backend transport errors may be eligible according to an explicit retry policy.

---

## 12. Errors and dispositions

> **Current gap:** current code has limited `on_error`/`error_key` behavior; the richer sink/disposition contract remains planned.

### 12.1 Error policies

```python
error_policy: Literal["fail", "skip", "dead_letter"]
```

`skip` requires explicit data-loss authorization. `dead_letter` advances only after the durable error sink acknowledges the failed item. A failure that is not successfully disposed must not advance resumable state past that item.

### 12.2 Error sink

A future error sink writes a structured `ItemFailure` and returns/awaits acknowledgement. Sink implementation must participate in the same side-effect/idempotency rules as other durable writes.

### 12.3 Drop policy

Intentional filtering is distinct from failure. The planned drop policy may distinguish silent completion, external disposition, and treating attempted drop as error. The default preserves current filter behavior: a deliberately filtered item is considered successfully disposed without public output.

### 12.4 Disposition sink

External disposition must be acknowledged before the item is treated as advanced when configured as part of the durability contract.

### 12.5 Internal counters

Execution may maintain aggregate emitted/dropped/dead-lettered/failed/retried counts without requiring a per-item public event stream for the normal path.

---

## 13. Filter semantics

> **Shipped:** see [IMPLEMENTED.md §13](../IMPLEMENTED.md#13-filter-semantics-shipped) for `permit` / `combine` / `stop`.

A filtered-out item under the default completion-style drop policy is intentionally disposed and may allow recovery state to advance. With `filter(stop=True)`, the first rejected item is intentionally dropped, upstream consumption stops, and normal completion remains distinct from a processing failure.

---

## 15. Stateful operators

The old proposed `state_checkpoint="replay" | "persist"` switch is superseded by the generic `StateStore` / `FeedState` / `.checkpoint()` model above.

Stateful operators declare their resumable scope and identity semantics. Checkpoint placement is explicit. Restore belongs to the stateful owner. Persisted source observations/final state and recovery checkpoints share the same store abstraction but retain their own owner semantics; a successful recovery scope removes its active recovery frontier rather than publishing a synthetic "completed" checkpoint record.

For finite `FeedResult.items`, final `FeedResult.state` becomes committable only after item consumption completes successfully. A downstream failure before successful completion must not commit a final source state. Infinite feeds require explicit incremental checkpoint boundaries rather than waiting for final completion.

---

## 16. Batch model

The earlier public `Batch` / `BatchPipe` / `BatchPolicy` proposal is superseded. Riko keeps one `Pipeline[T]`; batch mode changes the values flowing through it rather than introducing a parallel pipeline hierarchy.

```python
Pipeline(source=source, batch=False)

Pipeline(source=source, batch=True, batch_size=3)
```

`batch_size` is invalid unless `batch=True`.

Batches are ordinary pipeline values. Therefore:

```python
flow.map(func)
```

always passes the current logical value to `func`: an individual item in item mode or the current batch in batch mode. There is no separate `BatchPipe.map()` contract.

### 16.1 Backend negotiation

Batch representation/backend is negotiated graph- and capability-aware. Preference order is:

1. native safe/zero-copy representation when available;
2. Arrow;
3. Polars;
4. Pandas;
5. Python list fallback.

An explicit `batch_backend=` forces a supported backend; requesting an unavailable backend raises rather than silently falling back to another representation.

Batching must remain streaming/bounded. It may not require materializing an unbounded source. Stateful boundaries, source completion, and operator semantics determine when buffered values must be made visible/committed; implementation details may use internal batching helpers without exposing a second public pipeline type.

---

## 22. Memory limits

Initial execution limits are item-count based and enforced rather than advisory. Relevant bounded structures include merge queues, ordered-concurrency reorder buffers, subscription/split buffers, and batch builders.

Byte-aware accounting may be added for merge/reorder buffers, pending provenance, error/disposition channels, and batches without requiring a universal deep-Python-object size estimator in the initial implementation.

---

## Appendix A. Async primitive reference

This appendix describes implementation building blocks, not additional public API. AnyIO/Asyncer remain private implementation dependencies and are never surfaced through `riko` / `riko.ext` contracts.

### Sync and async iteration

| primitive | Riko role |
|---|---|
| `Iterator` / generator | sync execution stream |
| `AsyncIterable` / async generator | `Feed`, async execution stream |
| `for` / `async for` | pull-based operator consumption |

A Feed/stream's finiteness is independent of its iteration mechanism.

### Pub/sub implementation

The compatibility sync backend may continue to use generator coroutines + bounded/deque buffering internally. The current async backend may continue to use AnyIO memory object streams, including zero-buffer rendezvous behavior. Those mechanisms are implementation details behind the public `Publisher` / `Subscription` / `Channel` protocols.

Final lifecycle is execution-owned:

- one execution owns its active channels/subscriber tasks;
- bounded channels provide backpressure;
- subscriber branches do not require user drains for cleanup;
- cancellation/normal completion close all execution-owned channel ends;
- multiple independent pipeline executions never share implicit pub/sub lifecycle state.

Structured concurrency (`TaskGroup` or equivalent execution-owned task management) is appropriate where branch lifetime must be tied to execution. An MVP may use `asyncio.create_task()` for subscriber concurrency, provided the owning execution still tracks, joins/cancels, and cleans up those tasks deterministically.

### Producer/consumer bridges

Sync execution uses one persistent portal when bridging async-only components. Async execution runs unknown sync extension work on workers unless explicitly inline-safe. The runtime must never spin up an async runtime per item.

### Non-goals

- Do not expose AnyIO/Asyncer types publicly.
- Do not force the cheap native sync path through an async engine.
- Do not infer blocking behavior from arbitrary source inspection.
- Do not use unbounded queues to mask backpressure.
- Do not treat shared DAG ancestry as implicit fan-out.
