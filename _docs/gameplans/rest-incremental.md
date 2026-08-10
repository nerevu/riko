# Riko REST and Incremental Source Gameplan

## 1. Mission

Add a richer declarative REST-source layer to Riko with first-class pagination,
authentication references, dependent endpoints, incremental cursors, source-side filter
pushdown, and explicit source state.

The objective is not to turn Riko into a warehouse-loading framework. The objective is to
make REST acquisition as composable and configuration-driven as Riko's transformation
pipes while preserving Riko's existing record-stream model.

This plan is informed particularly by dlt's `rest_api` source, Singer's tap/state
conventions, and Riko's connector and monitoring plans.

Tabular conversion is intentionally **not** specified here. Pandas, Arrow, and Polars
boundaries are owned by `tabular-interop.md`.

## 2. Positioning

```text
dlt
    declarative extraction, schema normalization, incremental state, destination loading

Singer
    interoperable tap/target protocol and replication state

riko
    configurable record-stream processing, branching, joins, feed/web processing,
    sync/async/local-parallel execution
```

Riko should borrow strong source-side ideas without adopting destination-centric schema
loading as its primary abstraction.

## 3. Relationship to existing gameplans

This gameplan extends `connectors.md`.

`connectors.md` remains authoritative for:

* connector package boundaries;
* credential references and secret resolution;
* HTTP session lifecycle;
* source resolver contracts;
* response metadata and size/redirect limits;
* optional protocol/provider packages.

This plan owns higher-level **REST collection semantics** built on top of that transport.

`feed-monitoring.md` remains authoritative for `SourceCheckpoint`, checkpoint stores,
commit ordering, `Change` / `ChangeFeedSemantics`, dedupe, change detection, and monitoring
state. This plan defines how REST requests and responses encode/decode source cursors and
push source-supported filters; it must reuse the shared checkpoint/change-feed lifecycle
rather than invent a second state system.

`tabular-interop.md` remains authoritative for Pandas/Arrow/Polars conversion.

## 4. Non-goals

Do not add to core:

* automatic warehouse table creation as the primary output model;
* destination-specific schema migration;
* a Singer-compatible process protocol unless separately justified;
* embedded plaintext secrets in serialized pipeline configuration;
* a second HTTP client stack;
* a monolithic `fetch` function that guesses every API convention;
* provider-specific change-feed semantics in this plan;
* DataFrame/Arrow conversion semantics in this plan.

## 5. R0 — REST source plan

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
    source_filter: SourceFilterPlan | None
    dependencies: tuple[EndpointDependency, ...]
```

The plan is serializable, inspectable, and fingerprintable. Credentials remain references
resolved through connector/`ExecutionContext` mechanisms.

## 6. R1 — explicit REST source

Introduce a dedicated REST source rather than overloading RSS-oriented `fetch`.

Possible API:

```python
flow = AsyncPipe(
    "rest",
    conf={
        "base_url": "https://api.example.com/",
        "path": "events",
    },
)
```

or resolver-backed source configuration when connector architecture is available:

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

Final naming follows `connectors.md` compatibility rules around `fetch`; existing RSS
semantics must not change silently.

## 7. R2 — response record selection

Support configured extraction from common REST envelopes:

```json
{
  "results": [...],
  "paging": {"next": "..."}
}
```

```python
"data_path": "results"
```

Requirements:

* one normalized path traversal implementation;
* explicit missing-path behavior;
* object payloads may emit one record;
* arrays emit records lazily where parser support permits;
* response metadata stays namespaced rather than being merged into each user record.

## 8. R3 — pagination vocabulary

Common pagination should require no custom Python.

Initial strategies:

```text
next_url
page_number
offset_limit
cursor_param
header_link
```

Examples:

```python
"paginator": {
    "type": "next_url",
    "path": "paging.next",
}
```

```python
"paginator": {
    "type": "page_number",
    "param": "page",
    "start": 1,
    "stop_when": "empty",
}
```

Requirements:

* next URLs obey configured origin policy;
* page/record maxima are configurable;
* repeated-cursor detection prevents loops where the pagination strategy defines comparable
  cursor identity;
* cancellation closes active response/session resources;
* pagination state is observable;
* a paginator cannot silently override auth or other security-sensitive configuration.

An opaque incremental resume token is **not** automatically a pagination cursor and must not
be compared merely to detect a loop. Pagination and source-resume state may be distinct.

## 9. R4 — authentication references

REST configuration references connector credentials:

```python
"credential": "apis/github"
```

Provider-facing lifecycle such as OAuth status/refresh/revoke belongs to
`provider-integrations.md`; storage/resolution of credential material belongs to
`connectors.md`.

The REST source simply consumes the resolved credential/session and must not implement a
parallel secret or token store.

## 10. R5 — incremental extraction

Incremental extraction answers:

> Which source cursor should the next REST request use after the previous successful
> handoff?

Example:

```python
"incremental": {
    "cursor_path": "updated_at",
    "initial_value": "2026-01-01T00:00:00Z",
    "request_param": "since",
}
```

The value is encoded into the shared source checkpoint owned by `feed-monitoring.md`.

Rules:

* derive a candidate cursor while processing responses;
* commit it only through the shared checkpoint commit lifecycle;
* comparison semantics (`max`, ordered token, opaque cursor) are explicit;
* equal-cursor records require a tie-break strategy when ordering is not strict;
* initial/full-refresh behavior is explicit;
* cursor state is serializable and inspectable;
* a failed page/handoff cannot move committed state past unprocessed records;
* when the source returns a terminal/batch resume cursor, that cursor remains a candidate
  until every required record through that response boundary has completed durable handoff.

### 10.1 Opaque cursor rule

For `opaque_token`, REST machinery may only:

```text
extract token from configured response location
→ store token as JsonValue
→ inject the same logical token into the configured next/resume request location
```

Generic code must not:

```text
increment the token
parse an embedded timestamp/offset
numerically compare it
lexicographically compare it
infer ordering from its string/JSON representation
canonicalize it into a different semantic value
```

If request serialization necessarily turns structured JSON into a transport representation
such as a query string, the source adapter owns that reversible encoding. The checkpoint
still stores the source-level JSON value.

This directly follows the opaque cursor lifecycle owned by `feed-monitoring.md`.

## 11. R6 — cursor strategies

Support multiple source-position patterns:

```text
monotonic_value
    numeric or timestamp max cursor

opaque_token
    server-issued resume token; round-trip only, never generically ordered

compound
    timestamp + stable-id tie breaker

page_checkpoint
    page/offset only when the API guarantees stable paging
```

Compound example:

```json
{
  "updated_at": "2026-08-09T12:00:00Z",
  "id": 4821
}
```

This avoids loss when several records share the same boundary timestamp.

`opaque_token` deliberately has fewer generic operations than `monotonic_value` or
`compound`. A source can expose replay/order guarantees through `ChangeFeedSemantics`; they
must not be guessed from the token.

## 12. R6a — source-side filter pushdown

A REST source may support server-side filtering that reduces records before transfer. Treat
this as an acquisition optimization/selection contract, not as a replacement for Riko's
ordinary `filter` stage.

Possible configuration:

```python
"source_filter": {
    "strategy": "query",
    "params": {
        "status": "open",
        "updated_since": {"cursor": True},
    },
}
```

or when the API requires a structured POST body:

```python
"source_filter": {
    "strategy": "json_body",
    "body": {
        "selector": {...},
    },
}
```

Rules:

* filtering is used only when the upstream API explicitly supports equivalent semantics;
* the source filter is serializable/inspectable in the plan;
* GET query, POST body, header, or provider-specific named strategies may be supported by
  adapters;
* the source adapter owns the syntax and validates which fields/operators are supported;
* filter pushdown may reduce acquisition cost but must not silently change the logical
  workflow result compared with the declared source-selection semantics;
* security-sensitive request fields cannot be introduced through an unvalidated filter;
* a provider-specific executable filter language is not promoted into generic Riko core;
* downstream `flow.filter(...)` remains available for transformations that cannot or should
  not be pushed to the source.

The plan/introspection layer should distinguish:

```text
source filter
    executed by the upstream API before records reach Riko

pipeline filter
    executed by Riko after acquisition
```

For change feeds, a source-side filter narrows which source changes are observed. The
adapter must document whether changing that filter invalidates/requires resetting the
existing checkpoint.

## 13. R7 — dependent endpoints

One REST resource may parameterize another:

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

Map this to existing Riko topology rather than a second execution engine:

```text
parent records
→ bounded flat-map dependent request
→ child records
```

Requirements:

* dependency edges appear in workflow introspection;
* bounded async concurrency is reused;
* parent identity/context can be projected into child metadata when configured;
* N+1 behavior is visible in plans/metrics;
* rate/concurrency limits are explicit;
* dependencies serialize in workflow definitions.

## 14. R8 — request rate limits and backpressure

REST request concurrency is distinct from downstream CPU parallelism.

```python
"requests": {
    "concurrency": 10,
    "rate": 5,
    "per": 1.0,
}
```

Requirements:

* reuse AnyIO bounded concurrency;
* honor `Retry-After` where appropriate;
* expose throttling metrics;
* reuse sessions rather than opening one per item;
* cancellation stops queued requests;
* retries are bounded and policy-driven.

Generic retry semantics remain aligned with execution/orchestration contracts; this section
only specializes HTTP rate-limit behavior.

## 15. R9 — schema observations

REST acquisition may report observed record shape for diagnostics:

```text
field presence statistics
type observations
schema fingerprint
schema drift event
optional JSON Schema validation hook
```

Strict schema validation/drift policy remains with the schema/HigherGov plans. REST sources
must not automatically mutate warehouse schemas.

## 16. Source versus transformation responsibilities

```text
REST source owns
    HTTP request
    credential reference use
    pagination
    REST cursor extraction/transport encoding
    response record extraction
    supported source-filter pushdown

shared monitoring/change-feed contract owns
    persisted source position
    opaque cursor semantic rules
    commit ordering
    Change / ChangeFeedSemantics
    dedupe / business change detection

Riko pipes own
    filtering after acquisition
    mapping
    joins
    fan-out
    enrichment
    aggregation
    validation hooks
    anomaly/change processing

tabular-interop owns
    Pandas / Arrow / Polars boundaries

sink/connectors own
    destination protocol and delivery semantics
```

## 17. dlt/dltHub lessons

Borrow from dlt:

* declarative REST resources;
* paginator strategy vocabulary;
* dependent endpoint resources;
* incremental cursor configuration.

Its broad Python/tabular input ergonomics are relevant, but implementation belongs in
`tabular-interop.md`, not this REST plan.

Borrow from dltHub conceptually:

* deployment/scheduling belongs above the extraction library;
* persisted source state should survive scheduled runs.

Do not copy destination/schema-loading as Riko's primary execution model.

## 18. Singer lessons

Borrow:

* explicit replication/source state;
* clean source/destination capability separation;
* resumability expectations.

Do not require newline-delimited Singer messages or tap/target subprocess boundaries for
ordinary in-process execution.

## 19. Interaction with monitored and change feeds

Periodic incremental REST source:

```text
periodic finite poll
→ REST cursor extraction
→ shared checkpoint lifecycle
→ optional dedupe / changed
→ anomaly / filter
→ fan-out
```

REST-backed change feed:

```text
resume from shared SourceCheckpoint
→ REST request/response cursor encoding
→ normalize source changes into Change
→ apply declared ChangeFeedSemantics
→ dedupe/routing/changed
→ durable handoff
→ commit source checkpoint
```

If an API has a reliable cursor, dedupe may still be required when the source declares
`replay="possible"`. If the source version changes, `changed()` may still suppress a
business-level event when selected business fields did not change.

Incremental extraction, source-emitted change identity, and business change detection are
not synonyms.

## 20. Interaction with workflow definitions

REST plans, paginator configuration, endpoint dependencies, cursor configuration, and
source-filter pushdown are serializable in full workflow definitions.

Dependency extraction should report:

```text
external HTTP origins
credential references
parent REST resources
dependent endpoint edges
checkpoint namespaces
source-filter strategy
```

Compiled Python must retain equivalent source semantics.

## 21. Tabular interoperability

A REST stream may be materialized or batched into Pandas/Arrow only through the explicit
contracts in `tabular-interop.md`:

```text
REST records
→ ordinary Riko transforms
→ to_pandas() / to_arrow() / to_arrow_batches()
```

No REST-specific frame conversion API is defined here.

## 22. Observability

Emit metrics/events for:

* requests attempted/succeeded/failed;
* pages fetched;
* records emitted;
* source-filter strategy and whether pushdown was applied;
* retries and rate-limit delay;
* candidate cursor before/after;
* checkpoint commit outcome through the shared checkpoint layer;
* dependent-resource request count;
* response bytes;
* schema fingerprint changes.

Opaque cursor values may be sensitive/provider-specific; events should prefer fingerprints
or redacted summaries when logging full cursor values is not safe or useful.

Tabular materialization metrics belong to `tabular-interop.md`.

Never expose authorization headers or credential values.

## 23. Testing strategy

Required deterministic fixtures:

1. JSON object source;
2. array source;
3. nested `data_path` extraction;
4. next-URL pagination;
5. page-number pagination;
6. offset/limit pagination;
7. repeated pagination-cursor loop detection;
8. bearer/API-key credential resolution without serialized secret;
9. monotonic timestamp cursor resume using the shared checkpoint contract;
10. compound timestamp/id tie handling;
11. opaque JSON/string cursor round-trips without generic comparison/coercion;
12. source-issued terminal cursor remains uncommitted after failed handoff;
13. query-parameter filter pushdown;
14. structured POST-body filter pushdown;
15. pushdown plan remains distinct from downstream `filter`;
16. changed source filter detects/documented checkpoint-reset requirement where applicable;
17. dependent parent/child endpoint execution;
18. bounded child-request concurrency;
19. `Retry-After` / rate-limit behavior;
20. serialized workflow compiles and preserves REST semantics.

Frame conversion tests live in `tabular-interop.md`.

## 24. Phases

```text
R0   RestSourcePlan
R1   explicit REST source
R2   response data selection
R3   pagination strategies
R4   connector credential integration
R5   incremental cursor extraction
R6   compound/opaque cursor strategies
R6a  source-filter pushdown
R7   dependent endpoints
R8   request concurrency/rate limits
R9   schema observations/drift integration
```

## 25. Definition of done

1. Common REST APIs can be ingested without custom pagination loops.
2. Credentials remain references resolved by connector infrastructure.
3. REST cursor state uses the shared checkpoint lifecycle and commits only after successful
   handoff.
4. Opaque source cursors round-trip without generic interpretation/comparison.
5. Compound cursors prevent timestamp-boundary data loss where configured.
6. Source-supported filters can be pushed into REST acquisition without replacing Riko's
   downstream filter semantics.
7. REST-backed change feeds normalize into `Change` / `ChangeFeedSemantics` owned by
   `feed-monitoring.md` rather than defining another event model.
8. Dependent endpoints are represented as ordinary Riko topology.
9. REST request concurrency and rate limits are bounded and observable.
10. REST source configuration works in Python and serialized workflow definitions.
11. Pandas/Arrow/Polars behavior is referenced, not duplicated, from `tabular-interop.md`.
12. Riko remains a record-processing library rather than a destination-first loader.
