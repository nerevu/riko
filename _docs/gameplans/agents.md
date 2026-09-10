# Agent workflows gameplan

## 1. Mission

Support agent-style iterative/event-driven workflows by reusing Riko's immutable
`Pipeline` definition, graph tooling, pub/sub protocols, execution bridge, resources, and
state model.

The target architecture deliberately does **not** introduce `AgentGraph`, `AgentNetwork`, a
second DAG format, a universal DAG executor, or an agent-specific checkpoint store.

Agent workflows differ from ordinary finite transforms primarily in:

* event ingress/egress;
* explicit pub/sub branches;
* iterative state/termination;
* long-lived application orchestration;
* side effects and approvals.

Those differences are expressed using existing/common Riko abstractions rather than a
parallel execution stack.

Authoritative supporting plans:

* `execution-semantics.md` — `Pipeline`, `Context`, private sync/async executions,
  `Publisher`/`Subscription`, `FeedState`, `StateStore`, identity/idempotency, and `loop`;
* `fanout-topology.md` — explicit `publish` / `subscribe` / `split` topology;
* `connectors.md` — external event transports and credential/session resources;
* `provider-integrations.md` — side-effect/provider operation contracts;
* `orchestration.md` — schedules, workers, and durable run boundaries.

## 2. Core rule: agents reuse Pipeline

A `Pipeline` is an immutable DAG definition. Agent-oriented workflows compose ordinary
Pipeline nodes and branches:

```python
incoming = Pipeline.subscribe("incoming")
alerts = Pipeline.subscribe("alerts")

flow = Pipeline(source=incoming).map(normalize).map(classify).publish(alerts)
```

No separate graph definition is required. Shared graph construction, validation,
serialization, visualization, subgraph queries, and planning naturally apply because the
agent workflow **is** a Pipeline definition.

The underlying Pipeline graph remains acyclic. Iteration is represented by the existing
`loop` construct, not a graph cycle.

## 3. Graph infrastructure

The useful generic graph refactor from earlier exploration remains valid, but it serves one
Pipeline architecture rather than two public graph systems.

A small internal DAG utility may own:

```text
nodes / edges
roots / sinks
predecessors / successors
ancestors / descendants
topological ordering
cycle/self-loop validation
subgraph/pruning
visualization
```

Existing helpers such as `utils.gen_graph()`, `topological_sort()`, serialized pipe parsing,
and visualization can progressively converge on that utility.

Do not put execution behavior into the generic DAG helper. Module configuration, embedded
loops, ports, stream iteration, resources, fan-out, stateful-owner resolution, and
sync/async adaptation remain Pipeline/compiler/execution concerns.

## 4. Public event protocols

Agent/event integrations reuse the common protocols:

```python
class Publisher[T](Protocol): ...


class Subscription[T](Protocol): ...


class Channel[T](Publisher[T], Subscription[T], Protocol): ...
```

An external event source implementing `Subscription[T]` is an ordinary Pipeline source:

```python
flow = Pipeline(source=subscription)
```

An external event destination implementing `Publisher[T]` can be a publish target:

```python
flow = flow.publish(publisher)
```

Local branches use object-first subscription declarations:

```python
audit = Pipeline.subscribe("audit")
flow = flow.publish(audit)
```

Low-level compatibility modules may remain named `send` / `receive`, but new agent-facing
Python documentation uses `publish`, `subscribe`, `publisher`, and `subscription`.

## 5. Fan-out and branch lifecycle

Agent routing does not imply that every shared Pipeline ancestor broadcasts automatically.
Fan-out is explicit:

```python
left, right = flow.split(2)
```

or:

```python
flow = flow.publish(events)
```

Local published branches are attached to and owned by the execution. The caller does not
need to drain a subscriber merely to make cleanup occur. Terminal values on an attached
branch are discarded unless the branch contains an explicit sink/on_receive/routing effect.

`split()` is lossless streaming fan-out with bounded per-branch buffering; unused outputs
remain inactive. `publish()` isolates branches by default (`isolate=True`) with an explicit
`isolate=False` escape hatch.

Per-subscription item order is preserved; cross-subscription execution/completion order is
unspecified. Multiple publishers may target one subscription; that subscription completes
after all attached publishers complete.

## 6. External event adapters

Webhook receivers, feed monitors, ZeroMQ, RabbitMQ, Service Bus, Event Grid, mail inboxes,
and similar transports are connector/provider concerns. They adapt external protocols to
`Publisher` / `Subscription`; they do not live in graph-node attributes or create their own
agent executor.

Every adapter declares its delivery semantics, for example:

```text
best_effort
at_most_once
at_least_once
```

Exactly-once must not be claimed generically. When duplicate delivery is possible,
side-effecting nodes rely on the common execution-derived idempotency identity and the
transport's genuine acknowledgement/idempotency capabilities.

Protocol sessions are declared `Context` resources and are execution-owned session values.
They are not opened per item unless the protocol genuinely requires it.

## 7. Iteration uses `loop`

Agent-style reasoning/tool iteration extends the existing Riko `loop` rather than adding
cycles to the Pipeline DAG.

Conceptual example:

```python
flow = Pipeline(...).loop(embed=step, until=done, max_iterations=20, id="research-loop")
```

Iterative semantics:

1. the current state enters one iteration;
2. the embedded pipeline executes;
3. exactly one embedded result becomes the next state;
4. zero or multiple results raise `LoopStateError`;
5. `until(state, iteration)` is evaluated against the latest state;
6. if false, the next iteration begins.

The existing non-iterative loop mode may retain its current zero/many behavior. The
single-result requirement applies to the new iterative-state mode.

## 8. Termination

```python
max_iterations: int | None = None
```

`until` is checked before the first iteration (while-loop semantics). Initially `until` is
sync-only:

```python
def until(state: StateT, iteration: int) -> bool: ...
```

`iteration` is zero-based.

Rules:

* default termination preserves the current one-run loop behavior;
* `max_iterations` without an explicit `until` means fixed-count iteration;
* an explicit `until` that remains false at the limit raises `LoopIterationError`;
* `None` means no numeric bound, subject to the owning application's cancellation/deadline
  policy.

Long-lived agent applications should still configure practical budgets/deadlines. This
contract does not authorize unbounded model/provider retries.

## 9. Loop state and checkpointing

Agent iteration reuses:

```python
@dataclass(frozen=True)
class LoopState[T]:
    value: T
    iteration: int
```

as a checkpoint payload inside the common:

```python
FeedState[LoopState[T]]
```

There is no automatic loop checkpointing. Users place an explicit boundary where recovery
is meaningful:

```python
step = step.checkpoint(id="after-tool-result")
```

A checkpoint crossed after a successful iteration commits before the next iteration begins.
Resume restores the application state and iteration counter and continues **after** the
successfully crossed boundary. `max_iterations` remains a total bound across resumed
execution rather than resetting after a restart.

## 10. StateStore reuse

Agents use the same public store protocols as all other resumable Riko constructs:

```python
StateStore
AsyncStateStore
StateStoreLike
StateKey[T]
StateRecord[T]
FeedState[T]
```

Do not define `AgentStateStore` or `CheckpointStore`.

The enclosing iterative `loop` is the stateful owner for loop checkpoints. A checkpoint in
a reusable fragment resolves to the nearest enclosing stateful owner when the concrete graph
is compiled. Ambiguous multi-frontier recovery topologies are rejected.

CAS conflicts raise `CheckpointConflictError`; the execution does not silently reload and
rerun an agent iteration.

## 11. Stable identity

An explicit loop `id=` is required only where durable logical identity must survive a
structural graph revision that would otherwise change the generated node id.

The stateful fingerprint covers the full resumable loop scope:

```text
embedded Pipeline semantics
checkpoint placement
termination policy
relevant callable versions
statically declared reachable resource definitions
```

Unrelated downstream graph structure and the particular configured StateStore
implementation are excluded.

Per-item/iteration idempotency uses the common identity dimensions:

```text
(node_id, fingerprint, item_key, generation, iteration)
```

Generation remains deterministic/stable across retries; it is never replaced by a random
retry UUID.

## 12. Tool/provider calls

Agent tool calls are ordinary Pipeline side effects or provider capability executions.
They therefore use the common rules:

* side-effecting modules declare idempotency support;
* execution derives/injects the idempotency key centrally;
* a retryable/resumable workflow fails validation when a destination cannot honor
  idempotency unless the node explicitly opts out with `require_idempotency=False`;
* provider `OperationHandle` waiting remains owned by `provider-integrations.md`;
* approval/policy remains provider/MCP/application policy rather than a loop feature.

## 13. Observation and metadata

Agent/tool results may return `FeedResult` metadata/state like other Riko sources. Per-item
provenance remains private in `_FeedItem`; parsers/agent callables receive ordinary values.

Ordinary 1-to-1 transforms preserve truthful item identity/generation. Fan-out and combine
operations derive/combine identity according to the common execution semantics. An agent
workflow does not define a second event-identity system.

## 14. Concurrency and lifecycle

The same immutable Pipeline can run under sync or async execution. Async event sources,
subscriptions, provider calls, and resources use the common execution bridge and
execution-owned structured lifecycle.

Do not start a private event loop per agent or event. Sync execution may own one lazily
created portal when async-only components are encountered; async execution adapts unknown
sync extension work to workers unless explicitly inline-safe.

Cancellation/deadline propagates through active subscriptions, provider calls, loop
iterations, and execution-owned resources.

## 15. Serialization

Agent-oriented workflows serialize as ordinary Pipeline definitions plus explicit loop,
pub/sub, Context-reference, and provider configuration. Do not create a second `agents` /
`links` graph schema solely for symmetry.

Serialized subscriptions may use concise names; same-name target resolution follows the
fan-out contract. Serialized callable/key references use symbolic Context references rather
than attempting to serialize arbitrary Python callables.

## 16. Visualization and inspection

Because agents reuse Pipeline, the same graph renderer and graph queries apply:

```python
flow.dag.ancestors(node)
flow.dag.descendants(node)
flow.dag.roots
flow.dag.sinks
```

(if/when those public inspection conveniences are exposed).

Visualization should distinguish:

* normal data edges;
* explicit publish/subscription branches;
* embedded loop scope;
* checkpoint boundaries;
* side-effect/provider nodes;
* external sources/sinks.

It must not draw loop iteration as a cyclic DAG edge when the compiled Pipeline graph is
acyclic.

## 17. Deployment boundary

A long-lived service may keep consuming an external subscription or polling source.
Alternatively an orchestrator may invoke finite agent/loop work as separate runs at durable
boundaries. `orchestration.md` owns scheduling and worker restart policy.

A webhook request handler should validate/persist/queue the incoming event according to its
transport policy and trigger bounded work; it should not synchronously execute an unbounded
agent workflow in the request thread.

## 18. Graph refactor work

Generic graph infrastructure remains useful and should be extracted incrementally from the
existing topsort/compile utilities. Candidate internal API:

```python
@dataclass(frozen=True, slots=True)
class Dag[T]:
    nodes: tuple[T, ...]
    edges: tuple[tuple[T, T], ...]

    @property
    def order(self) -> tuple[T, ...]: ...
    def predecessors(self, node: T) -> tuple[T, ...]: ...
    def successors(self, node: T) -> tuple[T, ...]: ...
    def ancestors(self, node: T) -> frozenset[T]: ...
    def descendants(self, node: T) -> frozenset[T]: ...
```

This is an internal/shared structural utility, not `AgentGraph` and not an executor.
Pipeline compilation remains responsible for module/resource/state semantics.

## 19. Testing strategy

Required tests include:

1. Pipeline DAG stays acyclic when iterative loop semantics are used;
2. iterative loop accepts exactly one embedded result and rejects zero/multiple;
3. `until` is checked before the first iteration and receives zero-based iteration;
4. fixed-count `max_iterations` behavior;
5. explicit-until exhaustion raises `LoopIterationError`;
6. checkpoint commit occurs only after successful boundary/iteration;
7. resumed loop restores both value and iteration count;
8. `CheckpointConflictError` propagates without automatic rerun;
9. local published branches are execution-owned and need no manual drain;
10. external `Subscription` works as an ordinary source;
11. multiple publishers complete one subscription only after all publishers finish;
12. side-effecting agent/tool nodes reuse stable idempotency identity across retry;
13. sync/async execution of the same definition has equivalent logical semantics;
14. cancellation closes subscriptions/resources/provider operations deterministically;
15. serialization/visualization preserves loop and pub/sub structure without a second graph
    schema.

## 20. Phases

```text
A0  generic internal DAG utility/refactor
A1  Pipeline pub/sub protocols and execution-owned branch lifecycle
A2  external Publisher/Subscription connector adapters
A3  iterative loop state/termination semantics
A4  loop + FeedState/StateStore checkpoint/resume
A5  provider/tool idempotency and approval integration
A6  visualization/inspection of loop + pub/sub topology
A7  orchestrated and long-lived deployment examples
```

## 21. Definition of done

1. Agent workflows are ordinary immutable Pipeline definitions; there is no `AgentGraph`.
2. Pipeline DAGs remain acyclic; `loop` owns iteration.
3. Event ingress/egress reuse `Publisher` / `Subscription` / `Channel`.
4. Agent state/checkpoints reuse `FeedState` / `StateStore`; there is no agent checkpoint
   store.
5. Loop checkpointing is explicit and resumable with stable iteration count.
6. Side effects reuse common idempotency/provenance semantics.
7. Local fan-out branches are explicit and execution-owned.
8. Sync and async modes share one definition and logical behavior.
9. External transports remain connector/provider adapters, not graph runtime machinery.
10. Scheduling/restart policy remains outside the agent core.
