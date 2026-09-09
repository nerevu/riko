# Execution events gameplan

## 1. Mission

Define the minimal execution-owned event transport that Core runtime features use for out-of-band
results, diagnostics, and lifecycle observations without creating feature-specific callback systems.

This plan owns:

- the `Event`/`EventSink` transport contract;
- execution-local dispatch/lifetime rules;
- sync/async delivery adaptation rules;
- the no-op default behavior;
- the boundary between Core event production and optional observability consumers.

Feature owners define their own semantic payloads:

- `cache.md` — cache hit/miss/bypass/invalidation diagnostics;
- `effects.md` — `WriteResult` / `ActionResult`;
- `execution-semantics.md` — execution/resource/state/retry lifecycle payloads where needed;
- `fanout-topology.md` — publish/subscription lifecycle payloads.

`extensibility.md` owns OpenTelemetry and other ecosystem observability integrations.
Implementation ordering is owned by `implementation-sequence.md`; the minimal transport lands with
R4B private execution.

## 2. Public execution setting

An immutable Pipeline definition may select an event sink through execution configuration:

```python
flow = flow.with_execution(event_sink=events)
```

The sink is execution configuration, not graph data and not a serialized Workflow v2 node.

No sink means a no-op sink. Features may emit events unconditionally without requiring callers to
configure observability.

## 3. Contract

The exact final typing may be refined during implementation, but the semantic shape is:

```python
class Event(Protocol): ...


class EventSink(Protocol):
    def emit(self, event: Event) -> None: ...
```

Async-capable implementations may provide an async delivery path or be adapted once by the private
execution. Core feature code does not probe sink methods repeatedly or create event-specific
workers/portals.

The important invariant is one execution event channel, not the precise initial method spelling.

## 4. Ownership and lifetime

Each private `SyncExecution`/`AsyncExecution` owns its event-dispatch relationship for exactly that
execution.

Rules:

- event dispatch never outlives the execution that produced it;
- event sinks do not own Pipeline resources/task groups/portals;
- execution adaptation uses the shared R4B bridge/worker machinery;
- a feature must not create a private callback thread/task merely to report events;
- event delivery must not require draining the Pipeline's data output;
- one Pipeline definition may be executed repeatedly with different sinks.

## 5. Data versus events

Events are out-of-band execution information. They never replace ordinary stream values.

Examples:

```text
WriteNode
    records -> records
    completion -> WriteResult event

ActionNode
    records -> records
    completion -> ActionResult event

CacheNode backend failure
    records continue through bypass
    diagnostic -> cache event
```

Do not smuggle control/lifecycle values into the user stream. In particular pub/sub completion uses
owned channel/sender lifetime, not DONE/PENDING data markers.

## 6. Failure policy

Event reporting is not allowed to silently redefine the success of the dataflow.

Initial rule:

- the no-op sink cannot fail;
- user/configured sink failure is surfaced according to one documented execution policy rather than
  being inconsistently swallowed by individual features;
- feature code does not catch and reinterpret event-sink failure itself;
- security/redaction policy applies before sensitive payload data reaches optional observability
  consumers.

Whether configured observability failure is fatal or can be explicitly best-effort is an execution
policy decision; do not give each event type a separate answer.

## 7. Event taxonomy

Core may use typed events/results for:

```text
execution start/finish
node start/finish
resource open/close
cache hit/miss/bypass/invalidate
write/action completion
publish/subscription lifecycle
checkpoint/state CAS outcome
retry/disposition
cancellation/deadline
artifact publication
aggregate counters
```

Not every item needs a public per-item event. Aggregate counters are preferred when they express the
same observability at lower overhead.

Payload logging is opt-in and bounded. Secrets, credential material, tokens, and other sensitive
values are redacted by the owning feature/adapter before publication.

## 8. Optional consumers

CLI, GUI, tests, OpenTelemetry, structured logging, and service wrappers consume `EventSink`; they do
not become new runtime owners.

An OpenTelemetry adapter may translate execution/node/effect/cache/state events into spans, metrics,
or logs. OpenTelemetry remains optional and must not be required for Core execution.

## 9. Testing

Required contracts:

1. no configured sink behaves as no-op without feature branching;
2. events from one execution never leak into another execution of the same Pipeline;
3. sync Pipeline can use async-capable sink through the common bridge when supported;
4. async Pipeline does not block the event loop on an unknown blocking sink without worker
   adaptation;
5. WriteResult/ActionResult are out-of-band and records remain unchanged;
6. cache diagnostic emission does not require a separate callback API;
7. pub/sub lifecycle emits no user-stream control records;
8. event sink cleanup/cancellation follows execution lifetime;
9. sensitive adapter data is redacted before emission;
10. optional consumers can be added without changing feature/runtime semantics.

## 10. Definition of done

Every Core runtime feature reports optional out-of-band information through one execution-owned
EventSink contract, no feature invents a parallel observer lifecycle, and optional observability
packages can consume events without becoming runtime dependencies.
