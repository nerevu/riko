# SQL & dbt integration gameplan

## 1. Mission

Create optional SQL and dbt packages that provide bounded database reads, explicit writes, query
push-down, batch interchange, and warehouse transformation coordination.

This plan specializes the common `Target`/`write`/Resource/batch contracts; it does not define a
parallel SQL source/sink execution model.

## 2. Package boundaries

```text
nerevu/riko
    Pipeline + Workflow v2 runtime/definition contracts
    Target / Format / ReadNode / WriteNode structure
    provider-neutral write/effect semantics
    Feed and Pipeline batch-mode contracts
    Context resource definitions and execution-owned resource values

nerevu/riko-sql
    POSTGRES/DuckDB/etc Target adapters
    Ibis connection adapters
    SQL query/read planning specialization
    Arrow/Narwhals bridges
    query push-down

nerevu/riko-dbt
    dbt runner service
    manifest and run-result normalization
    optional dbt-ibis helpers
```

Do not add database drivers or dbt-core to the base Riko installation.

## 3. Connection and credential model

Configured database Targets reference declared resources/credentials rather than embedding secrets:

```json
{
  "name": "postgres",
  "database": "analytics",
  "table": "orders",
  "resources": {"connection": "warehouse/analytics"}
}
```

The connection resource resolves once per execution to the configured adapter or connection value.
Passwords/tokens are never serialized in workflow URLs. Immutable Context contains definitions;
private execution owns live connections and closes owned resources deterministically.

## 4. Read API

The target user surface is `Pipeline.read(...)` over a configured SQL/database Target. SQL-specific
query options may normalize into immutable adapter/query configuration before execution.

Conceptually:

```python
orders = Pipeline.read(
    Target(
        Targets.POSTGRES,
        table="orders",
        resources={"connection": "warehouse/analytics"},
    ),
    columns=("id", "status", "amount"),
    predicate=...,  # declarative SQL-capable subset
)
```

Exact public argument typing belongs to the common Target/read contract once implemented; this plan
owns SQL specialization, not a competing `SqlReadPlan` public identity.

Exactly one of table/query forms is selected when an adapter supports raw query input. Raw SQL may be
disabled by policy.

The source streams the negotiated representation in batch mode and ordinary records in item mode.
There is no parallel BatchPipe hierarchy.

## 5. Push-down

Push-down occurs only for a documented declarative expression subset. Unsupported transforms remain
normal Riko nodes after read.

Initial subset:

```text
column selection
comparison predicates
boolean conjunction/disjunction
limit
stable order when supported
grouped aggregate later
```

Preparation/explain reports which operations were pushed down and which remain local. Do not inspect
arbitrary Python callables to synthesize SQL.

## 6. Write API

Database mutation uses the common `Pipeline.write()` effect over a configured writable Target:

```python
flow = flow.write(
    Target(
        Targets.POSTGRES,
        table="processed_orders",
        resources={"connection": "warehouse/analytics"},
    ),
    mode="append",
    schema_policy="fail",
)
```

Supported adapter modes may begin with:

```text
append
replace
merge/upsert
```

`merge` requires explicit keys. Destructive replacement/schema change passes the applicable policy
or approval checks. Transactions, partial failure, and commit boundaries are explicit.

`write()` keeps its generic pass-through contract; SQL completion metadata is emitted as `WriteResult`
through EventSink. There is no separate SQL `sink()` or `export()` effect contract.

Side-effecting writes participate in the common execution-derived idempotency contract. When a
backend cannot genuinely honor idempotency, retryable/resumable use follows the generic effect/
execution validation rules rather than inventing SQL-local behavior.

## 7. Schema handling

At read time, capture truthful source schema metadata/fingerprint. At write time, compare incoming and
target schemas using the applicable schema-drift contract.

Initial policies:

```text
fail
additive
explicit_mapping
```

Do not silently coerce lossy types or issue automatic destructive DDL.

## 8. Ibis to batch bridge

Use Ibis for backend-neutral query construction and Arrow when it is actually the cheapest/native
interchange representation:

```text
Ibis expression
-> native/Arrow batch reader
-> Pipeline(batch=True)
-> optional Narwhals/Polars/pandas view
```

Connections/readers close on early termination. Batch size is bounded.

Batch negotiation follows `execution-semantics.md`:

```text
candidates = upstream representations ∩ representations the node accepts

1. current representation
2. zero-copy/interchange-backed candidate
3. cheapest supported conversion
4. Python objects fallback
```

A database driver will often choose Arrow because that path is natively cheap, not because Arrow has
a global rank. Pandas-native/Polars-native downstream work stays native when accepted.

Explicit `batch_backend=` forces a compatible representation and raises when unavailable.

## 9. DataFrame relationship

`Pipeline.from_frame()` is local ingestion. Database reads must not materialize an entire result into
a DataFrame before streaming.

Batches are ordinary values: `.map(func)` receives a batch in batch mode and an item in item mode.
Concrete frame conversion remains owned by `tabular-interop.md`.

## 10. dbt runner service

```python
class DbtRunner(Protocol):
    async def run(self, request: DbtRunRequest, context: Context) -> DbtRunResult: ...
```

Context is the immutable environment input. Live dbt clients/runners and database connections come
from declared Resources; there is no public ExecutionContext.

Normalize:

- invocation arguments;
- project/profiles references;
- selected nodes;
- manifest fingerprint;
- per-node status;
- elapsed time;
- generated artifact references;
- sanitized errors.

The first implementation may adapt `dbtRunner` through the common worker boundary. It must not
expose dbt SDK objects publicly.

## 11. dbt and Riko execution boundary

```text
Riko reads/transforms/writes
-> durable database commit
-> dbt transforms in warehouse
-> durable dbt result
-> Riko reads/delivers next phase
```

A dbt run is never invoked per record or in the middle of an uncommitted lazy write. Orchestration may
coordinate the durable phases separately.

## 12. dbt-ibis

Treat dbt-ibis as optional experimentation until supported backends/API stability meet compatibility
policy. Golden SQL/result fixtures are required per supported backend.

## 13. Phases

```text
S0  Ibis/backend compatibility spikes
S1  database Target adapters + connection Resource conformance
S2  Pipeline batch streaming and cleanup
S3  push-down subset + explain output
S4  SQL write Target + transactions/idempotency
S5  schema drift + merge semantics
D0  dbt runner protocol + fake runner
D1  dbt-core adapter + artifact normalization
D2  orchestration + CLI plugins
D3  optional dbt-ibis evaluation
```

## 14. Definition of done

1. Base Riko has no SQL/dbt dependency.
2. Connections/credentials are declared Resources/references.
3. Database reads use configured Targets and bounded ordinary Pipeline batch mode.
4. Push-down is explicit/inspectable.
5. Database mutation uses common `Pipeline.write()`/WriteResult semantics with transactions and
   idempotency participation; no SQL-specific sink/export runtime is introduced.
6. Schema changes never occur silently.
7. dbt runs only after a durable load boundary.
8. Public results contain no Ibis/dbt SDK objects.
9. Early termination closes execution-owned readers/connections.
10. Backend contract tests cover at least DuckDB and one client/server database.

---

> **Runtime-contract section extracted from ROADMAP §25.** SQL/dbt specializes the common batch/
> dataframe path. `§N` refs point to [RUNTIME_CONTRACT.md](../RUNTIME_CONTRACT.md).

## 25. Conversion and dataframe integration

> **Shipped:** see [IMPLEMENTED.md §25](../IMPLEMENTED.md#25-conversion--export-converters-shipped)
> for current converters. **Remaining:** the Pipeline batch/dataframe path above.

Meza owns conversion work where applicable. Riko may temporarily provide adapters/protocols needed by
the new architecture, but conversion implementation should be upstreamed/finalized there when it is
generally useful.

The batch/dataframe path avoids pandas as a mandatory intermediary. Arrow, Narwhals, Polars, pandas,
SQL-native values, or Python objects are execution representations selected by capability/conversion
cost rather than separate public pipeline types or a global library preference.

"Zero-copy" is claimed only when the actual path avoids conversion/copying.
