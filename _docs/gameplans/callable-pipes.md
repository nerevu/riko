# Callable pipes gameplan

> **Provenance.** Extracted from `docs/ROADMAP.md`. This plan is authoritative for callable-node behavior; common execution/state/resource/identity contracts live in [execution-semantics.md](execution-semantics.md).

## 4. Callable pipes

Callable transforms are ordinary nodes on the single immutable `Pipeline[T]` abstraction.
The same definition runs through sync or async execution; the target API does not define
separate final `SyncPipe.map` and `AsyncPipe.map` contracts.

```python
flow = Pipeline(source=items).map(normalize)
```

### Existing decorator model

Continue to use the existing module definition/preparation machinery:

```python
@processor(...)
@operator(...)
@splitter(...)
```

Do not add a parallel `PipeTraits`, `TraitOverrides`, `@riko.pipe`, signature-injection, or
callable-context framework.

Execution/planning characteristics may extend existing module options/metadata, including:

```python
boundedness: Literal["preserve", "finite", "unbounded", "unknown"]
ordering: Literal["preserve", "destroy", "establish"]
require_bounded: bool
stable_order: bool
```

The earlier proposed:

```python
state_checkpoint: Literal["replay", "persist"]
```

is superseded by `FeedState`, `StateStore`, stateful owners, and explicit `.checkpoint()`.

Execution `ordered=True` and semantic `stable_order=True` are distinct: one controls
concurrent presentation, the other guarantees deterministic semantic ordering for identity
derivation.

### One callable API

Conceptually:

```python
flow.map(
    fn,
    *,
    version=MISSING,
    resources=(),
    identity=None,
    stable_order=None,
    execution=None,
    **kwargs,
)
```

and:

```python
flow.flat_map(
    fn,
    *,
    version=MISSING,
    resources=(),
    identity=None,
    stable_order=None,
    strict=None,
    execution=None,
    **kwargs,
)
```

Exact signatures may be narrowed during implementation. The contract is:

* declare the callable node once;
* choose sync/async mode when iterating the Pipeline;
* use common `version=` for semantic-version/fingerprint escape;
* use common `resources=` declaration/binding;
* use common `preserve` / `derive` / `combine` identity semantics for ambiguous custom
  operators.

Execution-wide settings belong to:

```python
flow.with_execution(executor="thread", concurrency=8, ordered=False)
```

A retained node-level `execution=` hint only describes adaptation safety for that callable;
it does not mutate Pipeline-wide execution settings.

### Sync and async implementations

Decorators may wrap sync or async functions, bare or configured:

```python
@processor
def pipe(item, **kwargs): ...


@processor
async def pipe(item, **kwargs): ...
```

A single async implementation need not be renamed `async_pipe`. `isasync=True` remains the
explicit escape hatch when Python cannot classify the callable reliably. Dual
implementations may still use `pipe` + `async_pipe` so both forms can coexist in one module.

Native implementation wins for the execution mode. Sync execution bridges async-only
components through the execution's shared portal; async execution adapts unknown sync work
to a worker unless explicitly inline-safe. Never create an async runtime per item.

### Feed-native parser inference

An async generator parser is inferred as Feed-native. A legacy coroutine returning a
completed iterable remains a compatibility fallback. `parser_mode=` is only an escape hatch
when inference is ambiguous. Rollout by module is owned by `feed-native-streaming.md`.

### Callable Context

Callable invocation continues through the ordinary wrapper-prepared kwargs path:

```python
result = fn(item, **pipe_kwargs)
```

The public `Context` may be supplied as the immutable environment/configuration definition:

```python
def transform(item: Item, *, context: Context, **kwargs) -> Item: ...
```

Do not turn `Context` into mutable per-item execution state. Position, item key, generation,
and observation live in the private `_FeedItem` runtime wrapper; task groups, state-store
adapters, channels, portals, and live resource handles stay on the private execution.

There is no public `ExecutionContext`, `CallableContext`, `call_kwargs`, or per-item
`context.bind(...)` execution model.

### Declared resources

Callable nodes use the common declaration shape:

```python
resources = "db"
resources = ("db", "cache")
resources = {"db": "primary_db", "cache": "redis"}
```

Accepted input is normalized immediately from:

```python
type ResourcesLike = str | Iterable[str] | Mapping[str, str]
```

to an immutable local-name -> Context-name mapping.

Resolved handles are passed through the existing module wrapper/preparation machinery in
the same way current `stream`, `objconf`, and `tuples` arguments are prepared. Only directly
declared bindings are visible to the callable/parser. Transitive resource dependencies
affect lifecycle/fingerprinting but are not implicitly exposed.

The local alias is identity-significant; the Context lookup target name is not. The resolved
effective resource definition is identity-significant. Missing bindings fail preparation
before resource opening/source consumption.

### Callable fingerprints and `version=`

Semantic fingerprints are resolved during execution preparation and fixed for that run.
Inspectable Python callables use normalized AST while ignoring formatting, comments, source
locations, docstrings, and annotations. Relevant defaults, kwdefaults, closure nonlocals,
durable referenced globals, decorators, and captured configuration participate.

`functools.partial` includes the wrapped callable and bound arguments. Bound methods and
callable instances include durable instance configuration. Stable builtins/stdlib use
qualified identity. Opaque third-party/native implementations require a resolvable package
identity/version or an explicit node version.

```python
version: NonNullHashable | MissingType = MISSING
```

`MISSING` means automatic inspection; `None` is invalid. Explicit `version=` replaces
automatic implementation inspection for callables owned by the node while stable namespace
and non-callable configuration still participate.

### Identity semantics

Built-ins infer identity behavior from known semantics/module metadata. Ambiguous custom
operators expose only:

```python
identity: Literal["preserve", "derive", "combine"]
```

* `preserve`: 1 -> 1 identity/generation preservation;
* `derive`: deterministic child identity/generation;
* `combine`: output identity/generation from all contributors.

For derive operations, semantic child identity is preferred. Positional fallback requires a
stable semantic ordering guarantee. Combine semantics may declare whether contributor order
is significant.

### Strict flat-map

With `strict=False`, normal Python iterable semantics apply. With `strict=True`, accidental
bare mappings are rejected, the result must be iterable/async iterable as required, and
emitted values must satisfy the Riko item contract.

Strictness is a node semantic option, not an execution type.

### Process execution

Process execution preserves the logical callable interface but only serializable
configuration/definition values cross the process boundary. Live runtime objects do not:

```text
open files/sockets
resolved resource handles
StateStore adapter
publish/subscription channels
task groups/portal
worker pools
```

Planning fails before workers start when required configuration cannot be safely serialized.
No process-only public Context type is introduced.

### Side effects and idempotency

Pure callables need no idempotency contract. A side-effecting callable declares the
capability needed by execution validation and accepts the centrally derived idempotency key.
The callable does not reconstruct provenance itself.

The common dimensions are:

```text
(node_id, fingerprint, item_key, generation, iteration)
```

If the destination cannot genuinely honor idempotency, retryable/resumable validation fails
unless the node explicitly opts out with `require_idempotency=False`.

### State/checkpoints

Callable nodes do not select replay/persist modes. State uses:

```python
FeedState[T]
StateKey[T]
StateRecord[T]
StateStore / AsyncStateStore
```

and an explicit boundary is:

```python
flow.checkpoint(id="after-normalize")
```

A checkpoint in a reusable callable fragment resolves to exactly one enclosing stateful
owner when the concrete Pipeline is compiled. Restore belongs to that owner.

### Planning diagnostics

Planner output should expose declared/resolved semantic metadata without a second trait
runtime. Useful fields include boundedness, ordering, stable order, sync/async availability,
adaptation policy, identity mode, side-effect/idempotency support, declared resources,
callable/resource fingerprint source, and Feed-native vs legacy parser mode.

Structural compilation may be cached; execution-sensitive callable/resource fingerprints
are recomputed at execution preparation.

### Definition of done

1. `Pipeline.map` / `Pipeline.flat_map` are mode-neutral callable APIs.
2. Existing decorators/module preparation remain the definition mechanism.
3. No `state_checkpoint="replay|persist"` option remains.
4. Public `Context` remains immutable/environmental; per-item provenance remains private.
5. Resources use the common declaration/preparation model.
6. Callable fingerprints and `version=` support durable state/idempotency identity.
7. Ambiguous custom identity uses only `preserve` / `derive` / `combine`.
8. Sync/async/process adaptation does not introduce alternate callable interfaces.
