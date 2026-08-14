# Riko Callable pipes Contract Gameplan

> **Provenance.** Extracted from `docs/ROADMAP.md` so the roadmap stays a high-level overview. This gameplan is the authoritative detail for the callable-pipe execution contract — the `Opts` execution-characteristic fields, the `@processor`/`@operator`/`@splitter` decorator model, `map`/`flat_map`, strict mode, and callable context / thread / process execution (ROADMAP §4). Section references like §N point back to [RUNTIME_CONTRACT.md](../RUNTIME_CONTRACT.md) (the runtime contract); the numbered `## N.` headings are preserved so those references resolve.

## 4. Callable pipes

> **Status: Planned.** `Opts` carries none of the execution-characteristic fields; `map`/`flat_map` callable pipes and strict mode do not exist. `@processor`/`@operator`/`@splitter` exist but are not extended with these fields.

> **Deferred / not yet implemented.** Per-module Feed-native parsers (a
> `parser_mode: feed | legacy_stream` classification, review #8) are not built:
> today's module parsers consume synchronous `Items`, so a non-parallel async
> pipe buffers its upstream at the explicit `AsyncPipe._materialize_legacy_source`
> boundary. Only the bounded/parallel path streams end-to-end (see §3.2, §8).

### Pipe execution options

Pipe execution behavior is represented using the existing `Opts` typed dictionary.

Do not introduce:

* `PipeTraits`
* `TraitOverrides`
* `@riko.pipe`
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

Strictness is inherited from the pipe and may be overridden per pipe.

```python
pipe = AsyncPipe(..., strict=True)
pipe.flat_map(fn)
pipe.flat_map(other_fn, strict=False)
```

With `strict=False`:

* the result is iterated without special type checking
* a mistakenly returned mapping may be flattened into its keys
* later pipes may surface the error

With `strict=True`:

* a bare mapping result is rejected
* the result must be iterable or async iterable
* each emitted value must be a valid `Item`

### 4.3 Callable context

Callable pipes use Riko's existing `Context` primitive and existing keyword propagation model.

#### Callable invocation

A callable pipe invokes its function using the item followed by the normal pipe keyword arguments:

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
fn(item, **pipe_kwargs)
```

where `pipe_kwargs` is the ordinary resolved pipe kwargs and includes:

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
fn(item, **pipe_kwargs)
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

Callable pipes should reuse that behavior rather than introducing a new context delivery mechanism.

The same `Context` instance is propagated through chained pipes unless a narrower context is intentionally created for:

* an embedded module
* a Connect run
* a pipe
* a source
* a positioned item

#### Scoped contexts

Per-pipe or per-item execution metadata must not be written onto a single shared mutable context during concurrent execution.

When narrower execution metadata is needed, Riko derives a child `Context`:

```python
item_context = context.bind(
    pipe_id=pipe_id,
    source_id=position.source_id,
    position=position,
    schema_id=schema_id,
)
```

That child is then placed into the same ordinary kwargs mapping:

```python
item_kwargs = {
    **pipe_kwargs,
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

Riko does not inspect whether the callable declares `context`, `**kwargs`, or neither. A callable used as a Riko pipe is responsible for accepting the keyword arguments Riko supplies.

#### Process execution

Process execution preserves the same callable interface:

```python
fn(item, context=context, **kwargs)
```

Before submission, Riko validates and serializes the process-safe portions of the ordinary pipe kwargs.

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
