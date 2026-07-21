# Authoritative Riko SQL and dbt Integration Gameplan

## 1. Mission

Create optional SQL and dbt packages that provide bounded database reads, explicit
writes, query push-down, batch interchange, and warehouse transformation coordination.

This plan promotes Shelf milestones 5.1, 19, and 20.

## 2. Package boundaries

```text
nerevu/riko
    pipeline runtime
    Feed and batch contracts
    ExecutionContext resources
    schema and artifact contracts

nerevu/riko-sql
    Ibis connection adapters
    SQL read plans
    SQL write/export target
    Arrow/Narwhals bridges
    query push-down

nerevu/riko-dbt
    dbt runner service
    manifest and run-result normalization
    optional dbt-ibis helpers
```

Do not add database drivers or dbt-core to the base Riko installation.

## 3. Connection and credential model

Pipeline definitions use a named connection reference:

```json
{
  "connection": "warehouse/analytics",
  "table": "orders"
}
```

The connection resolver returns an execution-scoped Ibis connection or adapter. Passwords
and tokens are never serialized in a URI inside the pipeline definition.

## 4. Read API

Keep a familiar named source, but define an immutable plan before execution:

```python
@dataclass(frozen=True, slots=True, kw_only=True)
class SqlReadPlan:
    connection: str
    table: str | None = None
    query: str | None = None
    columns: tuple[str, ...] = ()
    predicate: SqlPredicate | None = None
    batch_size: int = 65_536
    limit: int | None = None
```

Exactly one of `table` or `query` is supplied. Raw SQL may be disabled by policy.

```python
flow = SyncPipe(
    "fetchsql",
    conf={
        "connection": "warehouse/analytics",
        "table": "orders",
        "columns": ["id", "status", "amount"],
        "filter": {"field": "status", "op": "eq", "value": "active"},
    },
)
```

The source streams Arrow record batches or the accepted batch abstraction. Record mode is
an explicit conversion for small or compatibility workloads.

## 5. Push-down

Push-down occurs only for a documented expression subset. Unsupported transforms remain
normal Riko stages after the source.

Initial subset:

```text
column selection
comparison predicates
boolean conjunction/disjunction
limit
stable order when supported
grouped aggregate in a later phase
```

The resolved plan reports which operations were pushed down and which remain local.
Do not inspect arbitrary Python callables to synthesize SQL.

## 6. Write API

Database writes are an export target or sink service, not a mode hidden inside a source
module.

```python
result = flow.export(
    "sql",
    connection="warehouse/analytics",
    table="processed_orders",
    mode="append",
    schema_policy="fail",
)
```

Supported modes begin with:

```text
append
replace
merge
```

`merge` requires explicit keys. Destructive replacement and schema changes pass policy
and approval checks. Transactions, partial failure, and commit boundaries are explicit.

## 7. Schema handling

At read time, capture the source schema and fingerprint. At write time, compare incoming
and target schemas using the core schema-drift contracts.

Initial policies:

```text
fail
additive
explicit_mapping
```

Do not silently coerce lossy types or issue automatic destructive DDL.

## 8. Ibis to batch bridge

Use Ibis for backend-neutral query construction and Arrow for interchange:

```text
Ibis expression
→ to_pyarrow_batches
→ Riko batch stream
→ optional Narwhals view
```

Connections and readers close on early termination. Batch size is configurable and
bounded. Backend capability differences are surfaced in the plan and events.

## 9. DataFrame source relationship

`SyncPipe.from_frame()` and runtime frame resources are local ingestion mechanisms. SQL
sources should not materialize an entire result into a DataFrame before streaming.

## 10. dbt runner service

```python
class DbtRunner(Protocol):
    async def run(
        self,
        request: DbtRunRequest,
        context: ExecutionContext,
    ) -> DbtRunResult: ...
```

Normalize:

* invocation arguments;
* project and profiles references;
* selected nodes;
* manifest fingerprint;
* per-node status;
* elapsed time;
* generated artifact references;
* sanitized errors.

The first implementation may wrap `dbtRunner` in a worker thread. It must not expose dbt
SDK objects publicly.

## 11. dbt and Riko execution boundary

```text
Riko extracts and loads
→ durable table commit
→ dbt transforms in warehouse
→ durable dbt result
→ Riko reads or delivers
```

A dbt run is never invoked per item or in the middle of a lazy stream. Orchestration may
coordinate these three steps as separate tasks because the database tables are durable
boundaries.

## 12. dbt-ibis

Treat dbt-ibis as optional experimentation until its supported backends and API stability
meet the package's compatibility policy. Shared expression helpers may live in a neutral
module, but Riko must not promise that every local expression can be compiled by dbt.
Golden SQL and result fixtures are required for each supported backend.

## 13. Phases

```text
S0  Ibis and backend compatibility spikes
S1  Connection registry and SqlReadPlan
S2  Arrow batch streaming and cleanup
S3  Push-down subset and explain output
S4  SQL export target and transactions
S5  Schema drift and merge semantics
D0  dbt runner protocol and fake runner
D1  dbt-core adapter and artifact normalization
D2  orchestration and CLI plugins
D3  optional dbt-ibis evaluation
```

## 14. Definition of done

1. Base Riko has no SQL or dbt dependency.
2. Connections and credentials are named resources.
3. Reads stream bounded batches.
4. Push-down is explicit and inspectable.
5. Writes use a sink/export contract with transaction semantics.
6. Schema changes never occur silently.
7. dbt runs only after a durable load boundary.
8. Public results contain no Ibis or dbt SDK objects.
9. Early termination closes readers and connections.
10. Backend contract tests cover at least DuckDB and one client/server database.
