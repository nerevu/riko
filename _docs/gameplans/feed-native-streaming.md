# Feed-native streaming gameplan

> **Scope:** discharge the P7 bounded-memory streaming carryover by driving the legacy
> materialization seam down to genuinely eager operators only.
>
> **Ownership boundary:** this plan owns per-module Feed-native migration, streaming-memory
> behavior, streaming `write`, and sync/async streaming parity. It consumes:
>
> * Feed-native parser inference / `parser_mode` escape hatch -> `callable-pipes.md`;
> * Pipeline batch semantics/backend negotiation -> `execution-semantics.md`;
> * public fan-out/subscription semantics -> `fanout-topology.md`;
> * canonical Workflow v2 structure/ordering -> `implementation-sequence.md` + `extensibility.md`;
> * AnyIO helper/version audit -> `bado-anyio-alignment.md`;
> * serialized streaming codecs -> `artifact-conversion.md`.

## 1. Reframe: which parsers can be Feed-native?

The useful question is not whether a sync implementation has an AnyIO equivalent. It is
whether a parser can consume/produce incrementally without a whole-source compatibility
materialization.

Async-generator parsers are inferred Feed-native. Legacy coroutines returning completed
iterables remain a compatibility fallback. `parser_mode=` exists only when inference is
ambiguous.

Acceptance target:

> the legacy materialization seam is reached only by genuinely eager legacy operators or
> extensions, not ordinary streaming composers/reducers.

Feed-native migration is **incremental across the forward implementation sequence**. It does not
wait wholesale for R10. Once the runtime capability a module needs is stable, that module may migrate:

```text
R5A  ordinary transforms/reducers using the final _FeedItem envelope
R5C  streaming WriteNode/effect path + removal of legacy Python write module
R7   publish/subscribe runtime + removal of send/receive modules + bounded split
R8   batch representation optimization
R10  remaining legacy-seam cleanup and parity proof
```

## 2. Per-module migration audit

| Pipe | Priority | Feed-native approach | Natural owner |
|---|:---:|---|---|
| `truncate` | A | async islice-equivalent; lazy, stops upstream early | R5A+ |
| `union` | A | async chain-equivalent; preserves input provenance | R5A+ |
| `filter` | A | native `async for` over rule engine | R5A+ |
| `uniq` | A | `async for` + bounded deque | R5A+ |
| `tail` | A | `async for` + `deque(maxlen=count)` | R5A+ |
| `count` | A | incremental accumulator | R5A+ |
| `sum` | A | incremental accumulator | R5A+ |
| `timeout` | A | cancellation/deadline around awaited next item | R5A+ / execution |
| legacy `receive` | A | reuse incremental receive mechanics inside final Subscription runtime, then remove module | R7 |
| legacy `send` | A | reuse publish-then-pass mechanics inside final PublishEdge runtime, then remove module | R7 |
| `split` | A/B | execution-owned bounded branch channels | R7 |
| legacy `write` | A/B | reuse bounded writer mechanics behind `WriteNode`, then remove module | R5C |
| `forever` | B | native async repeat/source | R10 if not earlier |
| `join` | B/C | incremental/hash strategy where semantics permit | R10 if not earlier |
| `sort` | C | collect then sort | intentionally eager |
| `reverse` | C | collect then reverse | intentionally eager |

The target is semantic sync/async parity, not replacing every helper with AnyIO.

## 3. Eager output is not eager storage

An operator may need EOF before it can emit without needing the entire source in memory:

| Pipe | Needs EOF before output? | Needs whole input in memory? |
|---|:---:|:---:|
| `count` | yes | no |
| `sum` | yes | no |
| `tail` | yes | no, O(count) |
| `write` | no | no |
| `split` | no | no |

Reducers keep one logical accumulator across any internal batches. Never change semantics to
"reduce each chunk and emit each chunk" merely because batch execution is enabled.

## 4. `split()` uses bounded execution-owned fan-out

An unbounded tee cache is not the production contract. The target is explicit execution-owned
branch channels with bounded buffering/backpressure:

```text
                 -> bounded branch A
source -> producer -> bounded branch B
                 -> bounded branch C
```

Only reachable/used outputs become active. Unused outputs allocate no queue and exert no
backpressure. Active branches are lossless. Default buffer size is zero/rendezvous; bounded
non-zero buffers may be supported but split never has a lossy/drop overflow mode.

Canonical Workflow v2 still represents split as an ordinary multi-output `ModuleNode` with
`out`, `out:1`, `out:2`, ... ports. Runtime queues are execution state, not serialized graph objects.

The runtime provides observable branch isolation and chooses the cheapest safe copy/share
strategy. There is no public copy-mode override initially.

This section implements semantics owned by `fanout-topology.md` / `execution-semantics.md`; it does
not define a second split contract.

## 5. Streaming `write` is a passthrough effect

`write` emits each logical value unchanged after performing its side effect; it is not a
whole-stream terminal by definition. In the target graph it is a `WriteNode`, not a public module and
not a desugared subscription callback.

Incremental codec interfaces remain useful:

```python
class StreamEncoder(Protocol):
    def start(self) -> bytes: ...
    def encode(self, items: Iterable[Item]) -> bytes: ...
    def finish(self) -> bytes: ...
```

`STREAM_ENCODERS` is separate from whole-dataset conversion functions because the interfaces
and framing state differ.

A writer may use bounded internal chunks while preserving Pipeline semantics. Destination
file atomicity can use temp-write + flush/fsync/close + atomic replace where appropriate.
Failure removes the temp artifact and does not publish it as successful.

Successful write completion is reported out-of-band through the common `EventSink` as `WriteResult`;
ordinary records continue downstream unchanged. Incremental downstream delivery cannot roll back
later downstream side effects if a subsequent write fails, so retry/resume correctness relies on the
common side-effect/idempotency and checkpoint/disposition rules from `execution-semantics.md`.

There is no separate public `sink()` terminal in the target API. The unreleased sink-specific
surface is removed outright; useful writer/codec mechanics are reused only behind `WriteNode`.
Reconciliation/destructive write modes are write semantics of the Target/operation contract;
terminality comes from graph position.

## 6. Internal batching uses the single Pipeline batch contract

The earlier separate `BatchPolicy(max_records/max_bytes/max_delay)` target is superseded.
There is one public batch model:

```python
Pipeline(source=source, batch=True, batch_size=1000)
```

`batch_size` is invalid without `batch=True`.

Batch representation follows the execution-semantics capability/cost model, **not** a global
Arrow/Polars/Pandas ranking:

```text
candidates = upstream representations ∩ representations the node accepts

1. keep the current representation when accepted
2. prefer a zero-copy/interchange-backed candidate
3. otherwise use the cheapest supported conversion
4. Python objects are the universal fallback
```

Equal-cost ties use a documented deterministic order; that order is a tiebreak, not a statement that
one dataframe library is globally preferred. A forced unavailable/incompatible `batch_backend=`
raises.

Implementation helpers such as:

```python
async def batch_feed(source, *, batch_size) -> AsyncIterator[tuple[T, ...]]: ...
def batch_stream(source, *, batch_size) -> Iterator[tuple[T, ...]]: ...
```

may exist privately for streaming writers/fan-out/adapters, but they do not define another
public batching API. A batch is an ordinary logical value in Pipeline batch mode; `.map(fn)`
therefore receives that batch.

## 7. Sync/async streaming parity

Sync and async implementations should differ primarily in how they wait/cancel, not in when
they materialize or their asymptotic memory behavior.

| Characteristic | Sync | Async |
|---|---|---|
| laziness | same | same |
| logical ordering | same | same |
| memory complexity | same | same |
| side-effect timing | same | same |
| waiting/cancellation | runtime-specific | runtime-specific |

Share runtime-neutral algorithm/state where practical (unique-state, reducers, encoders,
identity derivation), with sync and async adapters around waiting/I/O.

### 7.1 Stream-boundary source normalization

Classify one-item vs many-item sources consistently:

| Input | Normalized as |
|---|---|
| `None` | source invocation / one produced source, not automatically empty |
| mapping | one record |
| primitive / `str` / `bytes` | one item |
| iterable | stream of items |
| async iterable | async stream |
| awaitable | await, then normalize result |

The same Pipeline definition can execute sync or async. One-shot/lazy sources retain their
native replayability semantics; Pipeline immutability does not recreate consumed sources.

## 8. FeedResult and state propagation

Feed-native sources/parsers may return:

```python
FeedResult(items=..., metadata=..., state=...)
```

Ordinary transforms propagate state/metadata while truthful. Final finite `FeedResult.state`
is only committable after successful completion of `items`; infinite feeds require explicit
incremental checkpoint boundaries.

Per-item provenance remains private in `_FeedItem` and is not surfaced as a second parser
API. Fanout transports that envelope so crossing a split/publish boundary does not accidentally
invent new item identity.

## 9. Pub/sub migration boundary

The existing `send`/`receive` parsers may be made incremental as transitional implementation work,
but R7 consumes those mechanics into the final object-first API and removes the Python modules:

```python
events = Pipeline.subscribe("events", func=archive)
flow = flow.publish(events)
```

Canonical Workflow v2 represents that relationship as a `PublishEdge` targeting a `SubscribeNode`.
Attached local subscription branches are execution-owned; users do not drain them for cleanup.
Async buffering/backpressure, branch error handling, isolation, multiple publishers, completion, and
receive-time `func` semantics remain owned by the fan-out/execution contracts.

`func` is intentionally retained: it executes when an item is received/materialized by the
subscription, which is different from ordinary downstream UDF evaluation timing. Its return value is
discarded and the original item remains the logical stream value.

Pre-R7 streaming fixes must not harden the old DONE/PENDING lifecycle or create a compatibility API.
Once R7 lands, no legacy send/receive runtime/module survives behind the object-first surface.

## 10. Side effects, identity, cache, and checkpoints

Streaming ports must not invent replay/checkpoint semantics.

- item identity/generation follows canonical `_FeedItem` propagation rules;
- explicit `Pipeline.cache()` owns replay semantics; ordinary streaming helpers do not cache results;
- side-effecting `write` uses the centrally derived idempotency key where the destination supports it;
- generic persistence uses `FeedState` / `StateStore` / `.checkpoint()`;
- CAS conflicts propagate rather than causing automatic reload/rerun;
- a streaming port cannot advance committed state beyond a failed required handoff.

## 11. Implementation order

This local order is subordinate to `implementation-sequence.md`; it records module migration order,
not a second runtime roadmap:

```text
S0  source normalization + Feed-native inference tests
S1  truncate/filter/union/uniq after R5A
S2  tail/count/sum bounded reducers after R5A
S3  timeout cancellation around blocked next-item
S4  transitional send/receive streaming mechanics folded into R7 publish/subscribe runtime
S5  bounded split implementation under R7
S6  StreamEncoder + streaming WriteNode under R5C
S7  remaining eligible modules / legacy seam minimization
S8  Pipeline batch representation optimization under R8
```

R10 is the final S7-style cleanup/proof, not the first time S1–S6 are attempted.

## 12. Definition of done

1. Ordinary Feed-native transforms do not hit whole-source materialization.
2. Inherently EOF-blocking reducers remain bounded-memory where possible.
3. Sync/async laziness/order/memory/side-effect timing match semantically.
4. `split()` uses bounded execution-owned branches, not unbounded tee or whole-source copy.
5. `WriteNode` streams through bounded memory, passes records through, emits `WriteResult` through the
   common EventSink, participates in common side-effect/idempotency semantics, and the legacy Python
   `write` module is absent.
6. Public batching is only `Pipeline(batch=True, batch_size=...)`; no `BatchPolicy` or `BatchPipe`
   target remains and no global dataframe-backend ranking is documented.
7. FeedResult metadata/state and private per-item provenance survive streaming ports correctly.
8. Legacy `send`/`receive` modules are absent after R7; public pub/sub uses `publish`/`subscribe`, and
   subscriber `func=` retains receive/materialization-time semantics distinct from downstream UDFs.
9. Feed-native migration lands with its owning runtime capability; R10 leaves only intentionally
   eager materialization points and legacy-seam cleanup.
