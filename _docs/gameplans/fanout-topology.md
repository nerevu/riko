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

The current sync receiver priming requirement exposes generator-coroutine mechanics. Add a
public subscription helper that owns priming and cleanup.

Possible shape:

```python
receiver = SyncPipe.subscribe("alerts")
```

or:

```python
receiver = flow.subscribe("alerts")
```

The API must answer explicitly:

1. What happens when a sender publishes before a receiver exists?
2. Can a receiver subscribe after publishing begins?
3. Is history replayed? Default: no.
4. Who closes the channel?
5. What happens when the final receiver disappears?
6. What happens to the sender when a receiver fails?
7. Can multiple receivers use the same logical name?

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
F5  Subscription lifecycle API
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
8. Cancellation and subscriber failure do not leak channels or tasks.
9. No topology feature requires a distributed runtime.
10. Existing `split`, `union`, `join`, and sync `send` behavior remain backward compatible.
