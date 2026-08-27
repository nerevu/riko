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

## 2. Per-module migration audit

| Pipe | Priority | Feed-native approach | Memory/output effect |
|---|:---:|---|---|
| `truncate` | A | async islice-equivalent | lazy, stops upstream early |
| `union` | A | async chain-equivalent | lazy sequential concatenation; preserves each input provenance |
| `filter` | A | native `async for` over rule engine | lazy |
| `uniq` | A | `async for` + bounded deque | O(limit) |
| `tail` | A | `async for` + `deque(maxlen=count)` | EOF-before-output, O(count) |
| `count` | A | incremental accumulator | O(1) or O(groups) |
| `sum` | A | incremental accumulator | O(1) or O(groups) |
| compatibility `receive` | A / fanout owner | yield directly from subscription/feed | incremental; public target is `subscribe` |
| compatibility `send` | A / fanout owner | publish then pass item through | incremental; public target is `publish` |
| `timeout` | A | cancellation/deadline around awaited next item | bounds stalled `anext()` |
| `split` | A/B | execution-owned bounded branch channels | bounded lossless fan-out |
| `forever` | B | native async repeat/source | unbounded source |
| `join` | B/C | incremental/hash strategy where semantics permit | preserve exact contributor provenance |
| `sort` | C | collect then sort | inherently eager |
| `reverse` | C | collect then reverse | inherently eager |

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

The runtime provides observable branch isolation and chooses the cheapest safe copy/share
strategy. There is no public copy-mode override initially.

This section implements the semantics owned by `fanout-topology.md` /
`execution-semantics.md`; it does not define a second split contract.

## 5. Streaming `write` is a tap/passthrough side effect

`write` emits each logical value unchanged after performing its side effect; it is not a
whole-stream terminal by definition.

Incremental codec interface remains useful:

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

Incremental downstream delivery cannot roll back downstream side effects if a later write
fails. Retry/resume correctness therefore relies on the common side-effect/idempotency and
checkpoint/disposition rules from `execution-semantics.md`.

## 6. Internal batching uses the single Pipeline batch contract

The earlier separate `BatchPolicy(max_records/max_bytes/max_delay)` target is superseded.
There is one public batch model:

```python
Pipeline(source=source, batch=True, batch_size=1000)
```

`batch_size` is invalid without `batch=True`. Batch representation is negotiated using the
core order:

```text
native safe/zero-copy -> Arrow -> Polars -> Pandas -> Python list
```

A forced unavailable `batch_backend=` raises.

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
FeedResult(
    items=...,
    metadata=...,
    state=...,
)
```

Ordinary transforms propagate state/metadata while truthful. Final finite `FeedResult.state`
is only committable after successful completion of `items`; infinite feeds require explicit
incremental checkpoint boundaries.

Per-item provenance remains private in `_FeedItem` and is not surfaced as a second parser
API.

## 9. Pub/sub migration boundary

Compatibility `send`/`receive` parsers should become incremental, but the final Python API is
object-first:

```python
events = Pipeline.subscribe("events")
flow = flow.publish(events)
```

Attached local subscription branches are execution-owned; users do not drain them for
cleanup. Async buffering/backpressure, branch error handling, isolation, multiple publishers,
and completion semantics remain owned by the fan-out/execution contracts.

## 10. Side effects, identity, and checkpoints

Streaming ports must not invent their own replay/checkpoint semantics.

* item identity/generation follows the canonical `_FeedItem` propagation rules;
* side-effecting `write` uses the centrally derived idempotency key where the destination
  supports it;
* generic persistence uses `FeedState` / `StateStore` / `.checkpoint()`;
* CAS conflicts propagate rather than causing an automatic reload/rerun;
* a streaming port cannot advance committed state beyond a failed required handoff.

## 11. Implementation order

```text
S0  source normalization + Feed-native inference tests
S1  truncate/filter/union/uniq
S2  tail/count/sum bounded reducers
S3  timeout cancellation around blocked next-item
S4  fan-out compatibility parser streaming under fanout owner
S5  bounded split implementation under fanout contract
S6  StreamEncoder + streaming write
S7  remaining eligible modules / legacy seam minimization
S8  Pipeline batch representation optimization
```

## 12. Definition of done

1. Ordinary Feed-native transforms do not hit whole-source materialization.
2. Inherently EOF-blocking reducers remain bounded-memory where possible.
3. Sync/async laziness/order/memory/side-effect timing match semantically.
4. `split()` uses bounded execution-owned branches, not unbounded tee or whole-source copy.
5. `write` streams through bounded memory and participates in common side-effect/idempotency
   semantics.
6. Public batching is only `Pipeline(batch=True, batch_size=...)`; no `BatchPolicy` or
   `BatchPipe` target remains.
7. FeedResult metadata/state and private per-item provenance survive streaming ports correctly.
8. Compatibility `send`/`receive` may remain implementation names, but public docs use
   `publish`/`subscribe`.
