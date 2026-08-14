# Authoritative Riko Orchestration Implementation Gameplan

## 1. Mission

Integrate one-shot Riko pipeline executions with cron, webhook servers, Airflow, Prefect,
and Dagster without turning Riko or `riko-cli` into an orchestrator.

This plan owns **deployment-level run boundaries, scheduling integration, and durable
handoffs**. It does not redefine source checkpoints, operation waiting, record-level retry,
or artifact/frame semantics.

Related authoritative plans:

* `feed-monitoring.md` — source checkpoints and finite/repeated monitoring semantics;
* `provider-integrations.md` — provider `OperationHandle` and `wait_operation`;
* `execution-semantics.md` — retry, timeout, cancellation, and error policy inside a Riko
  execution;
* `artifact-conversion.md` — durable artifact references/rendering;
* `tabular-interop.md` — in-memory frame boundaries.

## 2. Architectural rule

An orchestrator schedules and observes Riko runs. Riko executes a pipeline.

```text
orchestrator task or asset
→ construct ExecutionContext
→ execute one Riko pipeline
→ persist explicit outputs/state/artifacts
→ report normalized run result
```

Do not map every streaming module to an orchestrator task. A stream crosses a process or
scheduler boundary only through explicit durable materialization such as an artifact,
database table, object, or RDP state boundary.

## 3. Common run adapter

```python
@dataclass(frozen=True, slots=True, kw_only=True)
class PipelineRunRequest:
    pipeline: str
    parameters: Mapping[str, JsonValue]
    run_id: str
    deadline: datetime | None = None
    idempotency_key: str | None = None


@dataclass(frozen=True, slots=True, kw_only=True)
class PipelineRunResult:
    status: Literal["succeeded", "failed", "cancelled", "partial"]
    artifacts: tuple[ArtifactRef, ...]
    state: JsonValue | None
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
* leaves recurrence to cron or the host platform.

Do not add an in-process forever scheduler to the base CLI.

## 5. Webhook-triggered runs

A webhook adapter:

1. authenticates and validates the request;
2. normalizes event ID/idempotency key;
3. persists or queues the event according to deployment policy;
4. starts a bounded pipeline run or returns an accepted response;
5. records the resulting run ID.

Provider signature verification and `EventEnvelope` normalization belong to
`provider-integrations.md`. The orchestrator owns **when/how a normalized event becomes a
run**.

The request handler must not execute an unbounded feed monitor or agent network inline.

## 6. Feed monitoring integration

Do not define another checkpoint protocol here.

`feed-monitoring.md` owns:

```text
SourceCheckpoint
CheckpointStore
observation state
dedupe / changed
bootstrap behavior
checkpoint commit ordering
periodic in-process monitor semantics
```

Orchestration only decides **when to invoke the finite monitoring operation** and which
persistent store/configuration the deployment supplies.

Typical deployment:

```text
cron / Prefect / Airflow / Dagster sensor
→ finite source observation using feed-monitoring contract
→ downstream durable handoff
→ checkpoint commit
→ run exits
→ orchestrator schedules the next run
```

An application-owned long-lived monitor may also use `feed-monitoring.md` directly without
changing checkpoint semantics.

## 7. Long-running provider operations

Do not use orchestration retries or sensors as a second definition of provider operation
waiting.

When a Riko action returns `OperationHandle`, `provider-integrations.md` owns the
`wait_operation` interval/event/hybrid semantics.

An orchestrator may instead choose to persist the handle and resume/check it in a later run,
but it must preserve the same provider terminal-state and correlation semantics rather than
inventing an incompatible waiter.

## 8. Airflow adapter

Default integration: one `PythonOperator` or TaskFlow task per Riko run.

Split extract, transform, and delivery into separate Airflow tasks only when each boundary
writes a durable artifact/table/object. Never pass a stream or large record collection
through XCom.

Use artifact references and lineage IDs instead. Airflow connections may resolve named Riko
credential references but must not be copied into task output.

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
artifact references, tables, Arrow batches, or files through the authoritative artifact and
tabular contracts.

Asset partitions map to explicit pipeline parameters/checkpoint namespaces rather than
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

* sources to restore committed checkpoint state through their authoritative state contract;
* sinks/actions to expose idempotency behavior;
* durable outputs to commit before their associated state advances;
* non-idempotent actions to follow approval/manual policy where applicable;
* partial artifacts to be marked incomplete rather than silently reused.

Only one layer should retry a given failure domain.

## 13. Events and observability

Normalize run-level events such as:

```text
run start/finish
pipe summary
artifact publication
checkpoint commit reference
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
O0  common run service + fake adapter
O1  cron/CLI examples
O2  webhook-to-run adapter
O3  feed-monitoring deployment examples using shared checkpoints
O4  provider-operation deployment examples using OperationHandle
O5  Airflow adapter
O6  Prefect adapter
O7  Dagster op/asset/partition/IOManager adapters
O8  cross-adapter contract tests and deployment templates
```

## 16. Definition of done

1. No lazy stream crosses an orchestrator boundary implicitly.
2. Every multi-task split occurs at a durable handoff.
3. Cancellation/deadlines reach the Riko execution.
4. Run-level retries are distinguished from pipe/provider retries.
5. Webhook ingress consumes normalized verified events.
6. Feed monitoring reuses, rather than redefines, checkpoint/state contracts.
7. Provider jobs reuse, rather than redefine, `OperationHandle`/wait semantics.
8. Orchestrator metadata uses artifact/frame references rather than large hidden payloads.
9. The base CLI remains a run adapter, not a scheduler daemon.
