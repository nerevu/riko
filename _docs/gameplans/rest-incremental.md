# Riko REST, Incremental Source, and Tabular Interop Gameplan

## 1. Mission

Add a richer declarative REST-source layer to Riko with first-class pagination,
authentication references, dependent endpoints, incremental cursors, and clean Pandas /
Arrow interoperability.

The objective is not to turn Riko into a warehouse-loading framework. The objective is to
make REST acquisition as composable and configuration-driven as Riko's transformation
pipes while preserving Riko's existing record-stream model.

This plan is informed particularly by dlt's `rest_api` source and dltHub deployment model,
Singer's tap/state conventions, and Riko's existing connector and orchestration gameplans.

## 2. Positioning

The relevant project boundaries are:

```text
dlt
    declarative extraction, schema normalization, incremental state, destination loading

Singer
    interoperable tap/target protocol and replication state

riko
    configurable record-stream processing, branching, joins, feed/web processing,
    sync/async/local-parallel execution
```

Riko should borrow the strongest source-side ideas without adopting destination-centric
schema loading as its primary abstraction.

## 3. Relationship to existing gameplans

This gameplan extends `_docs/gameplans/connectors.md`.

The connector gameplan remains authoritative for:

* connector package boundaries;
* credential references;
* HTTP session lifecycle;
* source resolver contracts;
* response metadata and size/redirect limits;
* optional protocol/provider packages.

This plan defines the higher-level **REST collection semantics** built on top of that HTTP
connector.

It also shares checkpoint/state contracts with the persistent monitoring gameplan. There
must be one source-position model, not separate incompatible cursor systems for polling and
REST extraction.

## 4. Non-goals

Do not add to core:

* automatic warehouse table creation as the primary output model;
* destination-specific schema migration;
* a Singer-compatible process protocol unless separately justified;
* embedded plaintext secrets in serialized pipeline configuration;
* a second HTTP client stack;
* a monolithic `fetch` function that guesses every API convention;
* a DataFrame-first rewrite of Riko's record-stream internals.

## 5. Phase R0 — define a REST source plan

Represent REST acquisition declaratively and separately from execution.

```python
@dataclass(frozen=True, slots=True, kw_only=True)
class RestSourcePlan:
    base_url: str
    path: str
    method: Literal["GET", "POST"]
    params: Mapping[str, JsonValue]
    headers: Mapping[str, str]
    credential: str | None
    data_path: str | None
    paginator: PaginatorPlan | None
    incremental: IncrementalPlan | None
    dependencies: tuple[EndpointDependency, ...]
```

This plan should be serializable, inspectable, and fingerprintable.

Credentials remain references resolved through `ExecutionContext` / connector mechanisms.

## 6. Phase R1 — explicit REST pipe / source

Introduce a dedicated source rather than overloading RSS-oriented `fetch`.

Possible public API:

```python
flow = AsyncPipe(
    "rest",
    conf={
        "base_url": "https://api.example.com/",
        "path": "events",
    },
)
```

or resolver-backed source configuration when the connector architecture is available:

```python
flow = AsyncPipe(
    "source",
    conf={
        "type": "rest",
        "client": {...},
        "endpoint": {...},
    },
)
```

The final naming must follow the connector gameplan's compatibility rule around `fetch`.
Do not silently change existing RSS semantics.

## 7. Phase R2 — response record selection

REST APIs commonly wrap records in objects such as:

```json
{
  "results": [...],
  "paging": {"next": "..."}
}
```

Support configured record selection:

```python
"data_path": "results"
```

Requirements:

* dot/path traversal uses one normalized path implementation;
* missing path behavior is explicit;
* object payloads may emit one record;
* array payloads emit records lazily where parser support allows;
* response metadata remains available through namespaced context/metadata rather than
  being merged into every user record by default.

## 8. Phase R3 — pagination vocabulary

Pagination should be a first-class strategy with no custom Python required for common API
shapes.

Initial paginator types:

```text
next_url
page_number
offset_limit
cursor_param
header_link
```

Example:

```python
"paginator": {
    "type": "next_url",
    "path": "paging.next"
}
```

Page-number example:

```python
"paginator": {
    "type": "page_number",
    "param": "page",
    "start": 1,
    "stop_when": "empty"
}
```

Requirements:

* next URL is constrained by configured origin policy by default;
* maximum pages / records can be configured;
* pagination loop detection prevents repeated-cursor infinite loops;
* cancellation closes the active HTTP response/session cleanly;
* pagination state can be reported through execution events;
* a paginator cannot silently override security-sensitive URL/auth configuration.

## 9. Phase R4 — authentication references

Support common auth schemes through connector configuration while keeping secrets outside
serialized workflow definitions.

```python
"credential": "apis/github"
```

Resolved credential metadata may describe:

```text
bearer token
basic auth
API key header
API key query parameter
OAuth2 access token
```

The REST source does not implement OAuth refresh independently if the connector credential
provider already owns refresh semantics.

## 10. Phase R5 — incremental extraction

Incremental state answers:

> What value should the next request use to retrieve records after the previous successful
> run?

Example:

```python
"incremental": {
    "cursor_path": "updated_at",
    "initial_value": "2026-01-01T00:00:00Z",
    "request_param": "since",
}
```

The source checkpoint stores the last committed cursor separately from downstream
processing state.

Rules:

* cursor advancement occurs only after successful downstream handoff/checkpoint commit;
* comparison semantics (`max`, ordered token, opaque cursor) are declared by strategy;
* equal-cursor records require a tie-break strategy when APIs are not strictly monotonic;
* initial/full-refresh behavior is explicit;
* cursor state is inspectable and serializable;
* a failed page does not advance committed state past unprocessed records.

## 11. Phase R6 — robust cursor strategies

Support several source-position patterns rather than assuming timestamps solve every API.

```text
monotonic_value
    numeric or timestamp max cursor

opaque_token
    server-issued continuation token

compound
    timestamp + stable id tie breaker

page_checkpoint
    page/offset when API guarantees stable paging
```

Compound cursor example:

```json
{
  "updated_at": "2026-08-09T12:00:00Z",
  "id": 4821
}
```

This avoids losing multiple records that share the same timestamp at a run boundary.

## 12. Phase R7 — dependent endpoints

Borrow the useful idea from dlt's REST source: one resource may parameterize another REST
resource.

Example use case:

```text
GET /issues
    ↓ each issue.number
GET /issues/{number}/comments
```

Declarative shape:

```python
{
    "name": "comments",
    "endpoint": {
        "path": "issues/{resources.issues.number}/comments"
    }
}
```

Riko implementation should map this onto existing stream topology rather than create a
second execution engine.

Conceptually:

```text
parent REST records
→ flat_map dependent request
→ child records
```

Requirements:

* dependency edges appear in workflow introspection;
* bounded async concurrency is reused for child requests;
* parent keys/context can be projected into child metadata when configured;
* N+1 request behavior is visible in plans/metrics;
* rate limits and concurrency limits are explicit;
* dependent endpoints can be represented in serialized workflows.

## 13. Phase R8 — rate limiting and HTTP backpressure

REST extraction needs source-level concurrency controls distinct from downstream CPU
parallelism.

Configuration:

```python
"requests": {
    "concurrency": 10,
    "rate": 5,
    "per": 1.0,
}
```

Requirements:

* reuse AnyIO bounded concurrency primitives;
* honor `Retry-After` where appropriate;
* expose throttling metrics;
* do not open one HTTP session per item;
* cancellation stops queued requests;
* retries remain bounded and policy-driven.

## 14. Phase R9 — schema observations, not warehouse ownership

Riko may infer or observe record shape for diagnostics without becoming a destination
schema manager.

Useful capabilities:

```text
field presence statistics
type observations
schema fingerprint
schema drift event
optional JSON Schema validation
```

The existing schema-contract/HigherGov work remains authoritative for strict validation.
The REST source should emit enough metadata to connect source observations to those
contracts.

Do not automatically mutate warehouse schemas from core Riko.

## 15. Phase R10 — Pandas input interoperability

Pandas integration should be an explicit boundary conversion, not a new internal data
model.

Target API:

```python
flow = SyncPipe.from_pandas(df)
```

Equivalent baseline behavior:

```python
SyncPipe(source=df.to_dict("records"))
```

but implemented to avoid unnecessary intermediate copies where practical.

Requirements:

* preserve column names;
* define treatment of index (`ignore`, `field`, `preserve` metadata);
* normalize pandas missing values predictably;
* document dtype loss when converting to ordinary Python records;
* allow chunked conversion for large frames.

## 16. Phase R11 — Pandas output interoperability

Target API:

```python
df = flow.to_pandas()
```

This is a **terminal materialization operation** and must be documented as such.

Configuration may include:

```python
to_pandas(
    columns=None,
    index=None,
)
```

Requirements:

* reject or warn for known-unbounded feeds unless explicitly truncated;
* preserve predictable record-to-column ordering;
* use nullable dtypes where sensible without surprising coercion;
* expose an iterator/chunk mode for large finite streams if practical.

## 17. Phase R12 — Arrow interoperability

Arrow is a better zero/low-copy boundary for some tabular workloads than Python dicts.

Target helpers:

```python
SyncPipe.from_arrow(table)
flow.to_arrow()
```

and optionally batch-oriented forms:

```python
flow.to_arrow_batches(batch_size=10_000)
```

Do not force every pipe to understand Arrow batches. Convert at explicit boundaries unless
future batch semantics from the runtime contract provide a common abstraction.

## 18. Phase R13 — Polars interoperability (optional follow-up)

Once Arrow boundaries are stable, Polars can often interoperate through Arrow rather than
requiring dedicated internal machinery.

Possible convenience methods:

```python
SyncPipe.from_polars(frame)
flow.to_polars()
```

This is lower priority than Pandas because current Riko/HigherGov use cases already involve
Pandas.

## 19. Source versus transformation responsibilities

Keep the boundary clear:

```text
REST source owns
    HTTP request
    auth reference
    pagination
    source cursor
    response record extraction

Riko pipes own
    filtering
    mapping
    joins
    fan-out
    enrichment
    aggregation
    validation
    anomaly/change processing

sink/connectors own
    destination protocol and delivery semantics
```

This separation prevents REST configuration from growing into an all-purpose ETL DSL.

## 20. dlt/dltHub lessons to borrow

Borrow from dlt:

* declarative REST resources;
* paginator strategy vocabulary;
* dependent endpoint resources;
* incremental cursor configuration;
* broad Python/tabular input acceptance;
* clean DataFrame boundary ergonomics.

Borrow from dltHub conceptually:

* deployment/scheduling/monitoring belongs above the extraction library;
* persisted source state should work across scheduled runs.

Do not copy:

* destination/schema-loading as Riko's primary execution model;
* warehouse-first terminology where Riko is performing arbitrary record processing.

## 21. Singer lessons to borrow

Borrow:

* explicit replication/source state;
* clean distinction between source and destination capabilities;
* resumability expectations.

Do not require:

* newline-delimited Singer messages between in-process Riko stages;
* tap/target subprocess boundaries for ordinary Python execution.

## 22. Interaction with monitored feeds

REST source state composes with the monitoring gameplan:

```text
periodic finite poll
→ REST incremental cursor
→ dedupe / changed
→ anomaly / filter
→ fan-out
→ checkpoint commit
```

If the API already provides a reliable incremental cursor, downstream `dedupe` may be
unnecessary. If the cursor reports changed entities, `changed` may still be useful when
only selected fields matter.

Do not assume incremental extraction and change detection are synonyms.

## 23. Interaction with workflow definitions

REST source plans, dependency edges, paginator configuration, and incremental cursor
configuration must be serializable in full workflow definitions.

Dependency extraction should be able to report:

```text
external HTTP origins
credential references
parent REST resources
dependent endpoint edges
checkpoint/state namespaces
```

Compiled Python should retain equivalent source semantics.

## 24. Observability

Emit metrics/events for:

* requests attempted/succeeded/failed;
* pages fetched;
* records emitted;
* retries;
* rate-limit delay;
* cursor before/after;
* dependent-resource request count;
* response bytes;
* schema fingerprint changes;
* DataFrame/Arrow materialization size when terminal conversions occur.

Do not expose authorization headers or credential values.

## 25. Testing strategy

Required deterministic fixtures:

1. JSON object source;
2. array source;
3. nested `data_path` extraction;
4. next-URL pagination;
5. page-number pagination;
6. offset/limit pagination;
7. repeated-cursor loop detection;
8. bearer/API-key credential resolution without serialized secret;
9. monotonic timestamp incremental resume;
10. compound timestamp/id cursor tie handling;
11. failed handoff does not advance committed cursor;
12. dependent parent/child endpoint execution;
13. bounded child-request concurrency;
14. retry-after/rate-limit behavior;
15. Pandas → records → Pandas round trip for representative nullable values;
16. Arrow conversion and batch output;
17. unbounded feed rejects accidental `to_pandas()` materialization;
18. serialized workflow compiles and preserves REST plan semantics.

## 26. Phases

```text
R0   RestSourcePlan
R1   explicit REST source
R2   response data selection
R3   pagination strategies
R4   credential/auth integration
R5   incremental extraction
R6   compound/opaque cursor strategies
R7   dependent endpoints
R8   request concurrency/rate limits
R9   schema observations/drift integration
R10  Pandas input boundary
R11  Pandas terminal output
R12  Arrow boundaries
R13  optional Polars convenience
```

## 27. Definition of done

1. Common REST APIs can be ingested without custom pagination loops.
2. Credentials remain references outside serialized workflow definitions.
3. Incremental state is explicit, serializable, and committed only after successful handoff.
4. Compound cursors prevent timestamp-boundary data loss where configured.
5. Dependent endpoints are represented as ordinary Riko topology, not a second runtime.
6. REST request concurrency and rate limits are bounded and observable.
7. Pandas can enter and leave a finite Riko pipeline through explicit, documented boundaries.
8. Arrow interoperability supports efficient tabular exchange without changing Riko's core record model.
9. REST source configuration works in Python and serialized workflow definitions.
10. Riko remains a record-processing library rather than becoming a destination-first warehouse loader.