# Fan-out, routing & fan-in gameplan

## 1. Mission

Make branching topology a first-class, inspectable part of Riko while preserving ordinary streaming
iteration and keeping distributed-runtime concerns out of core.

This plan owns the **topology** contract: explicit broadcast, routing, split, subscriber lifecycle,
and fan-in composition. Generic execution/resource/state semantics remain owned by
[execution-semantics.md](execution-semantics.md).

Current `send` / `receive` and eager legacy `split` implementations are migration inputs, not the
final public topology contract.

## 2. Canonical topology model

Riko keeps four concepts separate:

```text
broadcast
    one item -> every selected branch

route
    one item -> one selected branch

union / merge
    multiple streams -> one stream

join
    related records from multiple streams -> combined records
```

Shared DAG ancestry alone never implies fan-out. A definition branches only through an explicit
fan-out primitive such as `split()` or `publish()`.

## 3. Fan-in semantics preserved

### 3.1 `union` is sequential fan-in

`union` concatenates its inputs in sequence. It is not an interleaving merge and does not combine
item identity.

```text
A: a1 a2
B: b1 b2

union(A, B)
-> a1 a2 b1 b2
```

Each input item retains its own provenance. `union()` does not synthesize a combined identity.
Concurrent interleaving belongs to `merge` and its execution-semantics scheduling contract.

### 3.2 `join` is relational fan-in

`join` combines related records, optionally through `join_key` / `other_join_key`. It remains
distinct from `union`, `merge`, positional pairing, and temporal synchronization.

## 4. Public publish / subscribe contract

The final public vocabulary is object-first:

```python
class Publisher[T](Protocol): ...
class Subscription[T](Protocol): ...
class Channel[T](Publisher[T], Subscription[T], Protocol): ...
```

Low-level compatibility modules may remain named `send` / `receive`, but they do not define the
final Python API.

### 4.1 Local subscriptions

Declare a local subscription as a Pipeline object:

```python
events = Pipeline.subscribe("events")
flow = flow.publish(events)
```

`publish(events)` attaches the complete subscription branch to the producer's execution. The user
does not have to drain ignored branch output to trigger work or cleanup. Terminal branch values are
discarded unless the branch contains an explicit sink, tap, or routing effect.

Calling:

```python
list(events)
```

independently creates a fresh execution. A subscription definition is not a replay buffer.

### 4.2 External subscriptions and publishers

An external `Subscription[T]` is an ordinary source:

```python
flow = Pipeline(source=subscription)
```

`publish()` accepts either a local subscription Pipeline or an external `Publisher[T]`.

### 4.3 Names and identity

Multiple local subscriptions may share the same display name. Python object identity distinguishes
those definitions.

Serialized workflow declarations may remain concise:

```json
{"name": "events"}
```

A serialized target name resolves every same-name subscription in that compiled definition unless an
explicit serialized id selects one declaration.

## 5. Subscriber scheduling, buffering, and errors

### 5.1 Scheduling

Synchronous subscriber work is inline by default. Parallel subscriber execution is an explicit
execution-concurrency choice, not an implicit property of pub/sub.

Async subscriber orchestration is owned by the private execution. An MVP may use
`asyncio.create_task()` internally, but cancellation and teardown belong to the execution lifecycle.

### 5.2 Buffering

Async/local subscriptions default to rendezvous semantics:

```python
buffer_size = 0
overflow = "block"
```

The public overflow vocabulary is intentionally small:

```python
Literal["block", "drop"]
```

`block` is lossless and is the default. For a bounded buffered subscription, `drop` discards the
oldest buffered item and keeps the newest item, matching the useful behavior of the current sync
queue.

There is no implicit lossy mode.

### 5.3 Error policy

Subscriber errors use only:

```python
Literal["raise", "ignore"]
```

Default is `"raise"`. `"ignore"` means per-item continuation for that subscriber; it does not turn
all branch failures into successful execution.

### 5.4 Tap semantics

A subscriber `tap=` may be sync or async. Its return value is discarded:

```python
def archive(item):
    saved.append(item)

subscription = Pipeline.subscribe("archive", tap=archive)
```

The received item remains the logical stream value. The old `receive(func=...)` transformation
behavior is not the target contract; transformation belongs in an ordinary downstream node.

## 6. Multiple publishers and completion

More than one publisher may target one subscription. The subscription completes only after **all**
attached publishers complete.

Per-subscription delivery order is guaranteed. When multiple publishers run concurrently, observed
order is actual delivery order; Riko does not invent a global source ordering.

A publisher completing or failing must not strand subscriber tasks or channels. Execution teardown
owns final cleanup.

## 7. `split()` is streaming fan-out

The final `split()` contract supersedes the legacy eager finite duplication behavior.

```python
left, right = flow.split(2)
```

Semantics:

- upstream is consumed once;
- active branches receive items incrementally;
- only reachable/used outputs become active;
- unused outputs allocate no queue and exert no backpressure;
- each active branch has a bounded buffer;
- default branch buffer is zero/rendezvous;
- split is lossless and has **no** drop overflow mode;
- per-branch ordering follows upstream order;
- infinite/unbounded upstreams remain streamable.

### 7.1 Branch isolation

Split branches are observably isolated: mutation in one branch must not silently corrupt another
branch's logical value.

The runtime chooses the cheapest safe copy/share strategy. There is no public copy-mode knob in the
initial API.

Similarly:

```python
flow.publish(target, isolate=True)
```

isolates publication by default. `isolate=False` is the explicit escape hatch when sharing is known
to be safe and desired.

## 8. Conditional routing

Broadcast and routing are separate. A binary branch sends each item to exactly one output:

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

Requirements:

- every input item appears in exactly one output;
- existing filter/rule configuration is reused;
- relative order is preserved within each branch;
- both outputs are streaming;
- abandoned/unreachable outputs do not create hidden unbounded queues;
- callable predicates may be supported through callable-node integration, while serialized forms
  remain data-representable.

Do not call this operation `split`; `split` means broadcast duplication.

## 9. Named routing / partitioning

After binary branch semantics are stable, N-way routing may support:

```python
flow.route(
    field="customer_id",
    branches=["a", "b", "c"],
    strategy="hash",
)
```

Initial strategies may include:

```text
hash
round_robin
rule
```

Requirements:

- deterministic hash routing uses Riko's common canonical identity/fingerprint system;
- branch-count changes are documented as repartitioning events;
- round-robin ordering is explicit;
- routing remains local to one execution;
- no distributed leases, partition ownership, or worker-assignment system is introduced here.

## 10. Topology representation

Branching must be visible to workflow introspection rather than existing only as runtime side
effects.

A compiled plan must distinguish:

- primary stream edges;
- secondary fan-in edges;
- publish/subscription edges;
- split branches;
- routed branches.

A serialized workflow may use display names for convenience, but the compiled graph resolves them
to concrete node/subscription identities before execution.

## 11. Branch-to-fan-in composition

Do not add a redundant generic `rejoin()` primitive. Branch outputs are ordinary Pipeline
definitions and feed existing fan-in operators.

Conceptually:

```python
matched, unmatched = flow.branch(conf=rule)
result = Pipeline.union(
    matched.transform(...),
    unmatched.transform(...),
)
```

and relational branches may feed `join`.

Concurrent async fan-in uses `merge`; sequential concatenation remains `union`.

## 12. Ordering contract

Ordering is defined per primitive:

- `publish`: preserves publication order per subscription;
- multiple concurrent publishers: actual delivery order, no artificial cross-source ordering;
- `split`: preserves upstream order independently in each active branch;
- `branch`: preserves relative order in each selected output;
- `route`: preserves relative order per selected branch unless the routing strategy explicitly says
  otherwise;
- `union`: input streams concatenate in declared order;
- `merge`: follows the execution-semantics scheduling contract;
- `join`: follows relational operator semantics, not temporal synchronization semantics.

## 13. Memory and boundedness

Topology primitives must never hide unbounded materialization.

Rules:

- `split` is bounded streaming fan-out;
- publish/subscribe is bounded streaming fan-out;
- branch and route are streaming;
- `union` is lazy sequential fan-in;
- `merge` is bounded concurrent fan-in;
- `join` may require finite/materialized behavior and must declare that execution characteristic.

## 14. Relationship to current `send` / `receive`

Current hubs and modules are implementation/migration inputs:

- sync currently uses queue/generator-coroutine mechanics and historical PENDING/DONE bookkeeping;
- async uses AnyIO channels but has had incremental-delivery/materialization defects;
- current receiver `func` behaves like a transform rather than a tap;
- current lifecycle can tie cleanup to draining a receiver.

The target rewrite must preserve useful observable behavior while deleting those hidden ownership
mechanisms. In particular:

- no PENDING records on the final data stream;
- completion is channel/subscription lifecycle, not a user-visible DONE item;
- registration/teardown belongs to execution-owned subscription handles;
- cleanup does not depend on draining ignored output;
- async delivery is incremental;
- tap semantics change sync and async together.

Feed-native async parser support is therefore a prerequisite for the async compatibility modules and
is implemented through the common Feed-native parser mechanism, not a pub/sub-specific wrapper hack.

### 14.1 Revised compatibility MVP boundary

The compatibility MVP is deliberately narrower than the final F5 contract. Its purpose is to make
the existing sync/async pub/sub surfaces stream equivalently without prematurely rebuilding final
Pipeline ownership on top of compatibility machinery.

For that MVP:

- keep string-target `SyncPipe` / `AsyncPipe` publish/send and subscribe/receive behavior; strings
  also remain valid serialized/wire references after the final Python API becomes object-first;
- keep the current AnyIO zero-buffer/rendezvous async channel backend rather than adding a second
  buffering model;
- make async `send` and `receive` Feed-native and incremental, so the first delivered item is visible
  before publisher completion and unbounded feeds do not require whole-stream materialization;
- preserve the current subscriber `func` **transformation** behavior in both sync and async during
  the MVP. Do not change only the async side to tap semantics;
- `asyncio.create_task()` is acceptable for MVP subscriber concurrency when tasks are explicitly
  tracked and cleaned up; final structured orchestration belongs to the private execution;
- do not repair the sync idle-drain teardown bug by extending the old DONE/id bookkeeping. Keep that
  behavior characterized while F5 replaces the ownership mechanism instead of hardening machinery
  that is scheduled for deletion.

F5 then changes sync and async **together** to the final contract:

- object-first `Publisher` / `Subscription` / `Channel` and `Pipeline.subscribe(...)` /
  `flow.publish(subscription)`;
- `tap=` replaces transformation-shaped subscription `func`; the callback return is discarded and
  the received item remains the logical value;
- subscription/channel/task lifetime belongs to the private execution and cleanup never depends on
  the user draining ignored subscriber output;
- PENDING/DONE data markers and hidden sender ids are removed from the public lifecycle;
- multiple same-name local subscriptions are distinguished by object identity;
- one subscription targeted by multiple publishers completes only after all attached publishers
  complete.

This staging boundary is intentional: F1 fixes compatibility streaming; F5 owns the semantic
lifecycle/tap transition. Do not partially backport F5 semantics into the MVP.

## 15. Testing strategy

The tests below are grouped by **what they constrain**, not by phase. §15.1 are behavioral
outcomes that any implementation (F1…F5) must satisfy — they assert observable stream behavior, not
the pub/sub API surface, so they survive the F5 object-first transition unchanged. §15.2 documents
current compatibility behavior that F5 is *expected to change*; it is characterization, not a forward
contract. §15.3 asserts the F5 object-first surface itself and must not be frozen as migration tests
before that surface lands. (Test names below reference behavior only; xfail reasons stay
API-agnostic — "… not yet implemented" — never an internal F-label.)

### 15.1 Acceptance contracts (behavioral outcomes — decoupled from the API surface)

Encode these now. Where the behavior is not yet true, land a `strict=True` xfail so the guard flips
(and demands removal) the moment the behavior arrives.

Pub/sub streaming:

1. one source broadcasts incrementally to two subscriptions;
2. an async subscriber sees its first item before the publisher finishes reading its source
   — *shipped*; `test_async_subscriber_sees_item_before_publisher_completes`;
3. async `receive` does not materialize its source; the zero-buffer rendezvous channel delivers each
   item as it is published — *shipped*; `test_async_receive_does_not_materialize`;
4. async `send` does not buffer its own passthrough return (an unbounded source still returns a
   stream) — *not yet*; strict-xfail `test_async_send_does_not_buffer_its_source`;
5. publish/send is transparent: the publisher's own stream passes through unchanged;
6. zero-buffer subscription propagates backpressure;
7. lifecycle/state markers never leak into user data — *not yet* (sync `receive` surfaces
   `PENDING`/`DONE`); strict-xfail `test_lifecycle_markers_do_not_leak_into_user_data`;
8. bounded `overflow="drop"` drops oldest only on that configured subscription;
9. multiple publishers keep one subscription open until all publishers finish (completion outcome).

Topology:

10. `split()` consumes upstream once and streams to active branches;
11. unused split outputs allocate no runtime branch/backpressure;
12. split is lossless under slow consumers;
13. branch routes every item exactly once;
14. route preserves per-branch order;
15. `union` preserves sequential concatenation and input provenance;
16. join retains keyed relational semantics;
17. cancellation/early close leaks no tasks/channels/subscriptions;
18. attached publication branches clean up without a user drain.

### 15.2 MVP characterization (current compatibility behavior; expected to change under F5)

Keep these to pin present behavior, but do **not** read them as forward contracts:

1. subscriber `func` transformation semantics in both sync and async (`test_pubsub_funcs`) — F5
   replaces this with `tap=` (return discarded);
2. sync `receive` currently interleaves `PENDING`/`DONE` markers into the drained stream
   (`test_pubsub`) — the acceptance target that it must *not* is §15.1(7).

### 15.3 F5 API-shape contracts (assert once the object-first surface lands; not migration tests)

1. object-first `Publisher` / `Subscription` / `Channel` with `Pipeline.subscribe(...)` /
   `flow.publish(subscription)`;
2. sync and async `tap=` both discard return values and preserve the item;
3. multiple same-name subscription objects remain distinct by identity;
4. external `Subscription` works as a Pipeline source;
5. topology introspection reports stream, fan-in, split, and subscription edges (F6 surface).

## 16. Implementation phases

The historical F-labels remain useful for work tracking, but the final contracts above supersede
earlier eager-split / AsyncPipe-first API sketches.

```text
F0  Document current compatibility topology
F1  Feed-native incremental async send/receive compatibility modules
F2  Binary conditional branch
F3  Named N-way route / partition
F4  Final bounded subscription buffering/error policy
F5  Execution-owned Publisher/Subscription lifecycle + tap semantics
F6  Topology introspection / serialized representation
F7  Branch-to-union/join ergonomic contracts
```

Forward dependency ordering across core runtime PRs is owned by
[implementation-sequence.md](implementation-sequence.md), especially R4/R5/R7. These F labels do not
create a parallel implementation sequence.

## 17. Definition of done

1. Public Python pub/sub uses `publish` / `subscribe` objects rather than requiring low-level
   `send` / `receive` knowledge.
2. Publish/subscribe and split are incremental and bounded in both sync and async execution.
3. `split()` consumes upstream once, activates only reachable branches, and is lossless.
4. Broadcast and routing remain separate concepts.
5. Subscriber buffering, overflow, ordering, errors, and tap behavior are explicit.
6. Multiple publisher completion is correct and deterministic at the subscription-lifecycle level.
7. `union` remains sequential fan-in; `join` remains relational fan-in.
8. Branch outputs compose naturally with existing fan-in operators.
9. Workflow introspection can describe explicit branch/channel topology.
10. Cancellation, early close, subscriber failure, and ignored attached branches leak no runtime
    resources.
11. No topology feature requires a distributed runtime.