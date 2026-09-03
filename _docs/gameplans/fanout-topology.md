# Fan-out, routing & fan-in gameplan

## 1. Mission

Make branching topology a first-class, inspectable part of Riko while preserving ordinary streaming
iteration and keeping distributed-runtime concerns out of core.

This plan owns the **topology** contract: explicit broadcast, routing, split, subscriber lifecycle,
and fan-in composition. Generic execution/resource/state semantics remain owned by
[execution-semantics.md](execution-semantics.md). Canonical Workflow v2 normalization and schema
sequencing are ordered by [implementation-sequence.md](implementation-sequence.md).

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

Shared DAG ancestry alone never implies fan-out. A definition branches only through explicit topology.

The canonical graph rule is:

```text
node = executable/owned behavior
edge = relationship/delivery semantics
```

Therefore:

```text
split        -> ModuleNode + StreamEdges from distinct output ports
branch/route -> ModuleNode + StreamEdges from semantic output ports
publish      -> PublishEdge
subscription -> SubscribeNode
union/join   -> ModuleNode + distinct indexed input ports
```

There is no public/canonical `PublishNode` and no top-level channel table. A subscription is a node
because it owns delivery/buffering/error policy; publication is an edge because it is a relationship
between a producer output and that subscription.

Canonical edges are a discriminated union:

```text
StreamEdge
PublishEdge
```

Canonical ports use one grammar:

```text
in / out             default port
in:N / out:N         positional ports
out:<name>            semantic named output port
```

A source port may have multiple outgoing stream edges. A target stream port has at most one incoming
stream edge. Multi-input operators use distinct input ports rather than repeated edges into one port.

Legacy positional identities normalize as:

```text
_INPUT   -> in
_OTHER   -> in:1
_OTHER2  -> in:2
_OTHER3  -> in:3
_OUTPUT  -> out
_OUTPUT2 -> out:1
_OUTPUT3 -> out:2
```

Port identity, never traversal order or JSON array order, carries operand/branch position.

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

Canonical wiring makes today's positional semantics explicit:

```text
A.out -> union.in
B.out -> union.in:1
C.out -> union.in:2
```

which maps directly to the current logical call shape:

```text
stream = A
others = [B, C]
```

Each input item retains its own provenance. `union()` does not synthesize a combined identity.
Concurrent interleaving belongs to `merge` and its execution-semantics scheduling contract.

### 3.2 `join` is relational fan-in

`join` combines related records, optionally through `join_key` / `other_join_key`. It remains
distinct from `union`, `merge`, positional pairing, and temporal synchronization.

Like union, each distinct operand is represented by a distinct canonical input port. Module metadata
owns what those positional inputs mean semantically.

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

Canonical Workflow v2 represents this with a `SubscribeNode` and one or more incoming `PublishEdge`s.
The subscription node owns `buffer_size`, `overflow`, and error policy. Multiple incoming publish
edges structurally define the publisher set and therefore completion semantics.

`publish(events)` attaches the complete subscription branch to the producer's execution. The user
does not have to drain ignored branch output to trigger work or cleanup. Terminal branch values are
discarded unless the branch contains an explicit write/action/on_receive/routing effect.

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

Async subscriber orchestration is owned by the private execution. Every subscriber task is created
under the execution's task group; final code permits no detached tasks. Compatibility code may retain
tracked transitional tasks only until the execution-owned model lands.

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
oldest buffered item and keeps the newest item. There is no implicit lossy mode.

### 5.3 Error policy

Subscriber errors use only:

```python
Literal["raise", "ignore"]
```

Default is `"raise"`. `"ignore"` means per-item continuation for that subscriber; it does not turn
all branch failures into successful execution.

### 5.4 `on_receive` semantics

A subscriber `on_receive=` may be sync or async. Its return value is discarded:

```python
def archive(item):
    saved.append(item)


subscription = Pipeline.subscribe("archive", on_receive=archive)
```

The received item remains the logical stream value. The old `receive(func=...)` transformation
behavior is not the target contract; transformation belongs in an ordinary downstream node.

## 6. Multiple publishers and completion

More than one publisher may target one subscription. The subscription completes only after **all**
attached publishers complete.

This is structural in canonical v2: all incoming `PublishEdge`s are known before execution. Runtime
sender-handle ownership derives from that topology; there are no PENDING/DONE data markers and no
explicit integer publisher-count protocol in user-visible data.

Per-subscription delivery order is guaranteed. When multiple publishers run concurrently, observed
order is actual delivery order; Riko does not invent a global source ordering.

A publisher completing or failing must not strand subscriber tasks or channels. Execution teardown
owns final cleanup.

## 7. `split()` is streaming fan-out

The final `split()` contract supersedes the legacy eager finite duplication behavior.

```python
left, right = flow.split(2)
```

`split` remains an ordinary registered multi-output module. Its output contract is positional:

```text
split.out
split.out:1
split.out:2
...
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

Broadcast and routing are separate. A binary branch sends each item to exactly one semantic output:

```python
matched, unmatched = flow.branch(
    conf={"rule": {"field": "score", "op": "greater", "value": 500}}
)
```

Canonical ports are semantic rather than positional:

```text
branch.out:matched
branch.out:unmatched
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
flow.route(field="customer_id", branches=["a", "b", "c"], strategy="hash")
```

Canonical output ports preserve route identity:

```text
route.out:a
route.out:b
route.out:c
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

## 10. Port declaration and validation

The registered node/module contract declares the valid ports. Edges connect declared ports; edges do
not create ports.

For fixed routing, the contract statically declares semantic ports. For configurable routing/split,
node configuration determines the declared port set during normalization/preparation.

Examples:

```text
split(splits=3)
    -> out, out:1, out:2

branch(...)
    -> out:matched, out:unmatched

route(branches=["a", "b", "c"])
    -> out:a, out:b, out:c
```

An unconnected declared output remains valid. Reachability determines whether runtime machinery is
allocated for it.

Canonical validation rejects:

- edges referencing undeclared ports;
- more than one incoming stream edge to the same target stream port;
- fan-in operand gaps when the owning contract requires contiguous positional inputs;
- topology whose referenced nodes do not exist.

## 11. Branch-to-fan-in composition

Do not add a redundant generic `rejoin()` primitive. Branch outputs are ordinary Pipeline
definitions and feed existing fan-in operators.

Conceptually:

```python
matched, unmatched = flow.branch(conf=rule)
result = Pipeline.union(matched.transform(...), unmatched.transform(...))
```

Canonical wiring is explicit:

```text
branch.out:matched   -> left_transform.in
branch.out:unmatched -> right_transform.in
left_transform.out   -> union.in
right_transform.out  -> union.in:1
```

Concurrent async fan-in uses `merge`; sequential concatenation remains `union`.

## 12. Ordering contract

Ordering is defined per primitive:

- `publish`: preserves publication order per subscription;
- multiple concurrent publishers: actual delivery order, no artificial cross-source ordering;
- `split`: preserves upstream order independently in each active branch;
- `branch`: preserves relative order in each selected output;
- `route`: preserves relative order per selected branch unless the routing strategy explicitly says
  otherwise;
- `union`: input streams concatenate in port/declaration order (`in`, `in:1`, `in:2`, ...);
- `merge`: follows the execution-semantics scheduling contract;
- `join`: follows relational operator semantics, not temporal synchronization semantics.

JSON edge-list order never determines semantic input ordering.

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
- current receiver `func` behaves like a transform rather than an on_receive callback;
- current lifecycle can tie cleanup to draining a receiver.

The target rewrite must preserve useful observable behavior while deleting those hidden ownership
mechanisms. In particular:

- no PENDING/DONE records on the final data stream;
- completion is subscription/channel lifecycle, not a user-visible sentinel;
- registration/teardown belongs to execution-owned handles;
- cleanup does not depend on draining ignored output;
- async delivery is incremental;
- on_receive semantics change sync and async together.

Feed-native async parser support is implemented through the common Feed-native parser mechanism, not
a pub/sub-specific wrapper hack.

### 14.1 Compatibility staging boundary

Compatibility work may keep string-target `SyncPipe` / `AsyncPipe` send/receive behavior while the
old surfaces survive. Strings also remain valid serialized/wire references after the final Python API
becomes object-first.

Compatibility fixes should make async send/receive incremental and preserve currently documented
sync/async behavior together, but must not extend DONE/PENDING bookkeeping. Final R7 replaces that
ownership mechanism with `SubscribeNode`/`PublishEdge` topology, execution-owned sender handles, and
`on_receive=` semantics in both modes.

Do not partially implement final object-first lifecycle semantics inside the compatibility hub.

## 15. Testing strategy

### 15.1 Acceptance contracts

Encode these as behavior-level contracts independent of compatibility API shape:

1. one source broadcasts incrementally to two subscriptions;
2. an async subscriber sees its first item before the publisher finishes reading its source;
3. async receive does not materialize its source;
4. async send does not buffer its own passthrough return;
5. publication is transparent to the producer's ordinary stream;
6. zero-buffer subscription propagates backpressure;
7. lifecycle/state markers never leak into user data;
8. bounded `overflow="drop"` drops oldest only on that configured subscription;
9. multiple publishers keep one subscription open until all publishers finish;
10. `split()` consumes upstream once and streams to active branches;
11. unused split outputs allocate no runtime branch/backpressure;
12. split is lossless under slow consumers;
13. branch routes every item exactly once;
14. route preserves per-branch order;
15. `union` preserves sequential concatenation and input provenance;
16. join retains keyed relational semantics;
17. cancellation/early close leaks no tasks/channels/subscriptions;
18. attached publication branches clean up without a user drain;
19. canonical fan-in ordering is preserved after deterministic edge sorting;
20. invalid/duplicate target-port wiring fails before source consumption.

### 15.2 Compatibility characterization

Keep current compatibility tests that pin behavior scheduled to change, but do not treat them as
forward contracts. In particular current transformation-shaped receiver callbacks and sentinel
visibility are migration fixtures only.

### 15.3 Final API/IR contracts

Assert once the object-first surface and Workflow v2 land:

1. `SubscribeNode` + `PublishEdge` canonical topology;
2. sync and async `on_receive=` both discard return values and preserve the item;
3. multiple same-name subscription objects remain distinct by identity;
4. external `Subscription` works as a Pipeline source;
5. split uses positional output ports;
6. branch/route use semantic output ports;
7. union/join/merge operands use distinct indexed input ports;
8. one target stream port accepts at most one incoming stream edge.

## 16. Implementation phases

Historical F-labels remain useful for local work tracking, but the forward dependency order is owned
by [implementation-sequence.md](implementation-sequence.md). In particular, canonical topology
structure lands in R4A, provenance in R5A, and runtime fanout in R7.

```text
F0  Document current compatibility topology
F1  Feed-native incremental async send/receive compatibility modules
F2  Binary conditional branch
F3  Named N-way route / partition
F4  Final bounded subscription buffering/error policy
F5  Execution-owned Publisher/Subscription lifecycle + on_receive semantics
F6  Workflow v2 topology integration / introspection
F7  Branch-to-union/join ergonomic contracts
```

These F labels do not create a parallel implementation sequence.

## 17. Definition of done

1. Public Python pub/sub uses `publish` / `subscribe` objects rather than requiring low-level
   `send` / `receive` knowledge.
2. Canonical Workflow v2 represents subscriptions as `SubscribeNode`s and publication as
   `PublishEdge`s.
3. Publish/subscribe and split are incremental and bounded in both sync and async execution.
4. `split()` consumes upstream once, activates only reachable branches, and is lossless.
5. Split uses positional output ports; branch/route use semantic named ports.
6. Fan-in operands use distinct indexed input ports, never edge-list order.
7. Broadcast and routing remain separate concepts.
8. Subscriber buffering, overflow, ordering, errors, and on_receive behavior are explicit.
9. Multiple publisher completion is derived from topology/owned sender lifetime, not data sentinels.
10. `union` remains sequential fan-in; `join` remains relational fan-in.
11. Branch outputs compose naturally with existing fan-in operators.
12. Cancellation, early close, subscriber failure, and ignored attached branches leak no runtime
    resources.
13. No topology feature requires a distributed runtime.
