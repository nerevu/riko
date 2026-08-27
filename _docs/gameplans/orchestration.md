# Orchestration gameplan

## 1. Mission

Integrate one-shot Riko pipeline executions with cron, webhook servers, Airflow, Prefect,
and Dagster without turning Riko or `riko-cli` into an orchestrator.

This plan owns **deployment-level run boundaries, scheduling integration, and durable
handoffs**. It does not redefine source state/checkpoints, operation waiting, record-level
retry, or artifact/frame semantics.

Related authoritative plans:

* `execution-semantics.md` — `Pipeline`, `Context`, `FeedState`, `StateStore`, checkpoints,
  retry, timeout, cancellation, idempotency, and error policy inside a Riko execution;
* `feed-monitoring.md` — finite/repeated monitoring semantics and monitoring state payloads;
* `provider-integrations.md` — provider `OperationHandle` and `wait_operation`;
* `artifact-conversion.md` — durable artifact references/rendering;
* `tabular-interop.md` — in-memory frame boundaries.

## 2. Architectural rule

An orchestrator schedules and observes Riko runs. Riko executes a pipeline.

```text
orchestrator task or asset
→ resolve immutable Pipeline + Context definitions
→ iter(pipeline) / aiter(pipeline) creates a private execution
→ persist explicit outputs/state/artifacts
→ report normalized run result
```

There is no public `ExecutionContext` construction step. `Context` is the public immutable
environment/resource definition; private `SyncExecution` / `AsyncExecution` objects own live
resources and runtime state.

Do not map every streaming module to an orchestrator task. A stream crosses a process or
scheduler boundary only through explicit durable materialization such as an artifact,
database table, object, or state boundary.

## 3. Common run adapter

Canonical Python uses an explicit pipeline reference type:

```python
@dataclass(frozen=True, slots=True, kw_only=True)
class PipelineRunRequest:
    pipeline: PipelineRef
    parameters: Mapping[str, JsonValue]
    run_id: str
    deadline: datetime | None = None
    idempotency_key: str | None = None


request = PipelineRunRequest(
    pipeline=PipelineRef("daily-report"),
    parameters={},
    run_id="run-123",
)
```

Serialized configuration may accept a concise pipeline string, but that shorthand is
resolved by the compiler/configuration boundary. Runtime code does not guess whether an
arbitrary bare string is a pipeline name, module, path, or other reference.

```python
@dataclass(frozen=True, slots=True, kw_only=True)
class PipelineRunResult:
    status: Literal["succeeded", "failed", "cancelled", "partial"]
    artifacts: tuple[ArtifactRef, ...]
    state: FeedState | None
    metrics: Mapping[str, JsonValue]
```

Airflow, Prefect, Dagster, webhook workers, and CLI commands should call the same execution
service rather than each building a separate Riko runner.

## 4. Cron and standalone execution

A standalone script or `riko run` command is the baseline deployment.

The process:

* executes one bounded run/request;
* exits with stable machine-readable status;
* emits run metadata when requested;
* leaves recurrence to cron or the host platform unless the application explicitly owns a
  `Pipeline.poll(...)` long-lived process.

Do not add an in-process forever scheduler to the base CLI.

## 5. Webhook-triggered runs

A webhook adapter:

1. authenticates and validates the request;
2. normalizes event ID/idempotency key;
3. persists or queues the event according to deployment policy;
4. creates a `PipelineRunRequest` and starts a bounded pipeline run or returns an accepted
   response;
5. records the resulting run ID.

Provider signature verification and `EventEnvelope` normalization belong to
`provider-integrations.md`. The orchestrator owns **when/how a normalized event becomes a
run**.

The request handler must not execute an unbounded feed monitor or agent network inline.

## 6. Feed monitoring integration

Do not define another checkpoint/state protocol here.

`execution-semantics.md` owns:

```text
FeedState / StateRecord / StateKey
StateStore / AsyncStateStore
CAS mutation
checkpoint boundaries and stateful owners
identity / generation
```

`feed-monitoring.md` owns:

```text
observation cadence
bootstrap/backfill behavior
dedupe / changed / anomaly policy
monitoring-specific state payload meaning
```

Orchestration decides **when to invoke the finite monitoring operation** and which
`Context` / configured persistent store the deployment supplies.

Typical deployment:

```text
cron / Prefect / Airflow / Dagster sensor
→ finite source observation
→ downstream durable handoff
→ StateStore CAS commit at the valid owner boundary
→ run exits
→ orchestrator schedules the next run
```

An application-owned long-lived monitor may use `Pipeline.poll(...)` directly without
changing the same state semantics.

## 7. Long-running provider operations

Do not use orchestration retries or sensors as a second definition of provider operation
waiting.

When a Riko action returns `OperationHandle`, `provider-integrations.md` owns the
`wait_operation` interval/event/hybrid semantics.

An orchestrator may instead choose to persist the handle and resume/check it in a later run,
but it must preserve the same provider terminal-state and correlation semantics rather than
inventing an incompatible waiter. Persisted handles/state use the common `StateStore` when
modeled as Riko resumable state.

## 8. Airflow adapter

Default integration: one `PythonOperator` or TaskFlow task per `PipelineRunRequest`.

Split extract, transform, and delivery into separate Airflow tasks only when each boundary
writes a durable artifact/table/object. Never pass a stream or large record collection
through XCom.

Use artifact references and lineage IDs instead. Airflow connections may supply/resolve
named Riko `Context` resources but credentials must not be copied into task output.

## 9. Prefect adapter

Expose a task wrapper and result block.

Prefect may retry the **whole task/run** according to deployment policy. Record/source-level
retry inside the Riko execution remains governed by `execution-semantics.md`.

Prefect artifacts contain summaries and artifact references, not full streams.

## 10. Dagster adapter

Support:

```text
Riko run as @op
Riko durable output as @asset
```

An asset represents a durable data product, not every Riko module. IOManagers exchange
artifact references, tables, negotiated batch values, or files through the authoritative
artifact and tabular contracts.

Asset partitions map to explicit pipeline parameters/stateful-owner identity rather than
implicitly changing source state.

## 11. dbt coordination

`riko-dbt` supplies a reusable dbt execution service. Orchestrators decide when to invoke it.
A typical durable flow is:

```text
Riko load artifact/table
→ dbt run
→ Riko read/deliver artifact/table
```

Do not call dbt in the middle of a lazy record stream.

## 12. Run-level retries, idempotency, and state

Distinguish orchestration retry from Riko operation retry:

```text
execution-semantics RetryPolicy
    retries one configured source/pipe/write operation inside a run

orchestrator retry
    reruns the entire PipelineRunRequest
```

Whole-run retries require:

* stateful sources/owners to restore only successfully committed `StateStore` state;
* sinks/actions to honor the common execution-derived idempotency contract where their
  destination permits it;
* durable outputs to commit before associated source/recovery state advances;
* non-idempotent actions to fail retryable/resumable validation unless explicitly opted out
  or governed by an appropriate manual/policy boundary;
* partial artifacts to be marked incomplete rather than silently reused.

Only one layer should retry a given failure domain. A `CheckpointConflictError` propagates;
the Riko state-store adapter does not automatically reload/rerun a conflicting operation.

## 13. Events and observability

Normalize run-level events such as:

```text
run start/finish
pipeline summary
artifact publication
state/checkpoint commit reference
warning/failure
cancellation/deadline
```

Adapters translate these to Airflow logs, Prefect events, Dagster metadata, or JSON logging
without changing semantic meaning.

Detailed pipe/retry/checkpoint event schemas remain owned by their underlying contracts.

## 14. Package layout

```text
riko_orchestration/
    service.py
    types.py
    webhooks.py
    adapters/
        cron.py
        airflow.py
        prefect.py
        dagster.py
    cli.py
```

Orchestrator dependencies are optional extras and lazily imported.

## 15. Phases

```text
O0  PipelineRef/PipelineRunRequest common run service + fake adapter
O1  cron/CLI examples
O2  webhook-to-run adapter
O3  feed-monitoring deployment examples using FeedState/StateStore
O4  provider-operation deployment examples using OperationHandle
O5  Airflow adapter
O6  Prefect adapter
O7  Dagster op/asset/partition/IOManager adapters
O8  cross-adapter contract tests and deployment templates
```

## 16. Definition of done

1. No lazy stream crosses an orchestrator boundary implicitly.
2. Every multi-task split occurs at a durable handoff.
3. Public configuration uses `Context`; private execution owns runtime handles.
4. Canonical Python run requests use `PipelineRef`, with serialized string shorthand
   resolved before runtime.
5. Cancellation/deadlines reach the Riko execution.
6. Run-level retries are distinguished from pipe/provider retries.
7. Webhook ingress consumes normalized verified events.
8. Feed monitoring reuses, rather than redefines, `FeedState`/`StateStore` semantics.
9. Provider jobs reuse, rather than redefine, `OperationHandle`/wait semantics.
10. Orchestrator metadata uses artifact/frame references rather than large hidden payloads.
11. The base CLI remains a run adapter, not a scheduler daemon.
