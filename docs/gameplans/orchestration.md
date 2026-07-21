# Authoritative Riko Orchestration Implementation Gameplan

## 1. Mission

Integrate one-shot Riko pipeline executions with cron, webhook servers, Airflow, Prefect,
and Dagster without turning Riko or `riko-cli` into an orchestrator.

This plan promotes Shelf milestones 13.2, 13.3, and 15.

## 2. Architectural rule

An orchestrator schedules and observes Riko runs. Riko executes a pipeline.

```text
orchestrator task or asset
→ construct ExecutionContext
→ execute one Riko pipeline
→ persist explicit outputs/state/artifacts
→ report normalized run result
```

Do not map every streaming module to an orchestrator task. A stream cannot cross process
or scheduler boundaries without explicit materialization. Split a pipeline only at a
named artifact, database table, object, RDP state boundary, or other durable handoff.

## 3. Common adapter service

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
    status: Literal["succeeded", "failed", "cancelled"]
    artifacts: tuple[ArtifactRef, ...]
    state: JsonValue | None
    metrics: Mapping[str, JsonValue]
```

Airflow, Prefect, Dagster, webhooks, and CLI commands call the same service.

## 4. Cron and standalone execution

A standalone script or `riko run` command is the baseline deployment. The process exits
with stable status codes, writes machine-readable run metadata when requested, and leaves
retry and schedule policy to cron or the host platform.

Do not add an in-process forever scheduler to the base CLI.

## 5. Webhook-triggered runs

A webhook adapter:

1. authenticates and validates the request;
2. normalizes an event ID and idempotency key;
3. persists or queues the event according to deployment policy;
4. starts a bounded pipeline run or returns an accepted response;
5. records the resulting run ID.

The HTTP request handler must not execute an unbounded feed monitor or agent network.
Replay protection and duplicate-event behavior are explicit.

## 6. Feed monitoring

Continuous RSS/Atom monitoring is an orchestration source, not a restartable Riko source
implemented with an in-memory `while True` loop.

```python
class FeedCheckpointStore(Protocol):
    async def load(self, feed_id: str) -> FeedCheckpoint | None: ...
    async def save(self, feed_id: str, value: FeedCheckpoint) -> None: ...
```

A monitor performs a finite poll, emits new events, commits checkpoint state after
successful handoff, and waits with cancellation-aware backoff. Deployment may use an
agent worker, scheduled run, or orchestrator sensor.

## 7. Airflow adapter

Default integration: one `PythonOperator` or TaskFlow task per Riko run.

Split extract, transform, and delivery into separate Airflow tasks only when each boundary
writes a durable artifact. Never pass a stream or large record collection through XCom.
Use artifact references and record lineage IDs instead.

Map Airflow cancellation and deadlines into `ExecutionContext`. Airflow connections may
resolve named Riko credential references but must not be copied into task output.

## 8. Prefect adapter

Expose a task wrapper and result block. Retries occur at the task/run boundary unless the
pipeline itself has operation-specific retry policy. Prefect artifacts contain summaries
and artifact references, not full streams.

## 9. Dagster adapter

Support two modes:

```text
Riko run as @op
Riko durable output as @asset
```

An asset represents a durable data product, not every Riko module. IOManagers exchange
artifact references, tables, Arrow batches, or files. Asset partitions map to explicit
pipeline parameters and checkpoint keys.

## 10. dbt coordination

dbt execution is a reusable service supplied by `riko-dbt`. Orchestrators decide when to
invoke it. A typical durable flow is:

```text
Riko load artifact/table
→ dbt run
→ Riko read/deliver artifact/table
```

Do not call dbt in the middle of a lazy record stream.

## 11. Retries, idempotency, and state

Orchestrator retries may rerun the entire pipeline. Therefore:

* sources restore committed state;
* sinks support idempotency keys or document duplicate behavior;
* state is committed only after the durable output boundary succeeds;
* non-idempotent operations may require manual approval before retry;
* partial artifacts are marked incomplete and are not silently reused.

## 12. Events and observability

Normalize run-start, stage-start, stage-finish, artifact, checkpoint, warning, and failure
events. Adapters translate them to Airflow logs, Prefect events, Dagster metadata, or
ordinary JSON logs without changing event meaning.

## 13. Package and plugin layout

```text
riko_orchestration/
    service.py
    types.py
    webhooks.py
    feeds.py
    adapters/
        airflow.py
        prefect.py
        dagster.py
    cli.py
```

Orchestrator dependencies are extras and lazily imported.

## 14. Phases

```text
O0  Common run service and fake adapter
O1  Cron/CLI and webhook examples
O2  Feed checkpoint and finite-poll service
O3  Airflow adapter
O4  Prefect adapter
O5  Dagster op, asset, partition, and IOManager adapters
O6  Cross-adapter contract tests and deployment templates
```

## 15. Definition of done

1. No stream crosses an orchestrator boundary implicitly.
2. Every split occurs at a durable handoff.
3. Cancellation and deadlines reach Riko.
4. Retries have documented idempotency behavior.
5. Webhooks use event IDs and replay protection.
6. Feed monitoring persists checkpoint state.
7. Orchestrator metadata uses artifact references, not large payloads.
8. The base CLI remains a run adapter, not a scheduler daemon.
