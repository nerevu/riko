# REST & incremental source gameplan

## 1. Mission

Add a richer declarative REST-source layer to Riko with first-class pagination,
authentication references, dependent endpoints, incremental cursors, and explicit source
state.

The objective is not to turn Riko into a warehouse-loading framework. The objective is to
make REST acquisition as composable and configuration-driven as Riko's transformation
pipes while preserving Riko's existing record-stream model.

This plan is informed particularly by dlt's `rest_api` source, Singer's tap/state
conventions, and Riko's connector and monitoring plans.

Tabular conversion is intentionally **not** specified here. Pandas, Arrow, and Polars
boundaries are owned by `tabular-interop.md` and the single-Pipeline batch contract in
`execution-semantics.md`.

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

`execution-semantics.md` is authoritative for `FeedResult`, `FeedState`, `StateStore`,
`StateKey`, checkpoint/CAS behavior, identity/generation, and execution-owned resource
lifecycle. `feed-monitoring.md` owns monitoring-specific observation/change/dedupe policy.
REST cursor state must use those shared state contracts rather than defining a second
`SourceCheckpoint` system.

`tabular-interop.md` remains authoritative for Pandas/Arrow/Polars conversion.

## 4. Non-goals

Do not add to core:

* automatic warehouse table creation as the primary output model;
* destination-specific schema migration;
* a Singer-compatible process protocol unless separately justified;
* embedded plaintext secrets in serialized pipeline configuration;
* a second HTTP client stack;
* a monolithic `fetch` function that guesses every API convention;
* DataFrame/Arrow conversion semantics in this plan;
* a REST-specific persistence/checkpoint protocol.

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
    dependencies: tuple[EndpointDependency, ...]
```

The plan is serializable, inspectable, and fingerprintable. Credentials remain references
resolved through declared `Context` resources and execution-owned connector sessions.

## 6. R1 — first-class REST source

REST is a first-class Riko module rather than an overload of RSS-oriented `fetch`:

```python
flow = Pipeline(
    "rest",
    conf={
        "base_url": "https://api.example.com/",
        "path": "events",
    },
)
```

Serialized form:

```json
{"type": "rest", "conf": {"base_url": "https://api.example.com/", "path": "events"}}
```

A resolver-backed `source`/`fetchauto` entry point may still select the same REST service
when connector architecture is available, but the canonical Python/serialized module is
`rest`. Existing RSS `fetch` semantics must not change silently.

The same definition runs under sync or async execution; do not create separate public
`SyncPipe`/`AsyncPipe` REST APIs.

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
* response metadata stays in `FeedResult.metadata`/item observation rather than being
  merged into each user record.

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
* repeated-cursor detection prevents loops;
* cancellation closes active response/session resources;
* pagination state is observable;
* a paginator cannot silently override auth or other security-sensitive configuration.

## 9. R4 — authentication references

REST configuration references connector credentials:

```python
"credential": "apis/github"
```

Provider-facing lifecycle such as OAuth status/refresh/revoke belongs to
`provider-integrations.md`; storage/resolution of credential material belongs to
`connectors.md`.

The REST source consumes a declared resolved credential/session resource and must not
implement a parallel secret or token store.

## 10. R5 — incremental extraction

Incremental extraction answers:

> Which cursor should the next REST request use after the previous successful handoff?

Example:

```python
"incremental": {
    "cursor_path": "updated_at",
    "initial_value": "2026-01-01T00:00:00Z",
    "request_param": "since",
}
```

The candidate cursor is represented as source state using the common `FeedState` /
`StateStore` contract. It is not written through a REST-specific checkpoint API.

Rules:

* advance the candidate cursor while processing responses;
* final finite-source state becomes committable only after `FeedResult.items` completes
  successfully;
* infinite/repeated polling uses explicit incremental checkpoint boundaries;
* comparison semantics (`max`, ordered token, opaque cursor) are explicit;
* equal-cursor records require a tie-break strategy when ordering is not strict;
* initial/full-refresh behavior is explicit;
* cursor state is backend-serializable and inspectable;
* a failed page/handoff cannot move committed state past unprocessed records;
* state mutation uses the shared CAS contract and conflicts propagate rather than silently
  reloading/rerunning.

## 11. R6 — cursor strategies

Support multiple source-position patterns:

```text
monotonic_value
    numeric or timestamp max cursor

opaque_token
    server-issued continuation token

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

## 12. R7 — dependent endpoints

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
* parent identity/provenance can be projected into child metadata when configured;
* child generation is deterministically derived from parent/source identity;
* N+1 behavior is visible in plans/metrics;
* rate/concurrency limits are explicit;
* dependencies serialize in workflow definitions.

## 13. R8 — request rate limits and backpressure

REST request concurrency is distinct from downstream CPU parallelism.

```python
"requests": {
    "concurrency": 10,
    "rate": 5,
    "per": 1.0,
}
```

Requirements:

* reuse bounded execution concurrency;
* honor `Retry-After` where appropriate;
* expose throttling metrics;
* reuse execution-owned sessions rather than opening one per item;
* cancellation stops queued requests;
* retries are bounded and policy-driven;
* retry reuses the same execution-derived idempotency/provenance identity where the HTTP
  operation is side-effecting.

Generic retry semantics remain aligned with execution/orchestration contracts; this section
only specializes HTTP rate-limit behavior.

## 14. R9 — schema observations

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

## 15. Source versus transformation responsibilities

```text
REST source owns
    HTTP request
    declared credential/session resource use
    pagination
    REST cursor extraction
    response record extraction

execution/state contract owns
    FeedResult / FeedState
    StateStore CAS
    persisted source position
    checkpoint boundaries
    identity / generation
    commit ordering

monitoring owns
    dedupe
    change detection
    observation policy

Riko pipes own
    filtering
    mapping
    joins
    explicit fan-out
    enrichment
    aggregation
    validation hooks
    anomaly/change processing

tabular-interop owns
    Pandas / Arrow / Polars boundaries

sink/connectors own
    destination protocol and delivery semantics
```

## 16. dlt/dltHub lessons

Borrow from dlt:

* declarative REST resources;
* paginator strategy vocabulary;
* dependent endpoint resources;
* incremental cursor configuration.

Its broad Python/tabular input ergonomics are relevant, but implementation belongs in
`tabular-interop.md`, not this REST plan.

Borrow from dltHub conceptually:

* deployment/scheduling belongs above the extraction library;
* persisted source state should survive scheduled runs when a persistent `StateStore` is
  configured.

Do not copy destination/schema-loading as Riko's primary execution model.

## 17. Singer lessons

Borrow:

* explicit replication/source state;
* clean source/destination capability separation;
* resumability expectations.

Do not require newline-delimited Singer messages or tap/target subprocess boundaries for
ordinary in-process execution.

## 18. Interaction with monitored feeds

```text
periodic finite poll
→ REST cursor extraction
→ FeedState / StateStore lifecycle
→ optional dedupe / changed
→ anomaly / filter
→ explicit fan-out
```

Repeated acquisition uses the shared poll vocabulary:

```python
Pipeline.poll(source, interval=60)
```

If an API has a reliable cursor, dedupe may be unnecessary. If the cursor reports changed
entities, `changed` may still be useful for selected business fields.

Incremental extraction and change detection are not synonyms.

## 19. Interaction with workflow definitions

REST plans, paginator configuration, endpoint dependencies, and cursor configuration are
serializable in full workflow definitions.

Dependency extraction should report:

```text
external HTTP origins
credential references
parent REST resources
dependent endpoint edges
stateful owner/checkpoint identities
```

Compiled Python must retain equivalent source semantics.

## 20. Tabular interoperability

REST remains record-oriented by default. Batch mode is enabled through the ordinary
`Pipeline` contract rather than REST-specific frame conversion or a parallel `BatchPipe`:

```python
flow = Pipeline("rest", conf=conf, batch=True, batch_size=1000)
```

The negotiated representation/backend and Pandas/Arrow/Polars conversion details belong
to `tabular-interop.md` / `execution-semantics.md`.

## 21. Observability

Emit metrics/events for:

* requests attempted/succeeded/failed;
* pages fetched;
* records emitted;
* retries and rate-limit delay;
* candidate cursor before/after;
* state/checkpoint commit outcome through the shared `StateStore` layer;
* dependent-resource request count;
* response bytes;
* schema fingerprint changes.

Tabular materialization metrics belong to `tabular-interop.md`.

Never expose authorization headers or credential values.

## 22. Testing strategy

Required deterministic fixtures:

1. JSON object source;
2. array source;
3. nested `data_path` extraction;
4. next-URL pagination;
5. page-number pagination;
6. offset/limit pagination;
7. repeated-cursor loop detection;
8. bearer/API-key credential resolution without serialized secret;
9. monotonic timestamp cursor resume using `FeedState` / `StateStore`;
10. compound timestamp/id tie handling;
11. failed handoff does not commit a candidate cursor;
12. CAS conflict leaves committed state unchanged and propagates;
13. dependent parent/child endpoint execution;
14. bounded child-request concurrency;
15. `Retry-After` / rate-limit behavior;
16. serialized workflow compiles and preserves REST semantics.

Frame/batch representation tests live in `tabular-interop.md`.

## 23. Phases

```text
R0  RestSourcePlan
R1  first-class rest module
R2  response data selection
R3  pagination strategies
R4  connector credential/resource integration
R5  FeedState incremental cursor extraction
R6  compound/opaque cursor strategies
R7  dependent endpoints
R8  request concurrency/rate limits
R9  schema observations/drift integration
```

## 24. Definition of done

1. Common REST APIs can be ingested without custom pagination loops.
2. `Pipeline("rest", ...)` and `{"type":"rest", ...}` are the canonical module forms.
3. Credentials remain references resolved through declared resources.
4. REST cursor state uses `FeedState` / `StateStore` and commits only at valid lifecycle
   boundaries.
5. Compound cursors prevent timestamp-boundary data loss where configured.
6. Dependent endpoints are represented as ordinary Riko topology with deterministic
   provenance.
7. REST request concurrency and rate limits are bounded and observable.
8. REST source configuration works in Python and serialized workflow definitions.
9. Pandas/Arrow/Polars behavior is referenced, not duplicated, from `tabular-interop.md`.
10. Riko remains a record-processing library rather than a destination-first loader.
