# Riko Fan-out, Routing, and Fan-in Gameplan

## 1. Mission

Make branching topology a first-class, inspectable part of Riko without replacing the
existing iterator-oriented pipeline model or turning Riko into a distributed streaming
runtime.

Riko already has important pieces of this model:

* `split` for eager duplication of a finite stream;
* `send` / `receive` for named pub/sub-style fan-out;
* `union` for sequential fan-in by concatenation;
* `join` for SQL-like fan-in by record relationship;
* async channels and bounded execution primitives that can support stronger streaming
  semantics.

The goal is therefore **not** to invent fan-out from scratch. The goal is to make the
existing pieces compose predictably, expose missing routing semantics, and define
backpressure, lifecycle, and topology contracts explicitly.

This plan is informed by useful patterns from Streamz, Bytewax, and Bonobo while keeping
Riko's existing strengths: configured reusable pipes, ordinary Python records, sync and
async APIs, named channels, and workflow definitions that can be represented as data.

## 2. Existing semantics to preserve

### 2.1 `union` is sequential fan-in

`union` concatenates the primary stream and each stream in `others` in sequence. It is not
an interleaving merge and it does not synchronize records.

```text
A: a1 a2
B: b1 b2

union(A, B)
→ a1 a2 b1 b2
```

Do not change `union` into a concurrent merge. The execution-semantics gameplan already
reserves `merge` for an async-native concurrent fan-in operator with explicit scheduling,
buffering, and source-error behavior.

### 2.2 `join` is relational fan-in

`join` combines records from two sources, optionally using `join_key` and
`other_join_key`. It remains distinct from `union`, `merge`, and positional pairing.

```text
left.id == right.user_id
→ merged record
```

Do not overload `join` with temporal-stream or positional-zip semantics.

### 2.3 `send` is transparent broadcast

`send` remains a pass-through operator on the primary stream while publishing copies to
named receivers.

```text
                         ┌── receiver: archive
source → send(archive) ──┤
                         └── primary stream continues
```

The sync implementation's lazy generator-coroutine behavior is a compatibility contract.
The async implementation should converge on equivalent streaming behavior rather than
materializing the receiver before returning it.

### 2.4 `split` remains eager

`split` has useful finite-stream semantics and should not silently become a pub/sub
operator. Documentation must continue to distinguish eager duplication from lazy channel
fan-out.

## 3. Architectural model

Riko should describe topology using four separate concepts:

```text
broadcast
    one item → every selected branch

route
    one item → one selected branch

union / merge
    multiple streams → one stream

join
    related records from multiple streams → combined records
```

These concepts must remain separate because they have different ordering, memory,
backpressure, and error semantics.

## 4. Phase F0 — document the current topology contract

Before adding new APIs, update module and cookbook documentation with a single topology
matrix:

| Primitive | Direction | Duplication | Correlation | Materialization |
| --- | --- | --- | --- | --- |
| `split` | 1 → N | broadcast | none | eager |
| `send` / `receive` | 1 → N | broadcast | named channel | lazy sync; async to be fixed |
| `union` | N → 1 | none | none | lazy sequential |
| `merge` | N → 1 | none | none | planned async concurrent |
| `join` | 2 → 1 | none | key / record relation | operator-specific |

Also document that the terse DAG format cannot fully represent secondary-stream fan-in
where `_OTHER{n}` wiring is required; the full pipe definition remains authoritative for
those topologies.

## 5. Phase F1 — make async `receive` truly streaming

> **Release-gate consumer:** the pre-1.0 "minimum pub/sub contract" (eager sync subscriptions, no
> `PENDING` records, lossless-by-default buffers, execution-scoped hubs, sync/async observable
> parity, subscription handles) is collected in [release-readiness.md](release-readiness.md) § 2 and
> maps directly onto F1/F4/F5 here — this plan remains the owner of the phase mechanics.

The async receiver must yield items as they arrive from the AnyIO receive channel rather
than collecting all items until channel closure.

Target behavior:

```python
receiver = AsyncPipe("receive", conf={"name": "alerts"})

async for item in receiver:
    await deliver(item)
```

Requirements:

* first item is visible to the receiver before sender completion;
* bounded channel capacity propagates backpressure;
* cancellation closes the active receive stream cleanly;
* sender failure closes or fails receivers according to the declared policy;
* receiver abandonment does not leak a send task or channel;
* sync and async public semantics are documented together.

This is the highest-priority topology change because the named fan-out abstraction is only
fully useful for unbounded feeds when async receivers remain incremental.

The **sender** side is in the same phase, and its guard test is already written:
`test_async_send_does_not_buffer_its_source` in `tests/public/test_pipe_implementations.py`
is a `strict` xfail, so landing F1 flips it and the marker must come off (audit **R4**,
`send.async_parser` buffers into `sent` and returns `iter(sent)` after `complete`). Two
adjacent defects there are already repaired — completion now fires from a `finally`, and a
`Feed` source no longer raises — so what remains for F1 is purely the incremental yield.

Note the seam this needs, since it is not local to the pipes: yielding lazily makes the
parser an **async generator**, and the operator wrapper's post-parser path is sync-only *and
fails silently* — an async gen is not awaitable (`_decorators.py:1050`), so
`isinstance(stream, Iterator)` is `False`, `get_assignment` (`_assignment.py:110`) takes its
`else` branch, and the generator **object** is emitted as a single item. `OperatorWrapperOutput`
(`types/general.py:80`) is sync-only and `_assignment.py` has no async path at all. F1 therefore
consumes step 2 of
[feed-native-streaming § 8](feed-native-streaming.md#8-implementation-sequence) (the Feed-native
parser mechanism) rather than reimplementing it.

## 6. Phase F2 — first-class conditional routing

Add a routing primitive rather than forcing users to encode routing indirectly as
`send` + `filter` combinations.

The first API should be binary and configuration-friendly:

```python
matched, unmatched = flow.branch(
    conf={
        "rule": {
            "field": "score",
            "op": "greater",
            "value": 500,
        }
    }
)
```

Semantics:

* each input item appears in exactly one output;
* existing Riko filter/rule configuration is reused;
* no implicit copying occurs;
* order is preserved independently within each branch;
* both outputs remain lazy;
* abandoning one branch must have explicit backpressure behavior rather than causing an
  undocumented deadlock.

A callable predicate may be supported through callable-pipe integration, but serialized
workflow definitions must be able to express the rule-based form without arbitrary code.

Do not call this operation `split`; `split` already means eager duplication.

## 7. Phase F3 — named routing and partitioning

After binary branch semantics are stable, add N-way routing for workloads where each item
belongs to one destination rather than every destination.

Possible configuration:

```python
flow.route(
    field="customer_id",
    branches=["a", "b", "c"],
    strategy="hash",
)
```

Initial strategies:

```text
hash
round_robin
rule
```

Requirements:

* deterministic hash routing has a documented hash/fingerprint contract;
* branch count changes are explicitly documented as repartitioning events;
* round-robin ordering is defined;
* routing never pretends to provide durable distributed ownership;
* all routing remains local to one Riko execution.

Do not implement distributed partition assignment, leases, or worker ownership. Bytewax's
routing semantics are useful inspiration; its distributed runtime is not in scope.

## 8. Phase F4 — explicit buffering and slow-subscriber policy

Named fan-out must define what happens when subscribers consume at different speeds.

Target configuration:

```python
flow.send(
    others={
        "archive": {
            "buffer": 1024,
            "overflow": "block",
        },
        "metrics": {
            "buffer": 32,
            "overflow": "drop_oldest",
        },
    }
)
```

Policies:

```text
block
    sender waits until capacity is available

drop_newest
    discard the new item for that subscriber

drop_oldest
    discard the oldest queued item for that subscriber

error
    fail that subscriber or the whole send operation according to error policy
```

Default must remain lossless:

```text
overflow = block
```

A lossy policy must never be enabled implicitly.

Metrics should expose at least:

* queue depth;
* items published;
* items dropped;
* blocked-send time;
* subscriber detach/failure count.

## 9. Phase F5 — subscriber lifecycle

The sync receiver priming requirement exposed generator-coroutine mechanics. F5 replaces it
with a public subscription helper that owns priming and cleanup. It splits into **F5a** (the
API shape — landed), **F5c** (`func` becomes a tap — next, independently landable), and
**F5b** (subscription handles + teardown ownership — lands with P11).

### 9.1 Phase F5a — subscription API (landed)

`SyncPipe` gained a subscribe/publish pair that hides the hub entirely:

```python
receiver = SyncPipe.subscribe("alerts", func=alerted.append)
sender = SyncPipe.publish(items, "alerts")
flow = SyncPipe(source=items).publish("everything").filter(conf=...).publish("breaking")
```

* `subscribe` registers eagerly through `receive.register_receiver`, so no `next(receiver)`
  priming call is needed and the coroutine is never visible to the caller.
* `publish` is one descriptor serving both bindings — `SyncPipe.publish(source, *names)` on
  the class, `flow.publish(*names)` on an instance (chaining to `send`).
* **The drain is non-blocking.** `subscribe` pins `conf["max_wait"] = 0`, which makes
  `parser`'s PENDING branch structurally unreachable: `total_waited` starts at 0, so an
  empty queue always takes the stop branch before the sleep-and-yield branch. A subscribed
  receiver therefore never emits a state marker and needs no filtering by the caller or by
  the collection layer.

The rationale for non-blocking is load-bearing and should not be reverted casually: the sync
backend has **no producer/consumer concurrency**. `send` pushes only when the sender pipe is
advanced, on the same thread. While a caller is blocked inside `next(receiver)` waiting for
an item, nobody can push one — a blocking idle wait is unsatisfiable by construction and can
only burn `max_wait` before giving up. PENDING existed to let a pull iterator over a push
queue avoid blocking; removing the block removes the need for the marker.

This generalizes rather than conflicting with the 1.0 contract: **blocking is a property of
the `Subscription`, not of `receive`** ([release-readiness.md § 2](release-readiness.md)). The
in-process sync hub is a buffer you drain and never has to wait; a broker-backed subscription
blocks or polls because it has a real remote producer. Non-blocking is the default everywhere
and `blocking=True` + timeout is opt-in, owned by the `Subscription` implementations that need
it (P11) — so `max_wait=0` here is the permanent in-process default, not a stopgap.

**Transitional, not an end state:** the raw `SyncPipe("receive", conf=...)` path still emits
PENDING for interleaved manual stepping (`next(sender)` / `next(receiver)`), which is what
`tests/public/test_collections.py` exercises. Two receive behaviors coexist **until F1/F4
remove `PENDING` from the data stream entirely** — do not harden anything against the raw
path's marker contract on the assumption that it is permanent.

### 9.2 Phase F5b — subscription handles and teardown ownership (remaining)

> **Scope:** F5b lands **with** the `Publisher`/`Subscription` rewrite (P11 +
> [release-readiness.md § 2](release-readiness.md)), not before it. The defect below is real
> today, but every mechanism it would have to build on — the `DONE` sentinel, `send`'s `ids`
> dict, `_notify_subscribers()` — is itself slated for deletion in favour of explicit
> generation/token ownership. Fixing teardown on top of those would mean writing code twice
> and freezing a contract that is about to change. A `strict` xfail in
> `tests/public/test_collections.py` marks the defect in the meantime — don't "fix" it locally.

`receive.parser` calls `close(name)` on **both** exits — sender DONE *and* idle expiry — and
`SyncPubSubHub.close` pops the receiver, queue, and id together. So an empty drain destroys
the *subscription*, not just the *pass*. Three consequences:

1. A subscribed receiver cannot be drained twice; the second pass finds no channel.
2. The id the sender bound to is destroyed, so a later `notify_complete` fails its identity
   check and DONE never lands.
3. `register_receiver`'s idempotence guard (`if name not in sync_hub.receivers`) then
   silently creates a *different* channel under the same name.

Target: **an empty drain ends the pass; only channel closure or an explicit release ends the
subscription.**

* Drop `close(name)` from the idle-expiry branch — `break` alone.
* Completion is `subscription.close()` / channel closure, per § 2's "subscription handles, not
  hidden id bookkeeping". The sender closing its side terminates its receivers through
  generation/token ownership rather than by pushing a `DONE` record into the queue, so the
  drain loop no longer has a sentinel branch at all.
* Teardown follows the handle's lifetime, anchored to the pipe that opened it.
  `SyncPipe.close()`/`terminate()` already run `_settle_iter`, which throws `GeneratorExit`
  into the drain generator; a `try`/`finally` there releases the subscription.

Repeated drains then compose into live streaming with neither markers nor blocking — a second
`SyncPipe.subscribe(name)` resolves the same live subscription — while the pipe itself stays
one-shot ([PHASE_CHECKLISTS.md](../PHASE_CHECKLISTS.md) guiding decision 2). The subscription
is long-lived; a drain is one pass over it.

**Shape.** Split `receive.parser` into a plain function that resolves the name and calls
`register_receiver`, returning an inner drain generator that owns the `try`/`finally`. That
separation is what F5b needs anyway — the `finally` has to wrap the drain loop and not the
registration — and it makes "subscribed" and "draining" two distinct states rather than one
generator that conflates them.

Do **not** mistake this for a fix to the low-level priming requirement. Registration is
deferred by *two* layers of laziness, not one: `operator`'s `sync_wrapper` ends in
`yield from processed` (`_decorators.py`), so it is itself a generator function and
`receive.pipe(conf=...)` returns an unstarted generator regardless of how `parser` is shaped.
Verified — after calling `pipe(conf=…)` the name is absent from `sync_hub.receivers`. Making
registration eager at the module level means making the *wrapper* a plain function that
returns an inner generator, which moves when prepare/parse/setup side effects and config
errors fire for every operator. That is a separate, decorator-wide decision; F0/F5 must not
smuggle it in.

Priming **does** go away on the raw path — § 2 is explicit that a `SyncSubscription` is
"registered synchronously at construction" and that `SyncPipe("receive", …)` keeps working
over it. The objection is to the *mechanism*, not the goal: bare-`register_receiver`-in-
`__init__` puts process-global side effects in an otherwise-pure constructor with no object
owning the resulting lifetime, which manufactures exactly the leak this phase exists to
remove — a receive pipe built and never drained would hold a registration forever. Eager
registration must arrive as a **handle** that owns release, not as a constructor side effect.
When it lands, `test_pubsub` needs rewriting: it constructs an unprimed `receiver2` on purpose
so the sender logs `Attempted to send … to non-existent 'receiver2'`, and that assertion only
holds while priming is what registers.

**Constraint.** Keep the `yield from` chain between `SyncPipe._stream` and `parser`
generator-native. An intermediate C-level iterator (`filterfalse`, `map`) has no `close()`,
so PEP 380 does not forward `GeneratorExit` through it; the `finally` would then fire only
via refcounted deallocation and would silently not run on a non-refcounting runtime.

**Leak policy.** A subscription that is neither released nor closed by its sender stays alive
until `reset_pubsub()`. That is the same process-global ownership problem F5/P11 already
migrate to `Context.resources` — F5b must not invent a second lifetime mechanism, only remove
the accidental "timeout is teardown" one and let the handle own release.

Exit tests:

* drain an idle subscribed receiver, run the sender, re-subscribe and drain → items arrive
  (today the second drain sees a fresh empty channel and the sender's completion never lands);
* `SyncPipe.subscribe(n).close()` releases the subscription and drops its hub state;
* sender-side completion still terminates its receivers — regression guard on
  `test_send_signals_done_on_early_close` and `test_send_done_respects_channel_identity`,
  both of which are written against the `DONE` sentinel and need porting to closure semantics.

### 9.3 Phase F5c — `receive`'s `func` becomes a tap (next)

**Independent of F5b and landable now** — it touches only `receive`, not the hub, so it does
not wait on the `Publisher`/`Subscription` rewrite. This is the next pub/sub step.

Today `receive` applies `func` to each arriving item and queues **the return value**, so the
receiver yields whatever `func` produced. That conflates two jobs:

1. a side-effect hook — `func=archived.append`, `func=print`, both of which return `None`;
2. a transform — `func=len`, which yields `1`.

Only the first is `receive`'s to do. `func` runs inside the receiver coroutine at *push* time,
during the sender's iteration, so its one distinctive capability is "do this when the item
arrives, whether or not anyone ever drains". That is a tap. A transform gains nothing from
running at push rather than drain time, and `udf` already owns transforms
(`subscribe("x").udf(func=len)`).

Target: **call `func` for its side effect, discard the return, and yield the item that
arrived.**

Consequences:

* **The `Item` typing problem disappears at the root.** Because the receiver currently queues
  `func`'s result, `receive.parser` can yield `None` (from `append`/`print`) or an `int` (from
  `len`) — neither of which is an `Item` — so `pipe`'s declared return does not satisfy
  `SyncOperatorParser`. As a tap the stream is `Stream | Iterator[StatefulItem]` again and the
  error is gone. **Do not "fix" that error by widening `OperatorParserOutput` with
  `StreamOrValueStream`** — it type-checks, but it enshrines the conflation and drops the
  checker's ability to reject a junk parser return for every other operator.
* **Chaining stops emitting junk.** `subscribe("x", func=archived.append).sort()` currently
  yields `[{'content': None}]`, because the operator wrapper wraps the non-mapping `None`.
* `ReceiveFunc` becomes `Callable[[Item], object]`, permissive enough for `append`, `print`,
  and `len` alike.
* `func=len` no longer yields `1`. That is the only capability lost; `.udf(func=len)` covers
  it. Clean break, per § 2's no-deprecated-aliases policy.

Exit tests: `test_pubsub_funcs` currently asserts `next(printer) is None` and
`next(changer) == 1`, pinning the conflation — each becomes "the side effect fired *and* the
item passed through". The cookbook's fan-out recipe loses its `_ = list(everything)` workaround
and the note explaining that receivers hold `func` return values.

`func` is a misnomer once the return is ignored; the rename (`tap`/`on_item`) belongs to § 2's
vocabulary clean break alongside `others`→`targets`, not to this phase.

### 9.4 Open questions

1. What happens when a sender publishes before a receiver exists?
2. Can a receiver subscribe after publishing begins?
3. Is history replayed? Default: no.
4. ~~Who closes the channel?~~ **F5b:** the subscription handle — released by the pipe that
   opened it (`close()`/`terminate()`), or closed from the sender's side. Never a poll timeout.
5. ~~What happens when the final receiver disappears?~~ **F5b:** the subscription is released;
   a later `send` to that name stays log-and-continue (sync) / `ReceiverUnavailableError`
   after `max_wait` (async), until § 2's "eliminate silent data loss" makes sync raise too (F4).
6. What happens to the sender when a receiver fails?
7. Can multiple receivers use the same logical name?

Note on 3: buffering starts at subscription time. Items published after `subscribe` and before
the drain are queued and delivered; nothing published before `subscribe` is replayed.

Initial recommendation:

* subscriptions are execution-scoped;
* no historical replay;
* receiver registration occurs before consumption starts;
* unknown subscriber names fail early by default;
* sender completion closes attached channels;
* a detached subscriber follows explicit `on_subscriber_error` policy.

Persistent broker semantics are connector concerns, not in-process `send` / `receive`
semantics.

The public [`Pipeline`](release-readiness.md) pub/sub UX rides on F5: a producer
`Pipeline(source=…).send(targets=[…])` and a consumer `Pipeline.subscribe("…")` (or
`flow.subscribe`) resolve their channel from the execution's resource scope (`Context.resources`),
not a process global. Producer vocabulary is `targets` (renamed from `others`, clean break —
[release-readiness.md § 2](release-readiness.md)).

## 10. Phase F6 — topology-aware workflow representation

Branching must become visible to workflow introspection rather than existing only as
runtime side effects.

A plan should be able to report:

```json
{
  "nodes": ["fetch", "filter", "union"],
  "channels": {
    "archive": {
      "producer": "send-1",
      "consumers": ["receive-1"],
      "buffer": 1024,
      "overflow": "block"
    }
  },
  "edges": [
    ["fetch", "send-1"],
    ["send-1", "filter"],
    ["branch-a", "union"],
    ["branch-b", "union"]
  ]
}
```

The compiler and dependency extractor should distinguish:

* primary stream edges;
* secondary `other`/`others` fan-in edges;
* named channel edges;
* routed branch edges.

A future CLI can render this data, but graphical visualization is not required for the
first milestone.

## 11. Phase F7 — branch-to-fan-in ergonomics

Riko already has `union` and `join`. Do not add redundant generic `rejoin()` APIs.
Instead, make branch outputs ordinary pipe objects that can feed the existing fan-in
operators naturally.

Desired patterns:

```python
matched, unmatched = flow.branch(conf=rule)

result = SyncPipe(
    "union",
    matched.transform(...),
    others=[unmatched.transform(...)],
)
```

and:

```python
left, right = flow.branch(conf=rule)

result = SyncPipe(
    "join",
    left,
    conf={"join_key": "id", "other_join_key": "id"},
    other=right,
)
```

When concurrent async fan-in is desired, use the planned `merge` operator from the
execution-semantics gameplan rather than changing `union`.

## 12. Error and cancellation semantics

Fan-out multiplies failure surfaces, so policies must be explicit.

Suggested send policy:

```python
on_subscriber_error: Literal[
    "fail",
    "detach",
] = "fail"
```

`fail`:

* fail the sender;
* close sibling channels;
* cancel pending async work;
* preserve the original subscriber exception.

`detach`:

* record a partial/degraded event;
* detach the failed subscriber;
* continue healthy branches.

`detach` is only valid when the subscriber side effect is declared optional or an
execution policy explicitly allows degraded output.

## 13. Ordering contract

Ordering must be defined separately per primitive:

* `send`: preserves primary-stream order and publication order per subscriber;
* `branch`: preserves relative order within each output branch;
* `route`: preserves relative order per selected branch unless configured otherwise;
* `union`: primary stream followed by each `others` stream in list order;
* `merge`: follows its own planned scheduling contract;
* `join`: order follows the join implementation and must not be described as a temporal
  synchronization primitive.

## 14. Memory and boundedness

Topology features must not silently convert an unbounded feed into a materialized
collection.

Rules:

* `split` remains explicitly eager and finite-oriented;
* `send` / `receive` remain bounded-channel streaming operations;
* `branch` and `route` are streaming;
* `union` is streaming sequential concatenation;
* `merge` is bounded concurrent streaming;
* `join` may require finite/materialized behavior depending on implementation and must
  declare that requirement through the execution-semantics contract.

## 15. Comparison-derived design lessons

### Streamz

Borrow:

* branching and fan-in as visible topology;
* explicit backpressure expectations;
* independent downstream consumers.

Do not copy:

* a wholesale reactive graph API;
* feedback-loop semantics until Riko has a concrete use case and execution contract.

### Bytewax

Borrow:

* explicit route/branch semantics;
* separation between topology and stateful processing.

Do not copy:

* distributed worker ownership;
* durable keyed-state runtime as a prerequisite for local routing.

### Bonobo

Borrow:

* inspectable DAG edges and explicit branch structure.

Do not copy:

* graph construction as the only user-facing pipeline API.

## 16. Testing strategy

Add contract tests for both sync and async implementations.

Required cases:

1. broadcast one source to two subscribers;
2. slow subscriber blocks under `overflow="block"`;
3. lossy subscriber policy drops only on the configured branch;
4. async receiver yields before sender completion;
5. cancellation closes channels and upstream feeds;
6. binary branch routes every item exactly once;
7. route preserves per-branch order;
8. union preserves sequential concatenation;
9. join retains current keyed semantics;
10. branch outputs feed `union` and `join` without special adapters;
11. abandoned subscriber does not leak tasks;
12. workflow introspection reports primary, secondary, and channel edges accurately.

## 17. Phases

```text
F0  Document current topology contract
F1  Streaming AsyncPipe receive
F2  Binary conditional branch
F3  Named N-way routing / partitioning
F4  Per-subscriber buffers and overflow policy
F5a Subscription lifecycle API (landed)
F5c Receive `func` becomes a tap (next — independent of F5b)
F5b Subscription handles + teardown ownership (lands with P11)
F6  Topology introspection / workflow representation
F7  Branch-to-union/join ergonomic examples and contracts
```

## 18. Definition of done

1. `send` / `receive` are incremental in both sync and async execution.
2. Conditional routing is first-class and configuration-driven.
3. Broadcast and partition semantics are separate public concepts.
4. Buffering and slow-subscriber behavior are explicit and testable.
5. `union` remains sequential fan-in and `join` remains relational fan-in.
6. Existing fan-in operators compose naturally with branch outputs.
7. Workflow introspection can describe channel and fan-in topology.
8. Cancellation and subscriber failure do not leak channels or tasks; an idle drain ends the
   pass, never the subscription (F5b).
9. No topology feature requires a distributed runtime.
10. Existing `split`, `union`, `join`, and sync `send` behavior remain backward compatible.
11. A receiver yields only the items it received — a `func` is a tap, never a transform (F5c).
