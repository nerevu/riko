# Riko Provider Integration, Auth, and External Action Gameplan

## 1. Mission

Define reusable provider semantics for authenticated SaaS APIs, resource CRUD/search,
webhooks, caching, idempotent writes, identity mapping, browser fallback, and asynchronous
provider operations without recreating the monolithic API gateways found in earlier Nerevu
projects.

This plan owns **provider semantics**, not generic transport, secrets, REST pagination,
retry, monitoring checkpoints, or the common capability catalog.

Related authoritative plans:

* `connectors.md` — transport/session lifecycle and credential references/resolution;
* `rest-incremental.md` — REST collection, pagination, dependent endpoints, cursor encoding;
* `feed-monitoring.md` — source checkpoints, dedupe/change/anomaly monitoring state;
* `execution-semantics.md` — retry, timeout, cancellation, and error policy;
* `mcp.md` — common `CapabilityInfo`, effects, catalog, policy, and OpenAPI projection;
* `orchestration.md` — durable run boundaries and external scheduling.

## 2. Inspiration integrated by this plan

Reusable lessons from the inspiration corpus include:

* **HTTPSanction / authorizer / nerevu-api** — auth lifecycle, provider-scoped resources,
  normalized CRUD/search, webhooks, cache control, and provider adapters;
* **data-hub-etl** — mapped extraction plus batched provider writes;
* **ckanutils / ckanny** — CKAN operations and hash-aware smart updates;
* **Amazon/eBay search APIs** — provider search vocabularies, pagination, environments,
  caching, and discoverability;
* **extractor** — bounded multi-provider enrichment, response cache, browser fallback,
  provenance, cleaning, and upsert;
* **COVID19/HDX services** — queued long-running operations, IDs, status/result endpoints,
  timeouts, and TTLs;
* **webhooks** — provider signature verification before normalized dispatch;
* **contacts integrations** — OAuth-backed resource discovery, stable identity mapping,
  batch updates, and PII-aware records.

The common lesson is a provider capability layer, not a required Flask proxy monolith.

## 3. Ownership boundary

This plan owns:

```text
ProviderSpec / ResourceSpec / ActionSpec
provider-facing auth lifecycle projection
provider environment selection
resource CRUD/search semantics
multi-provider enrichment policy
provider response caching policy
explicit browser fallback
provider batch/write/idempotency policy
IdentityMap
provider webhook EventEnvelope
OperationHandle + wait_operation semantics
provider diagnostics
provider-specific sensitivity/provenance metadata
```

It does not redefine:

```text
CredentialProvider / secret material    connectors.md
REST pagination / source cursor         rest-incremental.md
SourceCheckpoint / observation state    feed-monitoring.md
RetryPolicy / timeout / cancellation    execution-semantics.md
CapabilityInfo / CapabilityCatalog      mcp.md
```

## 4. Architectural rule

```text
provider definition
    ↓
credential reference + policy
    ↓
resource/action semantics
    ↓
shared connector/session service
    ↓
normalized records / action result / OperationHandle
    ↓
shared capability catalog projection
```

Provider packages describe semantics. Core Riko continues to process records.

Do not introduce:

```text
riko → one giant provider proxy service → every external API
```

as a required architecture.

## 5. Package boundaries

Suggested ownership:

```text
riko core
    ExecutionContext
    ordinary record processing
    generic execution/retry primitives

riko-connect
    HTTP/file/storage/mail connectors
    credential-provider integration points
    generic provider adapter helpers

riko-mcp
    CapabilityInfo / CapabilityCatalog
    OpenAPI/MCP projection and execution policy

provider extras
    behavior not faithfully represented by generic REST/OpenAPI
```

A provider-specific adapter is justified by distinctive pagination, streaming, mutation,
state, auth, or operation semantics—not merely a brand name.

## 6. Provider definition

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

Provider definitions may be generated from OpenAPI and then augmented with explicit
provider policy/semantic overrides.

`credential` is a reference only; raw secret material is resolved by `connectors.md`.

## 7. Authentication lifecycle projection

Earlier gateway projects exposed auth/callback/status/refresh/revoke routes. Preserve the
lifecycle without preserving the server shape.

A provider integration may project lifecycle capabilities such as:

```text
authorize/setup
status
refresh
revoke
```

when supported by the credential implementation.

Secret storage, token retrieval, redaction, and serialized credential references are owned
by `connectors.md`. This plan only defines how a provider exposes setup/control operations.

Interactive authorization belongs to setup/control-plane tooling, not an implicit side
effect during record iteration.

## 8. Provider environments

Environment is explicit:

```python
ProviderSpec(
    id="example",
    environment="sandbox",
    ...,
)
```

Typical values may include `production`, `sandbox`, or provider-specific cloud/region
variants.

Environment may select endpoints and credential policy, but must not silently change record
shape, side-effect classification, or test semantics.

Tests prefer deterministic fake/recorded transports rather than hidden execution branches.

## 9. Resource and action semantics

Normalize common operations without pretending every provider implements all of them:

```text
list
get
create
update
upsert
delete
search
custom action
```

A `ResourceSpec`/`ActionSpec` describes provider identity, supported operations, and
provider-specific parameters. Generic input/output schemas, effects, policy, and catalog
identity are projected into `CapabilityInfo` from `mcp.md` rather than duplicated here.

Natural-name/URL lookups may be convenience resolvers, but mutation should resolve to a
stable provider identity first.

## 10. Search and collection operations

Provider search vocabularies may be richer than a generic HTTP request:

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

The implementation may still use generic REST/OpenAPI machinery.

Pagination, rate limiting, dependent endpoints, and incremental cursor encoding defer to
`rest-incremental.md`; durable source-position state defers to `feed-monitoring.md`.

## 11. Multi-provider enrichment

A reusable pattern is:

```text
base records
→ selected enrichment providers
→ merge normalized fields + provenance
→ clean
→ optional upsert
```

Selection is explicit:

```python
providers={
    "allow": ["sam", "highergov", "apollo"],
    "deny": ["browser-only-provider"],
}
```

Requirements:

* allow/deny selection is deterministic;
* each provider result carries provenance;
* required and optional provider failures are distinguishable;
* concurrent calls are bounded;
* cache hits/misses are observable;
* merge precedence is explicit;
* providers cannot silently overwrite higher-priority data.

## 12. HTTP caching and conditional requests

Provider response caching is an optimization, not correctness state.

Prefer standard validators when available:

```text
ETag
Last-Modified
provider version IDs
```

Requirements:

* cache key/namespace derivation is stable and inspectable;
* cache bypass/refresh is available for troubleshooting;
* response cache is distinct from source checkpoints and identity maps;
* credentials are never cached in ordinary result records;
* connector response/session rules still come from `connectors.md`.

## 13. Browser fallback

Browser automation is optional and explicit when no stable API is available.

Rules:

* REST execution never silently launches a browser;
* credentials remain references;
* browser contexts are execution-scoped resources;
* contexts close on success, error, timeout, or cancellation;
* concurrency is tightly bounded;
* plan/events disclose browser fallback;
* rendered-page parsing remains a downstream parser where practical.

## 14. Batched mutations

Remote writes may expose provider-native batch endpoints:

```python
batch={
    "max_items": 500,
    "max_bytes": 5_000_000,
    "flush_interval": 2.0,
}
```

Batching must preserve provider ordering/idempotency rules and expose item-level partial
failures where the provider permits it.

Do not materialize an unbounded stream solely to use a provider batch endpoint.

Generic batch execution semantics belong to the runtime/RDP plans; this section only owns
provider batch limits and response interpretation.

## 15. Idempotent and change-aware writes

Generalize the CKAN-style persisted-hash pattern as provider sink policy:

```python
write_policy="if_changed"
fingerprint={
    "algorithm": "sha256",
    "canonicalization": "records-v1",
}
```

Possible policies:

```text
always
if_changed
upsert
create_only
update_only
```

`if_changed` requires a comparable committed or provider-native version/fingerprint.
Prefer ETags/version IDs over redownloading content solely to hash it when equivalent safety
is available.

Artifact content fingerprinting/lineage is owned by `artifact-conversion.md`; this section
owns the **remote write decision**.

## 16. Identity mapping

Provider synchronization often needs durable local-to-remote identity mapping:

```python
class IdentityMap(Protocol):
    async def get_remote(self, provider: str, local_id: str) -> str | None: ...
    async def set_remote(self, provider: str, local_id: str, remote_id: str) -> None: ...
```

Prefer provider-native external IDs/upsert keys when available.

Identity mapping is application/provider state. It is distinct from:

```text
source checkpoint      where acquisition resumes
response cache         acquisition optimization
observation state      whether an entity changed
artifact version       durable output identity
```

## 17. Webhook ingress

Normalize provider webhook processing as:

```text
raw request bytes + headers
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

Provider signature algorithms belong to adapters and use exact raw bytes when required.

Never route an arbitrary URL-supplied function/import name directly to Python execution.
Dispatch only to registered, policy-authorized capability or pipeline IDs.

## 18. Asynchronous provider operations

Long-running actions use one provider-neutral contract:

```python
@dataclass(frozen=True, slots=True, kw_only=True)
class OperationHandle:
    provider: str
    operation_id: str
    status_capability: str
    result_capability: str | None = None
    correlation_id: str | None = None
```

A provider adapter owns:

* deriving the operation ID/status/result endpoint;
* normalizing provider status;
* defining provider terminal states;
* extracting result references/request IDs.

The shared waiter owns lifecycle:

```python
result = await wait_operation(
    handle,
    mode="interval",  # interval | event | hybrid
    interval=30,
    timeout=900,
    context=context,
)
```

### Interval mode

Periodically read the authoritative status capability until terminal state or timeout.

### Event mode

Wait for a correlated provider event, then re-read authoritative status. Event payloads are
wake-up hints unless the provider contract explicitly guarantees they are authoritative.

### Hybrid mode

Wait for either a correlated event or the interval deadline, then re-read authoritative
status. This is preferred when notifications may be delayed/dropped but can reduce polling
latency/cost.

Rules:

* subscribe before starting an operation when required to avoid a notification race;
* use caller/provider correlation IDs when the final operation ID does not yet exist;
* unrelated events do not satisfy the waiter;
* timeout/cancellation follow `execution-semantics.md`;
* transient status-read retries use `RetryPolicy` from `execution-semantics.md`;
* only the provider adapter defines terminal status mapping;
* the waiter never owns scheduling of future independent pipeline runs.

This contract is deliberately named **operation waiting**, not source polling. Periodically
checking a data source for new records remains `feed-monitoring.md`.

## 19. Retry ownership

Provider adapters classify failures and supply provider hints; `execution-semantics.md` owns
`RetryPolicy` and retry ordering.

Examples of provider hints/classification:

```text
Retry-After
HTTP transient/permanent classification
provider throttle codes
provider-specific conflict/eventual-consistency signals
```

Do not wrap a capability in an independent retry loop when Riko is already applying its
configured retry policy.

## 20. Provider diagnostics

Control-plane operations may include:

```text
auth/credential status
connectivity check
provider resource/action list
cache status/invalidate
rate-limit status
queued-operation status
```

They are diagnostics/control-plane capabilities, not user data records.

## 21. Capability catalog projection

`mcp.md` owns the common capability model and catalog.

Provider resources/actions project into that model:

```text
ProviderSpec / ResourceSpec / ActionSpec
→ CapabilityInfo / provider-specific CapabilitySpec
→ CapabilityCatalog
→ CLI / MCP / docs / agents
```

Do not maintain a second provider-only catalog containing duplicate fields such as input
schema, output shape, effects, boundedness, credential kind, or description.

Provider-specific semantics that are not generic catalog fields remain on the provider
spec and are referenced by capability identity.

## 22. PII and sensitive-resource metadata

Provider records may contain personal, financial, or administrative data.
Provider-specific metadata may augment shared capability policy with hints such as:

```python
sensitivity="personal"
fields={"email": "pii", "phone": "pii"}
```

These hints inform logging/redaction/artifact policy without changing ordinary record
semantics. Raw PII should not be copied into diagnostics by default.

## 23. Testing strategy

Contract tests should cover:

1. provider spec serialization without secret material;
2. auth setup/status/refresh/revoke projection uses connector credentials;
3. sandbox/production endpoint selection;
4. resource CRUD/search semantics project to the common catalog;
5. search pagination uses shared REST machinery;
6. bounded multi-provider enrichment with deterministic merge precedence;
7. HTTP validator/cache behavior distinct from checkpoint state;
8. explicit browser-fallback lifecycle;
9. partial provider batch-write failures;
10. `if_changed` suppresses identical writes;
11. identity-map-backed upsert survives recreation;
12. webhook signature/replay validation precedes dispatch;
13. unregistered webhook targets cannot execute;
14. `OperationHandle` status/result normalization;
15. interval/event/hybrid wait modes re-read authoritative status;
16. operation waiter respects timeout/cancellation and shared RetryPolicy;
17. provider adapters do not create nested retry loops;
18. provider projections use the common capability catalog;
19. logs redact credentials and sensitive payload fields.

## 24. Phases

```text
P0  ProviderSpec / ResourceSpec / ActionSpec
P1  auth lifecycle projection
P2  resource CRUD/search semantics
P3  cache + HTTP validator policy
P4  batch and idempotent write policy
P5  identity mapping and upsert
P6  multi-provider enrichment service
P7  explicit browser fallback
P8  verified webhook EventEnvelope
P9  OperationHandle + wait_operation
P10 provider diagnostics + capability projection
P11 sensitivity/provenance metadata
```

## 25. Definition of done

1. A provider integration is an adapter/capability, not a mandatory proxy service.
2. Raw credentials never enter provider specs or serialized workflows.
3. Common resource operations share semantics without erasing provider differences.
4. REST pagination/cursors, checkpoint state, retry, and capability metadata reuse their
   authoritative gameplans.
5. Multi-provider enrichment has explicit selection, provenance, and merge policy.
6. Browser automation is explicit and optional.
7. Remote writes can be batched, upserted, and skipped when unchanged.
8. Webhooks verify/authenticate before registered dispatch.
9. Long-running actions use one `OperationHandle`/`wait_operation` contract.
10. CLI, MCP, docs, and agents discover provider operations through the shared capability
    catalog rather than a second provider registry.
11. Provider-specific dependencies remain outside core unless broadly justified.
