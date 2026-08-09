# Riko Provider Integration, Auth, and External Action Gameplan

## 1. Mission

Define a reusable provider-integration layer for authenticated SaaS APIs, resource CRUD,
webhooks, cached acquisition, idempotent writes, and asynchronous provider jobs without
recreating the monolithic API gateways found in several earlier Nerevu projects.

This plan extends:

* `_docs/gameplans/connectors.md` for transport/session/credential contracts;
* `_docs/gameplans/rest-incremental.md` for declarative REST collection semantics;
* `_docs/gameplans/mcp.md` for capability projection and policy;
* `_docs/gameplans/orchestration.md` for webhook-triggered and queued executions.

## 2. Inspiration integrated by this plan

The inspiration corpus contains repeated versions of the same useful architecture:

* **HTTPSanction / authorizer / nerevu-api**: normalized OAuth/API-key/service-account
  authentication, provider-scoped resources, auth status/refresh/revoke, CRUD, webhooks,
  cache management, and provider adapters.
* **data-hub-etl**: API acquisition plus configuration-driven mappings and batched Google
  Sheets writes.
* **ckanutils / ckanny**: CKAN resource/package operations and hash-aware smart updates.
* **amzn-search-api / ebay-search-api**: provider search wrappers, cache policies,
  pagination, explicit sandbox/live behavior, and discoverable resource APIs.
* **extractor**: async multi-provider enrichment with allow/deny selection, response cache,
  browser fallback, cleaning, and Airtable upsert.
* **COVID19 IL Data API / HDX ageing service**: interchangeable source/destination
  backends, queued long-running work, job IDs, status/result endpoints, timeout/TTL.
* **webhooks**: provider-specific signature verification followed by normalized dispatch.
* **Google contacts / contacts**: OAuth-backed resource discovery, natural-name/ID/URL
  addressing, batch updates, and PII-aware records.
* **HDX scrapers / file proxy**: many source-specific collectors normalized behind common
  output contracts rather than promoted to core modules.

The common lesson is a provider capability model, not a new Flask monolith.

## 3. Architectural rule

```text
provider definition
    ↓
credential reference + policy
    ↓
resource/action capability
    ↓
shared connector/session service
    ↓
normalized records / action result / job handle
```

Provider packages describe semantics. Core Riko continues to process records.

Do not introduce:

```text
riko → one giant provider proxy service → every external API
```

as a required architecture.

## 4. Package boundaries

Suggested ownership:

```text
riko core
    ExecutionContext
    capability metadata contracts
    ordinary record processing
    generic retry/poll hooks when broadly useful

riko-connect
    HTTP/file/storage/mail/CKAN/Google-Sheets-style connectors
    credential-provider integration points
    provider resource/action registry
    caching and idempotent write helpers

riko-mcp
    OpenAPI/MCP-derived capabilities
    capability policy and agent-facing projection

provider extras
    behavior that cannot be represented faithfully through generic REST/OpenAPI
```

A provider-specific module is justified when protocol, pagination, streaming, mutation, or
state semantics require it—not merely because the provider has a brand name.

## 5. Provider definition

Use a serializable provider descriptor:

```python
@dataclass(frozen=True, slots=True, kw_only=True)
class ProviderSpec:
    id: str
    base_url: str | None
    credential: str | None
    resources: tuple[ResourceSpec, ...]
    actions: tuple[ActionSpec, ...]
    environment: str = "production"
```

Provider definitions may be generated from OpenAPI where possible, then augmented with
small explicit policy/semantic overrides.

They must not contain raw secrets.

## 6. Authentication lifecycle

Older gateway projects exposed auth, callback, status, refresh, and revoke as provider
routes. Preserve the lifecycle, not the server shape.

Credential providers should support capabilities such as:

```text
resolve
status
refresh
revoke
```

where supported by the underlying authentication scheme.

Serialized pipelines use references:

```json
{"credential": "providers/xero/accounting"}
```

not client secrets, access tokens, refresh tokens, private keys, or service-account JSON.

Supported auth metadata may include:

```text
API key
basic auth
OAuth 1 where unavoidable
OAuth 2 authorization code
OAuth 2 client credentials
service account/workload identity
bearer token
```

Interactive authorization belongs to setup/control-plane tooling, not an implicit action
inside ordinary record iteration.

## 7. Provider environments

Several inspiration APIs distinguish live, sandbox, development, and offline/test modes.
Make environment explicit:

```python
ProviderSpec(
    id="example",
    environment="sandbox",
    ...,
)
```

Environment selects endpoint/credential policy but must not silently alter record schemas or
side-effect classification.

Tests should prefer deterministic fixtures or recorded/fake transports rather than a hidden
`offline` branch with different execution semantics.

## 8. Resource capability model

Normalize common operations without pretending all providers are identical:

```text
list
get
create
update
upsert
delete
search
```

A resource capability declares which operations exist, its identity fields, pagination,
and side-effect/risk properties.

```python
ResourceSpec(
    id="xero.projects",
    identity=("project_id",),
    operations=frozenset({"list", "get", "create", "update"}),
)
```

Natural-name, ID, or URL lookups may be convenience resolvers, but resolution must end in a
stable provider identity before mutation.

## 9. Search and collection operations

Amazon/eBay-style wrappers show a useful distinction between generic REST requests and a
provider's search vocabulary. Search capabilities may expose typed/queryable parameters:

```python
pipe.capability(
    "ebay.search",
    conf={
        "query": "...",
        "limit": 100,
        "sort": "price",
    },
)
```

The underlying implementation may be generic REST/OpenAPI. Public output remains ordinary
Riko records plus namespaced response metadata.

Pagination, rate limiting, and incremental state defer to `rest-incremental.md`.

## 10. Provider selection for enrichment

Extractor demonstrates a useful multi-provider pattern:

```text
base records
→ selected enrichment providers
→ merge normalized fields/provenance
→ clean
→ upsert
```

Support an explicit provider-selection policy:

```python
providers={
    "allow": ["sam", "highergov", "apollo"],
    "deny": ["browser-only-provider"],
}
```

Requirements:

* allow/deny selection is deterministic;
* each provider result carries provenance;
* failure policy can distinguish required and optional enrichers;
* concurrent provider requests are bounded;
* cache hits/misses are observable;
* one provider cannot silently overwrite higher-priority data without a merge policy.

This belongs in an enrichment/provider extension, not in the core loop decorator.

## 11. HTTP caching and conditional requests

Earlier APIs relied heavily on local/memcached HTTP response caches. Modernize the pattern:

* use standard validators (`ETag`, `Last-Modified`) when provided;
* support bounded response caching through connector policy;
* make cache namespace/key derivation stable and inspectable;
* distinguish response cache from source checkpoint state;
* expose cache bypass/refresh for troubleshooting;
* never cache auth material in ordinary result records.

Caching is an optimization. Incremental/checkpoint semantics remain correctness contracts.

## 12. Browser fallback

Some legacy providers required Selenium/Playwright login or scraping. Browser automation may
exist as an optional connector capability when no stable API exists.

Rules:

* browser use is explicit in the plan;
* a REST connector never silently launches a browser;
* credentials remain references;
* rendered-page extraction remains a downstream parser where practical;
* browser contexts are execution resources and close on cancellation/error;
* concurrency is tightly bounded;
* plans/events identify that browser fallback was used.

## 13. Batched mutations

Google Sheets/contact examples and data-hub-etl show that remote writes often have native
batch semantics.

A sink/action may declare:

```python
batch={
    "max_items": 500,
    "max_bytes": 5_000_000,
    "flush_interval": 2.0,
}
```

Batching must preserve provider ordering/idempotency requirements and report partial
failures at item granularity where the provider supports it.

Do not materialize an unbounded stream solely to use a provider's batch endpoint.

## 14. Idempotent and change-aware writes

CKAN tooling used a persisted content hash so scheduled jobs did not rewrite unchanged
resources. Generalize this as a sink policy:

```python
write_policy="if_changed"
fingerprint={"algorithm": "sha256", "canonicalization": "records-v1"}
```

Possible policies:

```text
always
if_changed
upsert
create_only
update_only
```

`if_changed` requires a comparable committed/remote fingerprint. The fingerprint algorithm
and canonicalization version are metadata, not implicit implementation detail.

Provider-native ETags/version IDs should be preferred over downloading content solely to
compute a comparison hash when they provide equivalent safety.

## 15. Upsert and identity mapping

Provider sync projects repeatedly maintain mappings between local and remote identities.
Define an optional mapping-store contract rather than hiding mapping files in provider code:

```python
class IdentityMap(Protocol):
    async def get_remote(self, provider: str, local_id: str) -> str | None: ...
    async def set_remote(self, provider: str, local_id: str, remote_id: str) -> None: ...
```

Use provider-native external IDs/upsert keys when available. Mapping state is durable
application state, separate from source cursor/checkpoint state.

## 16. Webhook ingress

Normalize webhook processing as:

```text
request bytes + headers
→ provider signature verification
→ replay/idempotency validation
→ EventEnvelope
→ registered capability/pipeline
```

```python
@dataclass(frozen=True, slots=True, kw_only=True)
class EventEnvelope:
    provider: str
    event_id: str
    event_type: str
    occurred_at: datetime | None
    payload: JsonValue
```

Do not route arbitrary URL `func_name` values directly to arbitrary Python functions.
Dispatch only to registered capabilities or pipeline IDs authorized by policy.

Provider-specific signature algorithms belong to adapters and require exact raw request
bytes where the signature scheme specifies them.

## 17. Asynchronous provider jobs

COVID/HDX services expose a useful generic pattern for long operations:

```text
submit action
→ job id / result URL
→ queued/running state
→ bounded wait or later retrieval
```

Define a provider-neutral handle:

```python
@dataclass(frozen=True, slots=True, kw_only=True)
class OperationHandle:
    provider: str
    operation_id: str
    status_capability: str
    result_capability: str | None = None
```

Riko may either emit the handle immediately or pass it to the generic polling/wait contract.
Timeout, status TTL, result TTL, and cancellation are explicit. Redis/RQ is one possible
external implementation, not part of the core contract.

## 18. Provider status and diagnostics

Useful control-plane operations include:

```text
credential/auth status
connectivity check
resource capability list
cache status/invalidate
rate-limit status when exposed
queued-operation status
```

Expose these through CLI/control-plane capability discovery. They should not be mixed into
user data records.

## 19. Discoverability

Many inspiration APIs returned a link index at their root. Preserve the underlying idea as
a capability catalog:

```text
provider
resource/action id
input schema
output shape
side-effect classification
credential reference kind
boundedness
pagination/state support
```

The same catalog should drive CLI help, MCP projection, docs, and agent tool selection.
Do not maintain separate hand-authored registries for each surface.

## 20. PII and sensitive-resource metadata

Contacts and administrative provider records can contain personal or financial data.
Capabilities may declare data classification hints:

```python
sensitivity="personal"
fields={"email": "pii", "phone": "pii"}
```

These hints can inform logging/redaction/artifact policies without changing ordinary record
semantics. Raw PII must not be copied into diagnostic events by default.

## 21. Testing strategy

Contract tests should cover:

1. provider spec serialization without secrets;
2. auth resolve/status/refresh/revoke adapters;
3. sandbox vs production endpoint selection;
4. resource list/get/create/update/upsert/delete capability metadata;
5. search pagination through shared REST machinery;
6. bounded multi-provider enrichment and deterministic merge precedence;
7. HTTP validator/cache behavior;
8. explicit browser fallback lifecycle;
9. partial batch-write failure reporting;
10. `if_changed` suppresses identical writes;
11. changed fingerprints trigger one write;
12. identity-map-backed upsert survives recreation;
13. webhook signature/replay validation precedes dispatch;
14. unregistered webhook function/capability cannot execute;
15. long-running job handle can be polled/cancelled with timeout;
16. capability catalog projects the same underlying service to CLI/MCP/docs;
17. logs redact auth and sensitive payload fields.

## 22. Phases

```text
P0  ProviderSpec / ResourceSpec / ActionSpec
P1  credential lifecycle projection
P2  resource CRUD/search capability projection
P3  cache + HTTP validator policy
P4  batch and idempotent write policy
P5  identity mapping and upsert
P6  multi-provider enrichment service
P7  explicit browser fallback capability
P8  webhook EventEnvelope and verification adapters
P9  OperationHandle and status/result contract
P10 capability catalog / diagnostics / sensitivity metadata
```

## 23. Definition of done

1. A provider integration is a capability/adapter, not a mandatory proxy web service.
2. Raw credentials never enter serialized pipeline definitions.
3. Common resource operations share contracts without erasing provider-specific semantics.
4. REST pagination/incremental behavior reuses the existing REST gameplan.
5. Multi-provider enrichment has explicit selection, provenance, and merge policy.
6. Browser automation is visible and optional.
7. Remote writes can be batched, upserted, and skipped when unchanged.
8. Webhooks verify/authenticate before registered dispatch.
9. Long-running provider actions return inspectable job handles.
10. CLI, MCP, documentation, and agents discover the same capability catalog.
11. Provider-specific dependencies remain outside core unless broadly justified.
