# Fan-out, routing & fan-in gameplan

## 1. Mission

Make branching topology a first-class, inspectable part of Riko while preserving
ordinary streaming iteration and keeping distributed-runtime concerns out of core.

This plan owns the **topology** contract: explicit broadcast, routing, split, subscriber
lifecycle, and fan-in composition. Generic execution/resource/state semantics remain
owned by [execution-semantics.md](execution-semantics.md). Canonical Workflow v2
normalization and schema sequencing are ordered by
[implementation-sequence.md](implementation-sequence.md).

Current `send` / `receive` and eager legacy `split` implementations are migration
inputs, not the final public topology contract.

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

Shared DAG ancestry alone never implies fan-out. A definition branches only through
explicit topology.

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

There is no public/canonical `PublishNode` and no top-level channel table. A
subscription is a node because it owns delivery/buffering/error policy; publication is
an edge because it is a relationship between a producer output and that subscription.

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

A source port may have multiple outgoing stream edges. A target stream port has at most
one incoming stream edge. Multi-input operators use distinct input ports rather than
repeated edges into one port.

Legacy positional identities normalize as:

```text
_INPUT   -> in
_OTHER   -> in:1
_OTHER1  -> in:1   (alias of _OTHER; wiring both into one node is rejected)
_OTHER2  -> in:2
_OTHER3  -> in:3
_OUTPUT  -> out
_OUTPUT2 -> out:1
_OUTPUT3 -> out:2
```

Port identity, never traversal order or JSON array order, carries operand/branch
position.

## 3. Fan-in semantics preserved

### 3.1 `union` is sequential fan-in

`union` concatenates its inputs in sequence. It is not an interleaving merge and does
not combine item identity.

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

Each input item retains its own provenance. `union()` does not synthesize a combined
identity. Concurrent interleaving belongs to `merge` and its execution-semantics
scheduling contract.

### 3.2 `join` is relational fan-in

`join` combines related records, optionally through `join_key` / `other_join_key`. It
remains distinct from `union`, `merge`, positional pairing, and temporal
synchronization.

Like union, each distinct operand is represented by a distinct canonical input port.
Module metadata owns what those positional inputs mean semantically.

## 4. Public publish / subscribe contract

The final public vocabulary is object-first:

```python
class Publisher[T](Protocol): ...


class Subscription[T](Protocol): ...


class Channel[T](Publisher[T], Subscription[T], Protocol): ...
```

Current low-level `send` / `receive` modules exist only as pre-R7
migration/characterization inputs. R7 removes those Python modules when the object-first
`publish` / `subscribe` surface lands; there is no deprecated low-level compatibility
API in the target surface.

### 4.1 Local subscriptions

Declare a local subscription as a Pipeline object:

```python
events = Pipeline.subscribe("events")
pipeline = pipeline.publish(events)
```

Canonical Workflow v2 represents this with a `SubscribeNode` and one or more incoming
`PublishEdge`s. The subscription node owns `buffer_size`, `overflow`, and error policy.
`SubscribeNode.policy` holds that mapping with no key contract yet; once this phase
declares its TypedDict, the field's validator is `validator_from_typed_dict`
(`riko/base/_require_guards.py`), kept for that slot (see cache.md § 3).
Multiple incoming publish edges structurally define the publisher set and therefore
completion semantics.

`publish(events)` attaches the complete subscription branch to the producer's execution.
The user does not have to drain ignored branch output to trigger work or cleanup.
Terminal branch values are discarded unless the branch contains an explicit
write/action/subscription-`func`/routing effect.

Calling:

```python
list(events)
```

independently creates a fresh execution. A subscription definition is not a replay
buffer: items published in one execution are observed through the subscription's `func=`
or an explicit effect inside the attached branch, never by draining the subscription
afterwards (decided 2026-10-10; the `TestPipelineSubscriptions` tripwires and the
Cookbook fan-out examples are written against this form). Until R7 lands, those examples
stay plain code blocks beside "Pending." notes: the three `publish`/`subscribe`/`split`
blocks in `docs/COOKBOOK.rst` and the fan-out block in `docs/FAQ.rst`. Their tripwires
are the `PUBSUB_PENDING` strict xfail in `tests/public/test_pipeline.py`
("Pipeline.subscribe()/publish() are not available yet") and `SPLIT_METHOD_PENDING` in
`tests/_workflows.py` ("Pipeline.split() is not available yet"). R7 promotes each block
to a doctest with its observed output and drops the note; `manage lint --rst` flags a
plain Python block that keeps neither marker.

A possible future extension is an explicit, opt-in *retaining* subscription mode that
buffers published items for a later drain. It is not the default, is not part of R7, and
would need its own bounded-retention, ownership, and close semantics before it could
ship.

### 4.2 External subscriptions and publishers

An external `Subscription[T]` is an ordinary seed:

```python
stream = pipeline(subscription)
```

`publish()` accepts either a local subscription Pipeline or an external `Publisher[T]`.

### 4.3 Names and identity

Multiple local subscriptions may share the same display name. Python object identity
distinguishes those definitions.

Serialized workflow declarations may remain concise:

```json
{"name": "events"}
```

A serialized target name resolves every same-name subscription in that compiled
definition unless an explicit serialized id selects one declaration.

## 5. Subscriber scheduling, buffering, and errors

### 5.1 Scheduling

Synchronous subscriber work is inline by default. Parallel subscriber execution is an
explicit execution-concurrency choice, not an implicit property of pub/sub.

Async subscriber orchestration is owned by the private execution. Every subscriber task
is created under the execution's task group; final code permits no detached tasks.
Transitional code may retain tracked tasks only until the execution-owned model lands.

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

`block` is lossless and is the default. For a bounded buffered subscription, `drop`
discards the oldest buffered item and keeps the newest item. There is no implicit lossy
mode.

### 5.3 Error policy

Subscriber errors use only:

```python
Literal["raise", "ignore"]
```

Default is `"raise"`. `"ignore"` means per-item continuation for that subscriber; it
does not turn all branch failures into successful execution.

### 5.4 `func` semantics

A subscriber `func=` may be sync or async. It runs as the item is received/materialized
by the subscription, not later when an ordinary downstream UDF is pulled. Its return
value is discarded:

```python
def archive(item):
    saved.append(item)


subscription = Pipeline.subscribe("archive", func=archive)
```

The received item remains the logical stream value. `func` is retained specifically
because its materialization timing is part of the subscription contract and differs from
an ordinary downstream transform/UDF; callers should not infer transform semantics from
the shared callable-shaped name.

## 6. Multiple publishers and completion

More than one publisher may target one subscription. The subscription completes only
after **all** attached publishers complete.

This is structural in canonical v2: all incoming `PublishEdge`s are known before
execution. Runtime sender-handle ownership derives from that topology; there are no
PENDING/DONE data markers and no explicit integer publisher-count protocol in
user-visible data.

Per-subscription delivery order is guaranteed. When multiple publishers run
concurrently, observed order is actual delivery order; Riko does not invent a global
source ordering.

A publisher completing or failing must not strand subscriber tasks or channels.
Execution cleanup owns final cleanup.

## 7. `split()` is streaming fan-out

The final `split()` contract supersedes the legacy eager finite duplication behavior.

```python
left, right = pipeline.split(2)
```

`split` remains an ordinary registered multi-output module. Its output contract is
positional:

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
- a branch read behind its siblings holds a lossless lag buffer of the items it has
  not read yet (`itertools.tee` semantics), unbounded in the low-level tee;
  `Settings.branch_buffer` (`RIKO_BRANCH_BUFFER`, default 1024) caps it, and a branch
  exceeding the cap fails the run;
- split is lossless and has **no** drop overflow mode;
- per-branch ordering follows upstream order;
- infinite/unbounded upstreams remain streamable;
- reachable positional ports, not `splits`, decide which branches are active; an
  explicit `splits` smaller than the highest reachable `out:N` index is a validation
  error.

**Why a lag buffer, not rendezvous (user decision 2026-11-14).** A split feeding a
sequential fan-in such as `union` must buffer one branch while the fan-in drains the
other; a zero buffer would deadlock that composition. Rendezvous (zero buffer) remains
the rule for subscriptions (§5.2) and for branches driven as execution tasks, which
arrive in a later slice with the execution-scoped task group.

**Tee contract (decided 2026-11-16 (user), R7 Slice A).**

- Registration: every branch is registered before the first upstream advancement;
  `branch()` afterwards, or after close, raises `PipelineStateError`. Reentrant
  upstream advancement raises a clear error; a reentrant read of an already-buffered
  value is allowed. One consumer per branch, with no runtime guard.
- Reads stay demand-driven (no fairness or round-robin); the tee machinery stays even
  with one active output; `Tee` and `AsyncTee` stay separate classes.
- Two error latches. An upstream read error is drainable: branches drain what they
  queued, then re-raise the same exception on every later read until closed; a cleanup
  failure never replaces it. A fatal fan-out error (overflow, copy failure, strict
  cardinality violation) discards every branch buffer at once and re-raises on every
  later read until closed.
- Strict overflow: under strict managed execution an overflow is reported only after
  attempting the upstream read; non-strict may reject a full buffer before reading (a
  possible false positive at EOF). Strict validates splitter cardinality/counts only
  (no per-item provenance ids), applies to managed execution only (direct module
  splitters are non-strict), defaults off, and early close never forces extra upstream
  reads to finish validation (the `strict` knob lands in R7 Slice B, its enforcement in
  Slice C's shared walk; knob in execution-semantics § 6.5).
- Limits: low-level `Tee`/`AsyncTee` default to unlimited and never read global
  settings; managed execution passes its effective `branch_buffer` explicitly at every
  tee site (explicit splitters, implicit shared-port fan-out, and the async splitter
  input tee); direct `riko.modules.split` calls keep the process default (Slice C).
  Unlimited stays `inf`: `RIKO_BRANCH_BUFFER` accepts whole numbers of at least 1 or
  `inf`, `0` keeps being rejected with a warning, and there is no `None` normalization.
- Close: natural exhaustion closes the source promptly and buffered values still drain
  (a cleanup failure is reported after the drain). Closing the last branch while an
  upstream advance is in flight defers the source close to the advancer and returns
  promptly; a blocking sync `next()` that cannot be interrupted gets deferred cleanup
  with failures logged (no public waiting API). A closed branch ends normally (no
  replayed cancellation). Cancelling an async consumer that is only waiting on another
  task's read is branch-local; cancelling the consumer whose task is reading upstream
  interrupts that read and latches a `PipelineError` caused by the cancellation, which
  siblings raise after draining what they queued. Closing a branch early never stops
  its siblings (they keep reading to the end); a caller wanting all-or-nothing closes
  the whole pipeline. Branches
  expose only `close()`/`aclose()`, with no weakref/GC cleanup. A fatal read is
  published (siblings notified) before the source closes, so a blocking close never
  holds drained siblings; the close-failure note therefore lands on the shared
  exception after a sibling may already have raised it (visible on later inspection).
  `Tee._pull` publishes in a `finally` from an empty default read (user
  2026-11-17), so a second interrupt (Ctrl-C) landing inside its `except BaseException`
  arm still releases `_advancer` and sibling waiters never hang; they may then end
  without an error instead (`tests/internal/test_tee.py`
  `TestTee::test_second_interrupt_while_handling_the_first_releases_the_read`).
- Cleanup failures beside a primary error keep the primary type, attach via
  `Exception.add_note`, and log the traceback; there is no tee-specific
  `ExceptionGroup` (the general resource-unwind rule is unchanged). An interrupted
  read's close failure is noted on the interrupt, which each sibling's latched error
  carries as its `__cause__`, so the note is one hop away and prints in tracebacks; it
  is not copied onto the sibling error (`tests/internal/test_tee.py`
  `TestTee::test_interrupted_copy_notes_a_failed_close_on_the_interrupt`).
- Lock shape (fewest locks, least deadlock surface; `AsyncTee` revised 2026-11-23
  (user), replacing its advancement `anyio.Lock`): `AsyncTee` takes no lock at all
  (single-loop deque reads/appends). Reader election is an `_advancer` task id claimed
  with no await between the buffer check and the claim; other readers wait on one
  `anyio.Event` created lazily by the first waiter of the active read (an uncontended
  pull allocates neither lock nor event), and `_publish` publishes the read, clears
  `_advancer`, then sets and drops the event so every woken waiter re-checks its own
  buffer against published state. A same-task read of an empty buffer while advancing
  raises the reentrancy error. The advancer owns a close requested during its read
  (closing it after publishing, like `Tee._advance`), so a cancelled waiter has no
  cleanup obligation (`tests/internal/test_tee.py`
  `TestAsyncTee::test_cancelling_a_waiter_leaves_the_owed_close_to_the_reader`). A
  detached read task owned by the execution (a Web-Streams-style tee, where one branch's
  deadline cannot interrupt a shared read) is to be reconsidered once Slice C's
  execution task group lands; Slice C's design also aims for no riko-owned mutex (user,
  2026-11-23): `Tee`'s lock is then the last one, removable once the driver task
  confines each tee to one thread and hands items to branch workers through queues
  (which also retires its GIL reliance). `Tee` uses one `threading.Lock` plus one
  `Condition` over it, never held across `next(source)`; an advancing flag plus the
  advancer's thread id serialize advancement and detect reentrancy, and every state
  transition (item, EOF, read error, fatal, close) notifies waiters. `Tee` registers
  branches and re-reads the live sibling set after an upstream read without the lock,
  snapshotting dicts with one `tuple()` call and relying on GIL atomicity (CI has no
  free-threaded leg). No new generic synchronization framework.
- Source wrapper (decided 2026-11-16 (user), landed 2026-11-17): `Tee` wraps its source
  in `auto_close` (moved to `riko/base/_iterutils.py`, with `get_sync_closer`/
  `require_value` in `riko/base/_guards.py`), so an undrained, unclosed `Tee` closes its
  source at garbage collection like every other `auto_close` user. Revised 2026-11-17
  (user, stdlib parity with `itertools.tee`): `auto_close`/`aauto_close` warn
  `ResourceWarning` only when a closable is a resource (`has_open_resource`: anything
  with `close`/`aclose` other than a generator or another wrapper), so hand-composed
  `split` feeding an early-stopping pipe no longer warns; a file-backed leak still does
  (`tests/internal/test_stream_helpers.py::TestAutoClose::test_dropping_an_unclosed_wrapper_of_streams_does_not_warn`).
  `auto_close.close()` closes every value, then raises the single failure or an
  `ExceptionGroup` (execution-semantics § cleanup). `auto_close.close()` claims its
  close with one atomic pop of a one-item list, so concurrent closes (a deferred reader
  close racing `Tee.close()`) close once with no extra lock, and `Tee` keeps no close
  flag of its own beyond one lifecycle state (idle, reading, done, closed). Locking
  stays in the few `Tee` methods that already own it; a simplification never adds a
  locked section. As built 2026-11-17, `AsyncTee` matches it: it wraps its source in
  `aauto_close`, which claims its close with the same atomic pop, and shares
  `_TeeState`. Each read of either tee publishes one `TeeRead` built by
  `from_lag`/`from_interrupt`/`from_item` and delivered by `deliver`; both tees re-read
  live siblings after the read, publish before closing, and share the plain helpers
  `require_idle`/`is_lagging`/`log_cleanup_failure` in `riko/base/_iterutils.py` (no
  base class). Branches are `TeeBranch`/`AsyncTeeBranch` classes (a generator branch
  cannot drop its buffer when closed unstarted, or end a wait closed from another
  thread). The advancing branch publishes its own value into its own buffer, so no
  item/marker union is returned (enums need at least three members).

### 7.1 Branch isolation

Split branches are observably isolated: mutation in one branch must not silently corrupt
another branch's logical value.

Whichever branch pulls an item from upstream receives the original value; every other
branch receives a `deepcopy` of the envelope's value (provenance fields shared). The
knob is `pipeline.split(splits=2, *, isolate=True)` and the matching `isolate` conf
option (default `True`) on the `split` module; `isolate=False` shares each value
across branches. Plain one-port fan-out (one source port feeding several stream edges,
no split node) always isolates.

Decided 2026-11-16 (user), R7 Slice A: fan-out is atomic. Every isolated copy is
prepared before any branch buffer receives the item; a copy failure is fatal, raised
as `PipelineError` chained from the copy error and naming the node/branch where known,
and never falls back to sharing.

Similarly:

```python
pipeline.publish(target, isolate=True)
```

isolates publication by default. `isolate=False` is the explicit escape hatch when
sharing is known to be safe and desired.

## 8. Conditional routing

Broadcast and routing are separate. A binary branch sends each item to exactly one
semantic output:

```python
matched, unmatched = pipeline.branch(
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
- callable predicates may be supported through callable-node integration, while
  serialized forms remain data-representable.

Do not call this operation `split`; `split` means broadcast duplication.

## 9. Named routing / partitioning

After binary branch semantics are stable, N-way routing may support:

```python
pipeline.route(field="customer_id", branches=["a", "b", "c"], strategy="hash")
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
- no distributed leases, partition ownership, or worker-assignment system is introduced
  here;
- hash routing is Riko's partitioning primitive: there is no separate
  `key_by`/`partition` option, and key affinity means "same key, same route port", never
  a worker or execution lane.

## 10. Port declaration and validation

The registered node/module contract declares the valid ports. Edges connect declared
ports; edges do not create ports.

For fixed routing, the contract statically declares semantic ports. For configurable
routing/split, node configuration determines the declared port set during
normalization/preparation.

Examples:

```text
split(splits=3)
    -> out, out:1, out:2

branch(...)
    -> out:matched, out:unmatched

route(branches=["a", "b", "c"])
    -> out:a, out:b, out:c
```

An unconnected declared output remains valid. Reachability determines whether runtime
machinery is allocated for it.

Canonical validation rejects:

- edges referencing undeclared ports;
- more than one incoming stream edge to the same target stream port;
- fan-in operand gaps when the owning contract requires contiguous positional inputs;
- topology whose referenced nodes do not exist.

### 10.1 Executor value-addressing (inherited from R4B)

Before this phase the R4B executor keyed its per-node stream table by node id alone
and **failed closed** on any non-default source or selected-output port, and the plan
build refused one source port feeding more than one stream edge
(`Workflow.require_executable()`), because both consumers would have shared one
one-shot iterator.

**As built (R7 slice 1, 2026-11-14).** Value addressing is `(node, port)`-keyed: the
step table maps each `PortKey` to one stream per reader (`ExecutionPlan.get_port_demand`
counts the readers of each port in a run), and `_resolve_node_inputs` pops one per
incoming edge. A port with several readers is teed (`Tee`/`AsyncTee`, isolated copies);
a port nothing reads is closed before any item is pulled. Ordinary modules produce
`out`; a `PreparedSplitter` produces `out`, `out:1`, … from its `splits`. Both guards
are gone: `ExecutionPlan.validate()` instead rejects an edge or workflow output that
reads a port its node doesn't produce (rows
`nondefault-source-output-port`/`split-port-past-its-count`; fan-out runs in
`test_run_fans_out_every_item_to_each_consumer`). Branch/route semantic ports arrive
with their modules. Positional-input gaps are not guarded: `union` reads `others` as an
ordered list, so `in` + `in:2` (legacy `_OTHER2`) executes
(`test_run_accepts_sparse_positional_inputs`); `in:0`/`out:0` are grammar errors in
`parse_port`; per-module fan-in arity belongs to the module port contracts, not this
phase (tripwire `test_build_plan_rejects_undeclared_positional_input`).

**Node vs node-id naming (triage 2026-10-25).** `WorkflowEdge`'s node-id fields are
`source_id`/`target_id` (renamed from the node-sense `source`/`target` as this phase's
first change), and `WorkflowEdge.source_key`/`target_key` give the canonical
`PortKey` (`(node_id, port)`) of each end. The executor's `steps` table is
`PortKey`-keyed. `Endpoint.node` keeps its name: it mirrors the
serialized endpoint's `"node"` key.

## 11. Branch-to-fan-in composition

Do not add a redundant generic `rejoin()` primitive. Branch outputs are ordinary
Pipeline definitions and feed existing fan-in operators.

Conceptually:

```python
matched, unmatched = pipeline.branch(conf=rule)
result = Pipeline.union(matched.transform(...), unmatched.transform(...))
```

Canonical wiring is explicit:

```text
branch.out:matched   -> left_transform.in
branch.out:unmatched -> right_transform.in
left_transform.out   -> union.in
right_transform.out  -> union.in:1
```

Concurrent async fan-in uses `merge`; sequential concatenation remains `union`. The
fluent `Pipeline.union(...)` constructor above is an R7 deliverable
(implementation-sequence R7), as the one-call replacement for the removed
`SyncCollection`.

## 12. Ordering contract

Ordering is defined per primitive:

- `publish`: preserves publication order per subscription;
- multiple concurrent publishers: actual delivery order, no artificial cross-source
  ordering;
- `split`: preserves upstream order independently in each active branch;
- `branch`: preserves relative order in each selected output;
- `route`: preserves relative order per selected branch unless the routing strategy
  explicitly says otherwise;
- `union`: input streams concatenate in port/declaration order (`in`, `in:1`,
  `in:2`, ...);
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
- `join` may require finite/materialized behavior and must declare that execution
  characteristic.

## 14. Relationship to current `send` / `receive`

Current hubs and modules are implementation/migration inputs:

- sync currently uses queue/generator-coroutine mechanics and historical PENDING/DONE
  bookkeeping;
- async uses AnyIO channels but has had incremental-delivery/materialization defects;
- current receiver `func` is the receive-time hook whose materialization timing is
  intentionally distinct from ordinary downstream UDF evaluation;
- current lifecycle can tie cleanup to draining a receiver.

The target rewrite must preserve useful observable behavior while deleting those hidden
ownership mechanisms. In particular:

- no PENDING/DONE records on the final data stream;
- completion is subscription/channel lifecycle, not a user-visible sentinel;
- registration/cleanup belongs to execution-owned handles;
- cleanup does not depend on draining ignored output;
- async delivery is incremental;
- `func` timing and return-discard/pass-through semantics match in sync and async.

Feed-native async parser support is implemented through the common Feed-native parser
mechanism, not a pub/sub-specific wrapper hack.

### 14.1 Migration staging boundary

Before R7, characterization and bug-fix work may keep the existing string-target
`SyncPipe` / `AsyncPipe` send/receive behavior while those shipped surfaces still exist.
Such work must not make those Python modules part of the final contract. R7 removes
`send` / `receive` from the Python module surface when `PublishEdge` / `SubscribeNode`
and object-first `publish` / `subscribe` replace them.

String subscription names remain valid serialized/wire references after the final Python
API becomes object-first; that is subscription identity, not a compatibility module API.
Released persisted v1 shapes are handled only through the bounded v1 migration boundary
where deterministic; no legacy send/receive runtime survives behind Workflow v2.

Transitional fixes should make async send/receive incremental and preserve currently
documented sync/async behavior together, but must not extend DONE/PENDING bookkeeping.
Final R7 replaces that ownership mechanism with `SubscribeNode`/`PublishEdge` topology,
execution-owned sender handles, and receive-time `func=` semantics in both modes.

Do not partially implement final object-first lifecycle semantics inside the
transitional hub.

## 15. Testing strategy

### 15.1 Acceptance contracts

Encode these as behavior-level contracts independent of compatibility API shape:

1. one source broadcasts incrementally to two subscriptions;
2. an async subscriber sees its first item before the publisher finishes reading its
   source;
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

### 15.2 Migration characterization

Keep current characterization tests that pin behavior scheduled to change, but do not
treat them as forward contracts. In particular sentinel visibility and old hub ownership
are migration fixtures; `func` itself is retained, while its final sync/async timing and
pass-through behavior are tested as forward semantics.

### 15.3 Final API/IR contracts

Assert once the object-first surface and Workflow v2 land:

1. `SubscribeNode` + `PublishEdge` canonical topology;
2. sync and async `func=` both execute at subscription receive/materialization time,
   discard return values, and preserve the item;
3. multiple same-name subscription objects remain distinct by identity;
4. external `Subscription` works as a Pipeline source;
5. split uses positional output ports;
6. branch/route use semantic output ports;
7. union/join/merge operands use distinct indexed input ports;
8. one target stream port accepts at most one incoming stream edge;
9. legacy `send` / `receive` Python modules are absent after R7.

## 16. Implementation phases

Historical F-labels remain useful for local work tracking, but the forward dependency
order is owned by [implementation-sequence.md](implementation-sequence.md). In
particular, canonical topology structure lands in R4A, provenance in R5A, and runtime
fanout in R7.

```text
F0  Document current migration topology
F1  Feed-native incremental async send/receive transitional implementation
F2  Binary conditional branch
F3  Named N-way route / partition
F4  Final bounded subscription buffering/error policy
F5  Execution-owned Publisher/Subscription lifecycle + receive-time func semantics
F6  Workflow v2 topology integration / introspection
F7  Branch-to-union/join ergonomic contracts
```

These F labels do not create a parallel implementation sequence.

## 17. Definition of done

1. Public Python pub/sub uses `publish` / `subscribe` objects and the legacy `send` /
   `receive` modules are absent.
2. Canonical Workflow v2 represents subscriptions as `SubscribeNode`s and publication as
   `PublishEdge`s.
3. Publish/subscribe and split are incremental and bounded in both sync and async
   execution.
4. `split()` consumes upstream once, activates only reachable branches, and is lossless.
5. Split uses positional output ports; branch/route use semantic named ports.
6. Fan-in operands use distinct indexed input ports, never edge-list order.
7. Broadcast and routing remain separate concepts.
8. Subscriber buffering, overflow, ordering, errors, and receive-time `func` behavior
   are explicit.
9. Multiple publisher completion is derived from topology/owned sender lifetime, not
   data sentinels.
10. `union` remains sequential fan-in; `join` remains relational fan-in.
11. Branch outputs compose naturally with existing fan-in operators.
12. Cancellation, early close, subscriber failure, and ignored attached branches leak no
    runtime resources.
13. No topology feature requires a distributed runtime.
