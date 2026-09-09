# Provider integrations gameplan

## 1. Mission

Define reusable provider semantics for authenticated SaaS APIs, resource CRUD/search,
webhooks, caching, idempotent writes, identity mapping, browser fallback, asynchronous provider
operations, and provider-specific import/export/deployment hooks without recreating the monolithic
API gateways found in earlier Nerevu projects.

This plan exists so provider packages can expose authoritative platform facts and target-specific
mechanics through one adapter model while Riko Core remains provider-neutral and higher layers can
reuse those facts for capability discovery, Operations as Code, migration, and orchestration.

This plan owns **provider semantics**, including provider-specific extraction/deployment and
compatibility facts. It does not own generic transport, secrets, REST pagination, retry, monitoring
persistence, the common capability catalog, or the common Operations as Code import/compatibility
model.

Related authoritative plans:

* `connectors.md` — transport/session lifecycle and credential references/resolution;
* `rest-incremental.md` — REST collection, pagination, dependent endpoints, cursor encoding;
* `feed-monitoring.md` — dedupe/change/anomaly monitoring policy;
* `execution-semantics.md` — `Context`, resources, `StateStore`, identity/idempotency, retry,
  timeout, cancellation, and error policy;
* `mcp.md` — common `CapabilityInfo`, `CapabilityCatalog`, discovery, effects, policy, and OpenAPI
  projection;
* `operations-as-code.md` — common `OperationSpec`/`OperationPlan`, imported-operation provenance,
  normalization/lossiness, `CompatibilityReport`, deployment identity, and automation drift;
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
provider batch/write policy
IdentityMap logical semantics
provider webhook EventEnvelope
OperationHandle + wait_operation semantics
provider diagnostics
provider-specific sensitivity/provenance metadata
provider-specific operation-asset discovery/acquisition hooks
provider-specific operation export/deployment hooks
provider-specific target capability/compatibility facts
provider deployment inspection/identity hooks
```

It does not redefine:

```text
CredentialProvider / secret material       connectors.md
REST pagination / source cursor            rest-incremental.md
FeedState / StateStore / checkpoints       execution-semantics.md
monitoring observation policy              feed-monitoring.md
RetryPolicy / timeout / cancellation       execution-semantics.md
CapabilityInfo / CapabilityCatalog         mcp.md
capability discovery/catalog construction  mcp.md
OperationSpec / OperationPlan              operations-as-code.md
import provenance/lossiness model          operations-as-code.md
CompatibilityReport / automation drift     operations-as-code.md
scheduling / durable runner boundaries     orchestration.md
```

A provider package supplies facts and mechanics. Higher layers own the cross-provider models that
consume them.

## 4. Architectural rule

```text
provider definition
    ↓
credential reference + policy
    ↓
resource/action semantics
    ↓
declared Context resources + execution-owned connector session
    ↓
normalized records / action result / OperationHandle
    ↓
shared capability catalog projection
```

For Operations as Code import/deployment:

```text
provider-native automation asset
    ↓ provider-specific discover/acquire
source artifact + provider metadata
    ↓ operations-as-code normalization
OperationSpec / CompatibilityReport
    ↓ provider-specific export/deploy
provider-native derived automation
    ↓ provider-specific inspect
source/deployment identity facts
    ↓ operations-as-code drift comparison
```

Provider packages describe semantics. Core Riko continues to process records.

Do not introduce:

```text
riko -> one giant provider proxy service -> every external API
```

or a provider-owned parallel Operations as Code model.

## 5. Package boundaries

Suggested ownership:

```text
riko core
    immutable Context + Resource definitions
    private SyncExecution / AsyncExecution runtime
    ordinary Pipeline record processing
    identity / StateStore / retry primitives

riko-connect
    HTTP/file/storage/mail connectors
    credential-provider integration points
    generic provider adapter helpers

riko-mcp
    CapabilityInfo / CapabilityCatalog
    discovery + OpenAPI/MCP projection + execution policy

riko-ops
    OperationSpec / OperationPlan
    normalized import/provenance/lossiness
    CompatibilityReport / deployment drift

provider extras
    behavior not faithfully represented by generic REST/OpenAPI
    provider-native automation import/export/deployment/inspection
```

There is no public `ExecutionContext`. A provider-specific adapter is justified by distinctive
pagination, streaming, mutation, state, auth, operation, automation-asset, or deployment semantics —
not merely a brand name.

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

`credential` is a reference only; raw secret material is resolved by declared resources
through `connectors.md`.

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
effect during item iteration.

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
flow.capability("ebay.search", conf={"query": "...", "limit": 100, "sort": "price"})
```

The implementation may still use generic REST/OpenAPI machinery.

Pagination, rate limiting, dependent endpoints, and incremental cursor encoding defer to
`rest-incremental.md`; durable source position uses the common `FeedState` / `StateStore`
contract.

## 11. Multi-provider enrichment

A reusable pattern is:

```text
base records
-> selected enrichment providers
-> merge normalized fields + provenance
-> clean
-> optional upsert
```

Selection is explicit:

```python
providers = {"allow": ["sam", "highergov", "apollo"], "deny": ["browser-only-provider"]}
```

Requirements:

* allow/deny selection is deterministic;
* each provider result carries provenance;
* required and optional provider failures are distinguishable;
* concurrent calls are bounded;
* cache hits/misses are observable;
* merge precedence is explicit;
* providers cannot silently overwrite higher-priority data.

N-to-1/N-to-N enrichment provenance follows the common generation/combine rules rather than
creating provider-specific record identities.

## 12. HTTP caching and conditional requests

Provider response caching is an optimization, not correctness/recovery state.

Prefer standard validators when available:

```text
ETag
Last-Modified
provider version IDs
```

Requirements:

* cache key/namespace derivation is stable and inspectable;
* cache bypass/refresh is available for troubleshooting;
* response cache is distinct from committed `StateStore` source/recovery state;
* credentials are never cached in ordinary result records;
* connector response/session rules still come from `connectors.md`.

## 13. Browser fallback

Browser automation is optional and explicit when no stable API is available.

Rules:

* REST execution never silently launches a browser;
* credentials remain references;
* browser clients/contexts are declared resources;
* live contexts are execution-owned and close on success, error, timeout, or cancellation;
* concurrency is tightly bounded;
* plans/events disclose browser fallback where relevant;
* rendered-page parsing remains a downstream parser where practical.

## 14. Batched mutations

Remote writes may expose provider-native batch endpoints:

```python
batch = {"max_items": 500, "max_bytes": 5_000_000, "flush_interval": 2.0}
```

Provider-native batching must preserve ordering/idempotency rules and expose item-level
partial failures where the provider permits it.

Do not materialize an unbounded stream solely to use a provider batch endpoint. Generic
batch execution uses the single `Pipeline(batch=True, ...)` model from
`execution-semantics.md`; there is no provider `BatchPipe` contract.

## 15. Idempotent and change-aware writes

Possible provider write policies:

```text
always
if_changed
upsert
create_only
update_only
```

`if_changed` requires a comparable committed/provider-native version or content fingerprint.
Prefer ETags/version IDs over redownloading content solely to hash it when equivalent safety
is available.

Provider content hashing is distinct from Riko's canonical identity digest. Riko-generated
idempotency identity is derived centrally from:

```text
(node_id, fingerprint, item_key, generation, iteration)
```

A provider sink declares whether/how its backend genuinely honors that idempotency key.
Retryable/resumable validation fails when a side effect cannot honor idempotency unless the
node explicitly opts out:

```python
.write(..., require_idempotency=False)
```

Artifact content fingerprinting/lineage is owned by `artifact-conversion.md`; this section
owns the **remote write decision**.

## 16. Identity mapping

Provider synchronization often needs durable local-to-remote identity mapping. Keep a
provider-friendly logical facade:

```python
class IdentityMap(Protocol):
    async def get_remote(self, provider: str, local_id: str) -> str | None: ...
    async def set_remote(
        self, provider: str, local_id: str, remote_id: str
    ) -> None: ...
```

Prefer provider-native external IDs/upsert keys when available.

When Riko owns persistence for an identity map, back it with the common `StateStore` rather
than defining an independent generic key/value persistence protocol. A provider/application
may also supply an external `IdentityMap` resource whose lifecycle/storage semantics it owns.

Identity mapping remains logically distinct from:

```text
source position       where acquisition resumes
response cache         acquisition optimization
observation state      whether an entity changed
artifact version       durable output identity
operation deployment   where a derived automation lives
```

## 17. Webhook ingress

Normalize provider webhook processing as:

```text
raw request bytes + headers
-> provider signature verification
-> replay/idempotency validation
-> EventEnvelope
-> registered capability/PipelineRef
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
Dispatch only to registered, policy-authorized capability or pipeline IDs/references.

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

Here `context` is the public immutable `Context`; execution-owned resource/session handles
are resolved privately when the capability runs.

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
* transient status-read retries use the common `RetryPolicy`;
* only the provider adapter defines terminal status mapping;
* the waiter never owns scheduling of future independent pipeline runs.

This contract is deliberately named **operation waiting**, not source polling. Periodically
checking a data source for new records remains `Pipeline.poll(...)` / `feed-monitoring.md`.

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
configured retry policy. State-store `CheckpointConflictError` is not an instruction for a
provider adapter to reload/rerun automatically.

## 20. Provider diagnostics

Control-plane operations may include:

```text
auth/credential status
connectivity check
provider resource/action list
cache status/invalidate
rate-limit status
queued-operation status
automation-asset inventory where supported
deployment inspection where supported
```

They are diagnostics/control-plane capabilities, not user data records or a second Operations as
Code service.

## 21. Capability catalog projection and discovery

`mcp.md` owns the common capability model, discovery contract, and catalog.

Provider resources/actions project into that model:

```text
ProviderSpec / ResourceSpec / ActionSpec
-> CapabilityInfo / provider-specific CapabilitySpec
-> CapabilityCatalog
-> CLI / MCP / docs / agent-oriented Pipelines / OperationPlan resolution
```

A provider adapter may **discover provider-native resources/actions** and project their facts, but it
must not maintain a second provider-only capability catalog containing duplicate fields such as
input schema, output shape, effects, boundedness, credential kind, or description.

Provider-specific semantics that are not generic catalog fields remain on the provider
spec and are referenced by capability identity. Operations as Code resolves required target
capabilities against the shared `CapabilityCatalog`; it does not ask providers to invent a parallel
operation capability registry.

## 22. Operations as Code import/export and compatibility hooks

Provider integrations own target-specific mechanics needed to get operational knowledge into or out
of proprietary platforms. The common normalized models remain in `operations-as-code.md`.

A provider package may expose reusable services shaped around:

```text
discover operation assets
acquire/export original source artifact
map provider-native fields/actions to known semantic facts
report provider-native target capabilities/constraints
compile/export a normalized operation for that target
deploy/update a derived target object
inspect the deployed target object and its fingerprints/metadata
```

Examples of provider-native assets include scripts, workflow definitions, automation steps,
policies, monitor/remediation rules, scheduled jobs, runbooks, and provider variables.

Rules:

* extraction preserves original source bytes/text and stable provider identity when available;
* provider packages may report **mapping facts and constraints**, not a provider-local
  `CompatibilityReport`;
* `operations-as-code.md` owns normalization confidence/lossiness, `CompatibilityReport`, and the
  decision that a mapping is exact/partial/manual/unsupported;
* export/deployment never mutates the canonical `OperationSpec` to match a target silently;
* generated target objects carry source revision/fingerprint metadata where the target permits it;
* deployment inspection returns target identity/fingerprint facts that Operations as Code compares
  for automation drift;
* import/export/deploy actions project into the shared capability policy model when they are exposed
  as executable capabilities;
* raw credentials and provider session objects never enter imported artifacts or operation specs.

A provider may support only import, only deployment, both, or neither. Missing support is an explicit
compatibility fact, not an error in Core.

## 23. PII and sensitive-resource metadata

Provider records and imported operational artifacts may contain personal, financial,
administrative, or secret-adjacent data. Provider-specific metadata may augment shared capability
policy with hints such as:

```python
sensitivity = "personal"
fields = {"email": "pii", "phone": "pii"}
```

These hints inform logging/redaction/artifact policy without changing ordinary record semantics.
Raw PII, tokens, embedded passwords, or secret-bearing script values should not be copied into
diagnostics, compatibility reports, or imported-operation metadata by default.

## 24. Testing strategy

Contract tests should cover:

1. provider spec serialization without secret material;
2. auth setup/status/refresh/revoke projection uses connector credentials;
3. sandbox/production endpoint selection;
4. resource CRUD/search semantics project to the common catalog;
5. search pagination uses shared REST machinery;
6. bounded multi-provider enrichment with deterministic merge precedence/provenance;
7. HTTP validator/cache behavior distinct from `StateStore` state;
8. explicit browser-fallback lifecycle via declared resources;
9. partial provider batch-write failures;
10. `if_changed` suppresses identical writes;
11. execution-derived idempotency key remains stable across retry;
12. unsupported idempotency fails retryable/resumable validation unless opted out;
13. identity-map-backed upsert survives recreation;
14. webhook signature/replay validation precedes dispatch;
15. unregistered webhook targets cannot execute;
16. `OperationHandle` status/result normalization;
17. interval/event/hybrid wait modes re-read authoritative status;
18. operation waiter respects timeout/cancellation and shared RetryPolicy;
19. provider adapters do not create nested retry loops;
20. provider projections use the common capability catalog;
21. provider operation-asset discovery preserves original artifact/provider identity;
22. provider compatibility hooks return target facts without constructing a competing
    `CompatibilityReport`;
23. provider export/deployment records source revision/fingerprint when supported;
24. deployment inspection distinguishes target identity/fingerprint from canonical operation
    identity;
25. imported/deployment diagnostics redact credentials and sensitive payload fields.

Cross-provider normalization and RMM-to-RMM compatibility tests belong to
`operations-as-code.md`; this plan tests only the provider specialization.

## 25. Phases

```text
P0  ProviderSpec / ResourceSpec / ActionSpec
P1  auth lifecycle projection + Context resource bindings
P2  resource CRUD/search semantics
P3  cache + HTTP validator policy
P4  provider batch + common idempotency policy
P5  identity mapping/upsert backed by StateStore or external resource
P6  multi-provider enrichment service
P7  explicit browser fallback
P8  verified webhook EventEnvelope
P9  OperationHandle + wait_operation
P10 provider diagnostics + capability projection
P11 sensitivity/provenance metadata
P12 operation-asset discovery/acquisition hook
P13 target compatibility-facts + export/deployment/inspection hook
```

## 26. Definition of done

1. A provider integration is an adapter/capability, not a mandatory proxy service.
2. Raw credentials never enter provider specs, serialized workflows, or imported operation
   artifacts/metadata.
3. Common resource operations share semantics without erasing provider differences.
4. REST pagination/cursors, `FeedState`/`StateStore`, retry, and capability metadata reuse
   their authoritative contracts.
5. Provider clients/browser contexts are declared resources with execution-owned lifecycle.
6. Multi-provider enrichment has explicit selection, provenance, and merge policy.
7. Browser automation is explicit and optional.
8. Remote writes can be batched, upserted, skipped when unchanged, and participate in the
   common idempotency contract.
9. Webhooks verify/authenticate before registered dispatch.
10. Long-running actions use one `OperationHandle`/`wait_operation` contract.
11. CLI, MCP, docs, agents, and Operations as Code discover provider operations through the shared
    capability catalog rather than a second provider registry.
12. Provider packages can expose import/export/deployment/inspection hooks without owning
    `OperationSpec`, `OperationPlan`, `CompatibilityReport`, or automation-drift semantics.
13. A provider-specific migration/deployment adapter reports semantic loss and unsupported target
    facts rather than silently rewriting the canonical operation.
14. Provider-specific dependencies remain outside core unless broadly justified.
