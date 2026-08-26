# Feed-native streaming gameplan

> **Scope:** Discharges the **P7 carryover** — *bounded-memory streaming
> export* ([PHASE_CHECKLISTS.md](../PHASE_CHECKLISTS.md) § P7) — and generalizes it: drive the
> `_materialize_legacy_source` seam down to only genuinely blocking legacy operators.
>
> **Provenance.** Folded in from the untracked `_docs/streaming_eval.md` scratch analysis.
>
> **Ownership boundary.** This gameplan owns the *per-pipe Feed-native migration plan*, the
> *streaming-memory model* (eager output vs. eager storage), the streaming-`write` tap design, and
> the *sync/async streaming-parity* rules. It **consumes**, and does not redefine, these owners:
> - the `parser_mode: feed | legacy_stream` **mechanism** → [callable-pipes.md](callable-pipes.md) §4;
> - **`BatchPolicy`** (§16 batch model) → [execution-semantics.md](execution-semantics.md); this
>   gameplan uses `batch_feed`/`batch_stream` runtime primitives that eventually delegate to it;
> - the **AnyIO 4.14 floor** + `anyio.itertools` (`chain`/`islice`/`batched`/`tee`) →
>   [bado-anyio-alignment.md](bado-anyio-alignment.md);
> - **serialized codecs** (`StreamEncoder`) → [artifact-conversion.md](artifact-conversion.md);
>   whole-dataset `CONVERSION_FUNCS`/`export()` stays intact.

## 1. Reframe: "which pipes can become Feed-native?"

The right question is **not** "which sync implementation has an AnyIO equivalent?" but **"which
pipes can become Feed-native?"** Today `AsyncPipe` drains a `Feed` into a list at the explicit
`AsyncPipe._materialize_legacy_source` boundary before invoking module parsers, whose contracts take
synchronous `Stream`/`PipeTuples`. The escape hatch is the already-planned
`parser_mode: feed | legacy_stream` classification (owned by callable-pipes.md §4).

**Prerequisite:** raise the `async` extra floor to `anyio>=4.14` — `anyio.itertools` (`chain`,
`islice`, `batched`, `tee`) arrived in 4.14.0; the pin is currently `anyio>=4.0.0`. Shared with
[bado-anyio-alignment.md](bado-anyio-alignment.md) § prerequisite.

**Acceptance test** (better than "functions replaced with AnyIO"):

> After these migrations, `_materialize_legacy_source()` is reached **only** by genuinely
> blocking/eager legacy operators (`sort`, `reverse`, legacy extension modules) — never by ordinary
> composer/reducer pipes.

## 2. Per-pipe audit

Priority **A** = clear win, do first; **B** = worthwhile; **C** = inherently eager, low value.
(`udf`/`aggregate` excluded — covered by separate unpushed fixes.)

| Pipe | Priority | Feed-native approach | Effect |
|---|:---:|---|---|
| `truncate` | **A** | `anyio.itertools.islice(feed, start, stop)` | Lazy; stops upstream early — the **proof-of-concept** for `parser_mode="feed"` (port first: gives an early-termination test). |
| `union` | **A** | `anyio.itertools.chain(feed, *others)` | Fully lazy, sequential concatenation. No concurrency/ordering/state. |
| `filter` | **A** | native `async for` over the existing rule engine | Fully lazy, no materialization. **Don't** contort the rule engine into an AnyIO primitive. |
| `uniq` | **A** | `async for` + bounded `deque(maxlen=limit)` | Fully lazy, O(limit) memory (turn `for`→`async for`). |
| `tail` | **A** | `async for` into `deque(maxlen=count)` | Still EOF-before-output, but O(count) memory instead of O(source). High value — the legacy seam silently inflates it to O(source). |
| `count` | **A** | incremental async accumulator | O(1) ungrouped; O(groups) grouped. |
| `sum` | **A** | incremental async accumulator (`Decimal`) | O(1) ungrouped; O(groups) grouped. |
| `receive` | **A** → **F1** | yield directly from the AnyIO receive stream | Removes the current result list; pub/sub is already AnyIO-native, so materialization fights the abstraction. **Owned by [fanout-topology F1](fanout-topology.md#5-phase-f1--make-async-receive-truly-streaming)** (that phase's title *is* this row). |
| `send` | **A** → **F1** | publish → `yield` each item; `complete` in `finally` | Removes the current `sent` list. **Owned by F1** — same DoD, and F5 renames/deletes the `others`/`max_wait`/`complete()`/`ids` vocabulary this row assumes. `complete`-in-`finally` is already done (see below). |
| `timeout` | **A** | AnyIO cancel scopes (`move_on_after`) around iteration | **Real** cancellation of a blocked `anext()` (today's `AsyncTimeoutIterator` only notices *after* the deadline). |
| `split` | **A/B** | bounded broadcast (prototype with `tee`) | Removes the whole-source copy — see §4. |
| `forever` | **B** | `anyio.itertools.repeat` | Native async infinite source. |
| `join` | **B/C** | async product/hash join | Possible, but semantics matter more than laziness. |
| `sort` | **C** | collect Feed then sort | Inherently eager — stays legacy. |
| `reverse` | **C** | collect Feed then reverse | Inherently eager — stays legacy. |

**Three of those rows are confirmed defects, not missed optimizations** (one now fixed).
The [branch audit](correctness-audit.md#8-open-defect-register--features-branch-audit)
verified them against the tree, so each is worth repairing on the legacy path if the
Feed port does not reach it first:

* ~~`join` (**R3**)~~ — **fixed** on the legacy path. `product(stream, other)` tupled
  *both* inputs, so the **primary** stream was materialized even though `other` is the
  documented replayed side; a join over an unbounded primary emitted nothing at all. The
  keyless branch was equally affected one level down, via `meza.process.join`
  (`map(merge, product(…))`). Repaired in both branches with `others = list(…)` + a
  nested lazy loop, independent of the async product/hash-join design — `join` remains
  `B/C` for the *async* port.
* `send` (**R4**) — the `sent` list is not merely wasteful: `await async_pipe(infinite)`
  never returns, and no downstream item appears before the source is exhausted, on the
  one pipe whose purpose is lazy fan-out. **Reassigned to
  [fanout-topology F1](fanout-topology.md#5-phase-f1--make-async-receive-truly-streaming),
  not this port** — F1's DoD #1 is already "`send`/`receive` are incremental in both sync
  and async execution", and its bounded-capacity/cancellation/sender-failure requirements
  are the same contract, so porting `send` here would be redone. F1 also renames `others`→
  `targets` and `max_wait`→`timeout` and deletes `complete()`/the `ids` dict outright
  (F5), so the *vocabulary* this row assumes is itself scheduled for removal. Two adjacent
  non-laziness defects (completion skipped on publish failure; sync `for` over a `Feed`)
  were repaired on the legacy path 2026-08-24 with a `strict` xfail left as F1's guard —
  see the R4 row in [correctness-audit § 8](correctness-audit.md#8-open-defect-register--features-branch-audit).
  `truncate` remains this port's proof-of-concept.
* `timeout` (**R14**) — the cancel-scope port is the *only* thing that makes the pipe
  bound a stalled source. [execution-semantics § 7.2](execution-semantics.md#72-a-blocked-anext-outlives-the-deadline)
  owns the `on_timeout` policy it must land with.

## 3. Streaming-memory model: eager output ≠ eager storage

The central distinction:

> **Needs EOF before output ≠ needs whole input in memory.**

| Pipe | Needs EOF before output? | Needs whole source in memory? | Chunking role |
|---|:---:|:---:|---|
| `count` | yes | **no** | optional optimization |
| `sum` | yes | **no** | optional optimization |
| `tail` | yes | **no** (O(count)) | n/a |
| `write` | **no** | **no** | important |
| `split` | no | **no** | important (bounded fan-out) |

`count`/`sum`/`tail` are **blocking reducers**, not memory-eager operators. Batching them is an
execution optimization (fewer checkpoints), not a semantic change — the accumulator **spans**
batches; never "reduce each chunk and emit per chunk."

## 4. `split`: bounded fan-out, not `tee`

`anyio.itertools.tee(feed, n)` is a useful **behavioral reference** but not the production engine: a
tee must retain values when one consumer outruns another, so a stalled branch becomes an unbounded
cache. Riko's bounded-memory direction (already set by `_pool_stream`) wants bounded channels with
backpressure:

```text
                ┌→ bounded channel → branch A
source → producer├→ bounded channel → branch B
                └→ bounded channel → branch C
```

The producer does not advance until **every active branch** can accept the next chunk. Default =
backpressure on the slowest active branch, not silent memory growth. Chunking is the unit of
fan-out (`batch_size` records per send). The **sync** counterpart needs the same explicit decision:
`itertools.tee` is lazy but unbounded; strong bounded-memory semantics need bounded queues (likely
threads for truly independent concurrent branches). Define split's buffering/slow-consumer behavior
explicitly in **both** runtimes rather than defaulting to the current `list(stream)` replay.

## 5. Streaming `write`: a tap, not a terminal sink

`write` yields every item unchanged, so it is a **tap/passthrough sink**, not a terminal one:

```text
source ──→ write side effect
       └─→ downstream unchanged
```

Today it double-materializes (`items = list(stream)` then `convert([dict(i) for i in items])`), so
even a lazily-consumable converter never gets the chance. **Eagerness is an implementation property,
not an inherent requirement** — writing JSON/CSV does not require whole-stream materialization.

**Design: an incremental `StreamEncoder` separate from the file writer** (coordinates with
[artifact-conversion.md](artifact-conversion.md) codecs):

```python
class StreamEncoder(Protocol):
    def start(self) -> bytes: ...
    def encode(self, items: Iterable[Item]) -> bytes: ...
    def finish(self) -> bytes: ...
```

The write loop (identical shape sync/async — only the I/O transport differs):

```text
fp.write(encoder.start())
for/async for chunk in batched(source, chunk_size):
    fp.write(encoder.encode(chunk))   # await for async file
    yield from chunk                  # tap: pass records downstream
fp.write(encoder.finish())
```

Peak record storage becomes ≈ O(chunk size). Framing state lives in the encoder, not the loop:

| Format | Framing |
|---|---|
| JSONL | trivial — each record independent; ideal streaming target |
| JSON array | `[` once, commas across chunk/item boundaries, `]` once |
| CSV | header on first chunk only, rows after |
| GeoJSON | FeatureCollection prefix/suffix + separators |
| OFX/QIF | headers/footers/grouping — only where format semantics permit |

**Route streaming writes through a new `STREAM_ENCODERS` registry, not `CONVERSION_FUNCS`.** The
latter models `Items → complete exported representation` (keep it for `export()`); streaming needs
`Items/chunks → stateful serialization session`. Different interfaces; separating them keeps
`export()` backward-compatible and avoids twisting meza's converters into a contract they weren't
built for.

**Semantic decision (make it deliberate, document it):** streaming means downstream can consume
chunks 1–49 before a chunk-50 write fails, whereas today downstream sees zero records if writing
fails. Default to **destination-file atomicity**: write incrementally to a temp file, yield records
downstream incrementally, and on success `flush/fsync/close` + atomic-replace; on
failure/cancellation delete the temp file and do not replace. This protects the output artifact but
does **not** roll back downstream side effects — that belongs to execution/lineage semantics, not
`write`.

## 6. Shared batching primitive

Batching is a **runtime primitive**, not a per-pipe feature or an async-only optimization:

```python
async def batch_feed(source, *, max_records) -> AsyncIterator[tuple[T, ...]]: ...
def       batch_stream(source, *, max_records) -> Iterator[tuple[T, ...]]: ...
```

Initially delegate to `anyio.itertools.batched` / `itertools.batched`; grow naturally into the
already-envisioned `BatchPolicy` (owned by [execution-semantics.md](execution-semantics.md) §16 —
`max_records`/`max_bytes`/`max_delay`, first-threshold-wins). **Do not** expose a separate
`write.chunk_size` public concept — make it an internal implementation of `BatchPolicy.max_records`.
One primitive then serves `write` (serialization batch), `split` (broadcast batch), and future DB/
HTTP/AI/Arrow sinks; `sum`/`count` merely consume the batches if batching is enabled.

## 7. Sync/async streaming parity

Most of the above are **streaming/memory-management** recommendations, not async-specific ones. The
guiding rule:

> Sync and async pipes should differ primarily in **how they wait**, not in **when they materialize**
> or how much memory they use.

Factor each pipe into a **runtime-neutral state/algorithm** + a sync adapter + an async adapter
(e.g. a shared `UniqueState.accept(item, key)`, shared reducers, shared `StreamEncoder`, shared
batching). Per-pipe, document four characteristics and expect them to match unless the runtime
fundamentally prevents it:

| Characteristic | Sync | Async |
|---|---|---|
| laziness | same | same |
| output ordering | same | same |
| memory complexity | same | same |
| side-effect timing | same | same |
| waiting/cancellation | runtime-specific | runtime-specific |

This prevents drift like `sync tail = O(count)` / `async tail = O(source)`, or `sync union = lazy` /
`async union = materialized`. Sync stays the semantic baseline wherever it is already lazy and
bounded (`union` = `chain`, `truncate` = `islice`).

### 7.1 Unified stream-boundary source normalization

Parity starts at **ingest**: sync and async should classify a source into "one item" vs.
"many items" the same way, at one boundary. The invariant (already the `_iterutils.listize`
contract) is:

| Input | Normalized to |
|---|---|
| `None` | source invocation (one call producing a stream) — **not** an empty stream |
| `Mapping` | one record |
| primitive / `str` / `bytes` | one item (never iterated char/byte-wise) |
| `Iterable` (`list`/`tuple`/`range`/generator/iterator) | stream of items |
| `AsyncIterable` | async stream of items |
| `Awaitable` | `await`, then normalize the result |

**Landed (sync + async processor wrapper).** Both `processor` wrappers in
`riko/modules/_decorators.py` gate their implicit-loop auto-map on `_iterutils.is_listlike(item)`
(mirroring `listize`'s boundary) instead of the old `isinstance(item, Iterator)`. So `list`,
`tuple`, `range`, generators, and iterators all map element-by-element, while a mapping,
primitive, or `None` stays one item — sync is the semantic baseline and async matches it.

**Deferred (this gameplan).** Formalize the *async* arms (`AsyncIterable`, `Awaitable`) as a
single `_as_async_stream(source)` adapter and route `AsyncPipe`/`AsyncCollection` source ingest
through it, so the collection path and the wrapper share one boundary. This lets us delete the
bespoke source-normalization special-casing currently sitting in `AsyncPipe` and drive the
`_materialize_legacy_source` seam (§1) down to only genuinely blocking legacy operators — the
adapter yields a lazy `AsyncIterator` for the Feed/AsyncIterable case rather than pre-draining.

`send.async_parser` now carries a second such arm
(`stream if isinstance(stream, AsyncIterator) else async_iter(stream)`, added with the R4
repair — a sync `for` there crashed outright on the `AsyncIterator` that `operator.aparse`
produces). Fold it in when the adapter lands; it is a call site, not a competing contract.

Two hard constraints the adapter must preserve (both are current, load-bearing behavior):
- **`None` is a source invocation, not an empty stream.** Source pipes (`fetchdata`, …) are
  called with `item=None` to *produce* a stream; normalizing `None`→empty would never invoke
  them. `is_listlike(None)` is `False` for exactly this reason.
- **Normalize only the outermost source, never record values.** A `Mapping` is one record;
  `listize(mapping)` already yields a one-item stream. A list-valued *field* inside a record
  (e.g. `tags: [...]`) stays a list — riko interprets only the outermost argument as one-or-many.
- **Definition replay vs generator one-shot.** A `Pipeline` *definition* over a list/tuple replays
  across executions; a **generator instance** is intrinsically one-shot and is **never** secretly
  buffered to fake replay. That definition-vs-execution rule is owned by
  [release-readiness.md § 4](release-readiness.md); this section owns only the per-source
  classification above.

## 8. Implementation sequence

1. Raise the `async` extra to `anyio>=4.14`.
2. Build the Feed-native parser mechanism (`parser_mode`/equivalent + async `PipeTuples`/config
   machinery that Feed operators need) — the callable-pipes.md §4 deferred item.
3. Port **`truncate`** (`islice`) — minimal proof + early-termination test.
4. Port **`union`** (`chain`).
5. Port **`filter`, `uniq`, `tail`** with native `async for`.
6. Port **`count`, `sum`** to incremental accumulators (O(1)/O(groups)).
7. ~~Port **`send`/`receive`** to yield incrementally (stop materializing).~~ **Reassigned to
   [fanout-topology F1](fanout-topology.md#5-phase-f1--make-async-receive-truly-streaming)** —
   it needs the same seam (step 2), but the pub/sub contract, vocabulary rename, and
   subscription lifecycle around it are F1/F4/F5's, so F1 consumes step 2 rather than this
   plan owning the pipes.
8. Add shared `batch_feed`/`batch_stream`; align with the future `BatchPolicy`.
9. Introduce stateful streaming encoders (JSON/CSV first, JSONL as an easy target).
10. Convert **`write`** into a chunked passthrough sink over `STREAM_ENCODERS`; leave
    `CONVERSION_FUNCS`/`export()` intact.
11. Implement bounded **`split`** fan-out (evaluate `tee` as reference only).
12. Move **`timeout`** onto AnyIO cancel scopes (per-`anext` + total).
13. Later: GeoJSON/OFX/QIF streaming encoders only where format semantics permit; leave `sort`/
    `reverse` genuinely eager.
14. Fold the async source arms into a shared `_as_async_stream` adapter (§7.1) and route
    `AsyncPipe`/`AsyncCollection` ingest through it — can land independently, but pairs naturally
    with step 2 (it needs the lazy Feed path to avoid pre-draining) and lets step 1's
    `_materialize_legacy_source` retreat to blocking legacy operators only.

## 9. Relationship to the P-track

- **Discharges the P7 carryover** (bounded-memory streaming *export*) via §5–§6; broadens it to the
  whole composer/reducer surface.
- **Depends on** the callable-pipes.md §4 `parser_mode` mechanism (currently *Deferred*) and the
  execution-semantics.md §16 `BatchPolicy` (currently *Planned*).
- **Absorbs the deferred cleanup** from the processor `is_listlike` change (sync + async wrapper
  auto-map now shares `listize`'s boundary): §7.1 owns the remaining async-side unification
  (`_as_async_stream` + collapsing `AsyncPipe`'s bespoke source normalization into it).
- **Live status** (done/next/suite count) lives only in the
  [PHASE_CHECKLISTS.md](../PHASE_CHECKLISTS.md) tracker — do not restate it here.
