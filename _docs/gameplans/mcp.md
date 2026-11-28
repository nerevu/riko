# MCP gameplan

## 1. Mission

Create an optional `riko-mcp` package that allows Riko to discover, validate, and
execute external capabilities while preserving the immutable `Pipeline` execution model.

The package must support:

1. MCP v2 clients.
2. Native Riko module and export discovery.
3. MCP tool, resource, and resource-template discovery.
4. Dynamic public API discovery through APIs.guru.
5. OpenAPI operation normalization and execution.
6. One unified capability catalog.
7. Immutable execution and discovery plans.
8. Configurable approval and security policies.
9. Large-result artifactization.
10. Deterministic evaluation and telemetry.
11. A later MCP server exposing stable Riko capabilities.

AI ranking, decomposition, synthesis, and verification belong in `riko-ai`, not
`riko-mcp`. Agent-oriented workflows reuse ordinary Riko `Pipeline` definitions; MCP
does not provide an agent graph/runtime.

Operations as Code consumes this package's common capability
discovery/catalog/policy/approval contracts; it does not create an operation-specific
capability catalog or security policy engine.

---

## 2. Prerequisites

Assume Riko provides:

* one reusable immutable `Pipeline[T]` definition;
* private `SyncExecution` / `AsyncExecution` runtimes created by iteration;
* immutable public `Context` and declared `Resource` definitions;
* execution-owned clients/sessions and deterministic cleanup;
* Feed-native async iteration plus a supported sync bridge;
* cancellation/deadline propagation;
* module/export registries;
* common identity/idempotency and retry semantics.

Do not add a second async runtime or private per-package event loop.

---

## 3. Package boundaries

### `nerevu/riko`

Riko core owns:

* Pipeline definition/compilation/execution;
* module/export resolution;
* public immutable `Context` / `Resource` definitions;
* private execution lifecycle and cancellation;
* stream composition and pub/sub protocols;
* sync/async bridging;
* common identity/idempotency/retry/state contracts.

There is no public `ExecutionContext`.

### `nerevu/riko-mcp`

`riko-mcp` owns:

* MCP v2 SDK integration;
* MCP session/transport adapters;
* capability discovery/catalogs;
* APIs.guru/OpenAPI normalization;
* deterministic filtering and plan validation;
* capability execution/approval/security policy;
* result normalization/artifactization;
* audit/telemetry/evaluation;
* future MCP-server projection.

### `nerevu/riko-ai`

`riko-ai` owns model providers, semantic retrieval, AI capability selection,
decomposition, verification, summarization/research, and model routing. It consumes
public `riko-mcp` contracts.

### `nerevu/riko-ops`

Operations as Code owns `OperationSpec`, `OperationPlan`, Git/repository semantics,
operation-level validate/plan/apply/verify coordination, import/normalization,
compatibility, deployment identity, and automation drift. It consumes
`CapabilityCatalog`, `CapabilityPlan`, effects, policy, and approval from this plan
rather than duplicating them.

---

## 4. Source design retained from Langly and AutoGen

Retain declarative discovery, APIs.guru as an API directory, OpenAPI as executable HTTP
contract, explicit tool availability, scenario-based evaluation, structured results,
large-result redirection, and cost/latency/success telemetry.

Do not retain mutable mid-conversation function registration, generated `FunctionType`
objects, code-object mutation, arbitrary model-selected schema/server URLs, prompt-only
security, unrestricted local Python, unbounded retries, or conversational multi-agent
routing as an execution engine.

Replacement:

```text
OpenAPI document
→ immutable OpenApiOperationSpec
→ immutable OpenApiOperationPlan
→ generic validated capability executor
```

---

## 5. Non-negotiable architecture decisions

### 5.1 MCP client before server

```text
client foundation
→ discovery
→ catalog
→ execution
→ OpenAPI discovery/execution
→ production integrations
→ MCP server
```

### 5.2 MCP v2 only

Pin the exact tested v2 prerelease during development, then use a bounded stable-v2
range. Direct SDK imports stay under `riko_mcp/sdk/`; SDK classes do not leak into
public APIs.

### 5.3 Stdio first

Spike in-memory, stdio, and Streamable HTTP. Ship stdio first, Streamable HTTP second,
then remote auth/OAuth. Transport choices never create their own event loop.

### 5.4 One unified capability catalog

The catalog includes native Riko modules/exports, MCP tools/resources/templates, OpenAPI
operations, and provider-projected capabilities. Multi-step AI planning belongs in
`riko-ai`. Operations as Code resolves required capabilities from this same catalog;
operation compatibility may consume catalog facts but does not create another catalog.

### 5.5 No independently persisted derived tags

Origin/kind/effect/runtime facets are computed from typed fields. Only non-derivable
operator labels such as `approved-vendor`, `preferred`, or `production-tested` are
stored.

### 5.6 Discovery, selection, and execution stay separate

```text
discover
→ deterministic filter
→ optional AI proposal
→ validate plan
→ apply policy
→ approval if required
→ execute
```

Selection never performs execution implicitly. An Operations as Code `plan` may
reference one or more validated `CapabilityPlan` values, but the operation lifecycle
uses `apply` for the operation phase; capability `execute` remains this package's term.

### 5.7 Context precedence

```text
package defaults
→ mcp.toml
→ environment interpolation
→ Context overrides
```

A same-name server/resource definition supplied through `Context` replaces the
file-defined entry rather than deep-merging it.

`Context` stores immutable definitions/configuration. Live MCP sessions are
execution-owned resolved resource values, not values mutated onto Context.

### 5.8 Approval

```python
class ExecutionApproval(StrEnum):
    NEVER = "never"
    POLICY = "policy"
    ALWAYS = "always"
```

Default is policy-driven. Known read-only actions may run automatically; unknown effects
and writes require confirmation by default; destructive actions require explicit policy
plus appropriate confirmation/unattended authorization. Model confidence never overrides
policy.

Operations as Code approval may be bound to an `OperationPlan` fingerprint by its owner;
the underlying capability/domain plan identities must remain part of that binding so an
operation cannot use one approval to execute a materially changed capability plan.

### 5.9 Sessions are execution resources

Never establish a new MCP session/subprocess per item. Declare MCP client/session
resources in `Context`; the private execution resolves and owns the live session once
per execution. Externally supplied resources use `Resource.from_external(...)` and are
never closed by Riko.

A module that needs the MCP manager declares it through common `resources=` metadata and
receives the execution-bound resource view through existing wrapper preparation.

### 5.10 MCP is not internal Riko transport

Do not route ordinary `rename`, `filter`, `sort`, `map`, pub/sub, export edges, or
operation repository/deployment metadata through MCP.

---

## 6. Core domain model

Use frozen, slotted, keyword-only public dataclasses. Do not expose MCP SDK models.

```python
class CapabilityOrigin(StrEnum):
    RIKO_MODULE = "riko_module"
    RIKO_EXPORT = "riko_export"
    MCP_TOOL = "mcp_tool"
    MCP_RESOURCE = "mcp_resource"
    MCP_RESOURCE_TEMPLATE = "mcp_resource_template"
    OPENAPI_OPERATION = "openapi_operation"


class CapabilityKind(StrEnum):
    SOURCE = "source"
    PROCESSOR = "processor"
    OPERATOR = "operator"
    AGGREGATOR = "aggregator"
    EXPORT = "export"
    RESOURCE = "resource"
    TOOL = "tool"


class DataShape(StrEnum):
    UNKNOWN = "unknown"
    TEXT = "text"
    JSON = "json"
    RECORD = "record"
    RECORDS = "records"
    BINARY = "binary"
    STREAM = "stream"
    ARTIFACT = "artifact"


@dataclass(frozen=True, slots=True, kw_only=True)
class CapabilityEffects:
    read_only: bool | None = None
    destructive: bool | None = None
    idempotent: bool | None = None
    open_world: bool | None = None
```

Protocol annotations are hints, not proof of safety. Local policy may become more
restrictive but not silently less restrictive.

```python
@dataclass(frozen=True, slots=True, kw_only=True)
class CapabilityInfo:
    id: str
    origin: CapabilityOrigin
    kind: CapabilityKind
    effects: CapabilityEffects
    runtime: str
    input_shape: DataShape
    output_shape: DataShape
    name: str
    title: str | None
    description: str | None
    input_schema: JsonObject
    output_schema: JsonObject | None
    labels: frozenset[str] = frozenset()
```

Capability union:

```python
type CapabilitySpec = (
    NativeModuleSpec
    | NativeExportSpec
    | McpToolSpec
    | McpResourceSpec
    | McpResourceTemplateSpec
    | OpenApiOperationSpec
)
```

Catalog:

```python
@dataclass(frozen=True, slots=True, kw_only=True)
class CapabilityCatalog:
    generation: int
    fingerprint: str
    capabilities: tuple[CapabilitySpec, ...]
    created_at: datetime
```

Catalog serialization/fingerprinting must be deterministic. Computed facets are not
stored independently or accepted as configuration overrides.

---

## 7. Capability providers

```python
class CapabilityProvider(Protocol):
    name: str

    async def discover(
        self, request: CapabilityDiscoveryRequest, *, context: Context
    ) -> CapabilityCatalogFragment: ...
```

`context` is immutable public configuration. Providers needing live clients declare
resources; execution resolves those resource values privately.

Initial providers:

```text
RikoModuleProvider
RikoExportProvider
McpProvider
ApisGuruProvider
OpenApiProvider
```

Provider integrations may also project provider-native resources/actions through this
same contract; provider-specific discovery mechanics remain in
`provider-integrations.md` while catalog identity and conflict resolution remain here.

Catalog construction validates identity conflicts and creates one deterministic catalog
fingerprint using the common Riko fingerprinting contract where applicable.

---

## 8. Plan model

```python
type CapabilityPlan = (
    NativeModulePlan
    | NativeExportPlan
    | McpToolPlan
    | McpResourcePlan
    | OpenApiOperationPlan
)


type SelectionOutcome = CapabilityPlan | CapabilityDiscoveryPlan | NoCapabilityMatch
```

Plans are immutable and carry capability/catalog/schema identity needed for
revalidation. The model may not inject a new base URL/schema URL, undeclared headers,
raw credentials, HTTP method, or schema-invalid arguments.

Discovery plans may expand a catalog but may not execute the final user task.

An `OperationPlan` may reference `CapabilityPlan` values, but it remains a distinct
higher-level contract owned by `operations-as-code.md`; do not broaden `CapabilityPlan`
into a generic operation plan.

---

## 9. Configuration

File configuration contains transport/server definitions and credential **references**,
not resolved secrets. Environment interpolation resolves at configuration assembly
without serializing secrets back into plans/catalogs/audit records/items.

Example Context override:

```python
context = Context(
    resources={"capabilities": capability_manager}  # generator/CM resource definition
)
```

The resource definition/factory may carry immutable MCP server configuration. Live
sessions, secret-provider clients, HTTP clients, and artifact-store clients are resolved
by execution.

Do not describe already-open sessions or mutable runtime credentials as ordinary Context
values.

---

## 10. Public Riko modules

MCP/capability modules are ordinary `Pipeline` modules and use the same definition under
sync and async execution:

```python
catalog = Pipeline.from_module(
    "capabilitycatalog",
    conf={
        "include": {
            "riko_modules": True,
            "riko_exports": True,
            "mcp": True,
            "openapi": False,
        },
        "mcp_servers": ["filesystem", "git", "fetch"],
    },
    context=context,
)
```

Other initial modules:

```text
mcpdiscover
mcpresource
mcpresources
mcptool
capabilitydiscover
capabilityexecute
```

AI-backed capability selection belongs in `riko-ai`. Legacy `SyncPipe` examples may
remain only in compatibility docs, not this target API.

All modules that need MCP/HTTP/provider clients declare resource bindings in module
metadata; they do not fetch live clients by mutating `Context.resources`.

---

## 11. APIs.guru progressive discovery

For a task such as `Convert 100 USD to GBP`:

1. search lightweight directory metadata;
2. shortlist exchange-rate providers;
3. fetch only bounded top-N schemas;
4. normalize compatible operations;
5. allow `riko-ai` to propose one operation;
6. validate plan/catalog/schema fingerprint;
7. apply network/credential policy;
8. execute only after approval requirements are satisfied.

`ApiSummary`, `ApiCandidateSet`, `ApiExpansionPolicy`, and `OpenApiOperationSpec` remain
immutable domain types. Directory summaries are not executable capabilities.

Initial OpenAPI support: 2.0/3.0/3.1, GET, path/query/schema-declared headers,
JSON/text, no-auth/API-key/bearer auth, local/internal refs and explicitly permitted
remote refs. Writes/uploads/callbacks/custom signing may follow after read-only
execution is stable.

---

## 12. Result model

```python
@dataclass(frozen=True, slots=True, kw_only=True)
class CapabilityResult:
    capability_id: str
    content: tuple[CapabilityContent, ...]
    structured: JsonValue | None
    is_error: bool
    metadata: JsonObject
    usage: CapabilityUsage
    artifact: CapabilityArtifact | None = None
```

Extraction modes may include raw/structured/text/content/records/artifact. Never
silently discard non-text blocks.

Keep transport failure, protocol failure, tool-level error, schema failure, policy
rejection, approval requirement, and result-conversion failure distinct.

When a capability is exposed as a Riko source/parser, rich stream metadata/state should
map through the common `FeedResult` model rather than introducing a second source-result
envelope.

---

## 13. Security policies

Execution policy controls allowed servers/capabilities, trust/effects,
open-world/private network access, approval, maximum result size, and timeout.

Schema-discovery policy bounds catalogs/candidates/schema count/schema bytes/redirects
and remote refs.

API policy bounds host/method/private-network/response-size/timeout/approval. A
discovered OpenAPI URL is never automatically added to an execution allowlist.

Stdio commands come only from trusted operator configuration. AI output cannot define
the executable/arguments. Use executable/working-directory allowlists, minimal
environment, bounded stderr, and deterministic child-process cleanup.

Operations as Code must pass through the same policy boundary:

* an imported script/workflow is **data**, not permission to execute it;
* importer/compatibility output cannot add a host, credential, capability, method,
  executable, or effect to an allowlist;
* an operation's required capabilities must resolve through the shared catalog before
  apply;
* target deployment/export is a side effect and receives normal effect/policy/approval
  treatment;
* AI-assisted operation normalization or target mapping is a proposal and cannot reduce
  policy;
* operation/source/deployment fingerprints do not substitute for authorization;
* plan-bound approval is rejected after `OperationPlan` or referenced `CapabilityPlan`
  identity changes.

The Operations as Code layer may be more restrictive, but it cannot silently weaken this
policy.

---

## 14. Session lifecycle

MCP session management is an execution-resource implementation detail, not a second
public lifecycle system.

Requirements:

* reuse one resolved manager/session pool per execution as configured;
* bound concurrent calls per server;
* close owned HTTP clients/subprocesses/sessions on completion/cancellation/error;
* preserve original exceptions;
* do not close externally supplied resources;
* do not expose MCP SDK session types through Riko public APIs.

If call/pipe/pipeline session scopes are useful internally, they remain policies of the
MCP resource implementation; normal public lifetime is still anchored to the owning Riko
execution.

---

## 15. Large-result artifactization

Formalize oversized response redirection:

```python
class ResultDisposition(StrEnum):
    INLINE = "inline"
    ARTIFACT = "artifact"
    INDEXED = "indexed"
    STREAM = "stream"
```

Stream large data directly to storage where possible, hash while streaming, preserve
binary content/provenance, return bounded previews, support later partial reads, and
avoid full memory materialization.

Artifact content hashes are artifact identities; do not confuse them with Riko's
canonical BLAKE2b-128 semantic identity/fingerprint digest contract.

---

## 16. Retry and deterministic recovery

Use the common `RetryPolicy` from `execution-semantics.md`. Do **not** create an
independent `ExecutionRecoveryPolicy` retry loop for MCP/OpenAPI calls.

MCP/provider adapters classify transport/rate-limit/tool failures and provide hints such
as `Retry-After`; common execution owns retry ordering/backoff/count.

Rules:

* no hidden retries by default (`max_retries=0`);
* one layer owns retry for one failure domain;
* side-effecting capabilities participate in common execution-derived idempotency;
* write capability without genuine destination idempotency fails retryable/resumable
  validation unless explicitly opted out;
* state-store `CheckpointConflictError` is not automatically reloaded/rerun;
* deterministic verification may validate JSON Schema, status/media type, required
  fields, numeric/code/freshness/size bounds, and catalog/schema fingerprints;
* automatic capability reselection belongs in `riko-ai`, not retry handling.

An Operations as Code caller must not treat capability retry/reselection as permission
to re-plan an already-approved `OperationPlan` silently.

---

## 17. Parallel execution

Independent capability calls may be bounded concurrently. Preserve per-plan structured
results/exceptions and server-specific concurrency limits.

Where this maps directly onto Pipeline execution, prefer the common execution settings:

```python
pipeline.with_execution(concurrency=8, ordered=False)
```

Capability-level fan-out that has additional `fail_fast`/collect/minimum-success
semantics may retain an MCP service policy, but it must not create an unbounded task set
or alternate runtime.

---

## 18. Capability indexing

`riko-mcp` may provide deterministic keyword/index contracts without requiring
embeddings. Semantic indexing/retrieval belongs in `riko-ai`.

Index identity uses catalog/capability fingerprints and deterministic content hashes. Do
not silently alter ranking based on execution history.

---

## 19. Telemetry and history

Normalize capability usage with capability id/origin/server/transport, request/response
bytes, latency, retry count, status, rate-limit observations, and optional cost.

Execution history may record task/plan/catalog fingerprints, status, latency/cost,
validation result, and reviewer outcome. History is telemetry/audit data, not hidden
planner state.

Operation-level evidence may reference this telemetry through stable capability/plan/run
IDs; MCP history does not become the canonical operation repository or deployment
record.

---

## 20. Sandboxed computation

Never expose an in-process Python REPL. Sandboxed computation is an external MCP
capability with isolated filesystem/process/network/resource limits and explicit
artifact inputs/outputs. Default approval is `always` initially.

Imported operation source does not become a sandboxed-computation request automatically;
it must be resolved to an explicitly allowed capability through normal Operations as
Code validation/planning.

---

## 21. Initial integrations

Use the MCP Everything test server for protocol/CI coverage, not as production
integration. First production targets:

1. read-only filesystem MCP over stdio;
2. read-only Git MCP over stdio;
3. native `fetchdata` vs Fetch MCP selection evaluation;
4. APIs.guru/OpenAPI dynamic read-only capability;
5. remote CMS/content MCP;
6. authenticated read-only GitHub MCP;
7. read-only PostgreSQL/analytics MCP with strict limits.

---

## 22. Proposed repository layout

```text
riko_mcp/
├── sdk/
├── types/
├── config/
├── providers/
├── client/
├── transports/
├── catalog/
├── openapi/
├── execution/
├── artifacts/
├── audit/
├── modules/
├── evaluations/
└── server/
```

The `execution/` package implements MCP capability services on top of Riko's execution
contracts; it is not a competing Riko execution runtime.

---

## 23. Implementation phases

<!-- planning-slices: Generated by `manage codegen --planning`. Do not edit manually. -->
| Slice | Lands with | Status |
| --- | --- | --- |
| [client-spikes · Architecture and MCP v2 client spikes](#23-implementation-phases) |  | Planned |
| [capability-catalog · Capability domain, providers, and catalog fingerprints](#23-implementation-phases) |  | Planned |
| [execution-resources · Context resource definitions and stdio execution lifecycle](#23-implementation-phases) |  | Planned |
| [mcp-discovery · MCP discovery and static Pipeline module execution](#23-implementation-phases) |  | Planned |
| [apis-guru-provider · APIs.guru provider](#23-implementation-phases) |  | Planned |
| [openapi-provider · OpenAPI provider](#23-implementation-phases) |  | Planned |
| [openapi-executor · Read-only OpenAPI executor](#23-implementation-phases) |  | Planned |
| [plan-validation · Unified plan validation, approval, and execution](#23-implementation-phases) |  | Planned |
| [result-artifacts · Result artifacts and telemetry](#23-implementation-phases) |  | Planned |
| [parallel-execution · Bounded parallel execution with shared retry and idempotency](#23-implementation-phases) |  | Planned |
| [streamable-http · Streamable HTTP](#23-implementation-phases) |  | Planned |
| [authenticated-integrations · OAuth and authenticated integrations](#23-implementation-phases) |  | Planned |
| [site-integration · Site integration](#23-implementation-phases) |  | Planned |
| [capability-index · Deterministic capability indexing](#23-implementation-phases) |  | Planned |
| [security-fixtures · Deterministic evaluations and security fixtures](#23-implementation-phases) |  | Planned |
| [sandboxed-computation · Sandboxed computation](#23-implementation-phases) |  | Planned |
| [prompt-support · Prompt support](#23-implementation-phases) |  | Planned |
| [mcp-server · MCP server](#23-implementation-phases) |  | Planned |
<!-- /planning-slices -->

**client-spikes: Architecture and MCP v2 client spikes.** Spikes in-memory, stdio, and
Streamable HTTP clients against a pinned MCP v2 SDK, exercising pagination, structured
and non-text results, cancellation, and clean shutdown. It records retained and rejected
Langly and AutoGen patterns, ranks APIs.guru candidates for the exchange-rate scenario
without calling the third-party API, writes the architecture decisions, and verifies
execution-owned resource cleanup under sync and async `Pipeline` execution with no
production code depending on a public `ExecutionContext`.

Earlier notes call it M0.

**capability-catalog: Capability domain, providers, and catalog fingerprints.** The
frozen capability domain types, the `CapabilityProvider` protocol with its initial
native, MCP, APIs.guru, and OpenAPI providers, and one `CapabilityCatalog` whose
serialization and fingerprint are deterministic and whose construction rejects identity
conflicts.

Earlier notes call it M1.

**execution-resources: Context resource definitions and stdio execution lifecycle.**
Capability managers declared as resources on an immutable `Context`, with live stdio
sessions resolved by the execution, one session pool per execution, bounded calls per
server, and owned clients and subprocesses closed on completion, cancellation, or error.
It verifies that cleanup under both sync and async `Pipeline` execution.

Earlier notes call it M2.

**mcp-discovery: MCP discovery and static Pipeline module execution.** Discovery of MCP
tools, resources, and resource templates into the catalog, plus the `capabilitycatalog`,
`mcpdiscover`, `mcpresource`, `mcpresources`, and `mcptool` modules running as ordinary
`Pipeline` modules that declare their resource bindings.

Earlier notes call it M3.

**apis-guru-provider: APIs.guru provider.** Progressive discovery over APIs.guru
directory metadata: shortlists providers and fetches only a bounded top-N of schemas
under the schema-discovery policy. Directory summaries are not executable capabilities.

Earlier notes call it M4.

**openapi-provider: OpenAPI provider.** Normalizes OpenAPI 2.0, 3.0, and 3.1 operations
into immutable `OpenApiOperationSpec` capabilities, resolving local and internal refs
and only explicitly permitted remote refs.

Earlier notes call it M5.

**openapi-executor: Read-only OpenAPI executor.** Executes GET operations with path,
query, and schema-declared header arguments, JSON or text responses, and no-auth,
API-key, or bearer auth. Writes, uploads, callbacks, and custom signing wait until
read-only execution is stable.

Earlier notes call it M6.

**plan-validation: Unified plan validation, approval, and execution.** Immutable
capability and discovery plans revalidated against their catalog and schema
fingerprints, checked against the execution, schema-discovery, and API policies, and run
only after approval requirements are satisfied. A discovered OpenAPI URL never joins an
execution allowlist on its own.

Earlier notes call it M7.

**result-artifacts: Result artifacts and telemetry.** The `CapabilityResult` model with
distinct failure kinds, oversized results streamed to artifact storage with hashes,
provenance, and bounded previews, and normalized capability usage and history records.

Earlier notes call it M8.

**parallel-execution: Bounded parallel execution with shared retry and idempotency.**
Independent capability calls run concurrently within server-specific limits, retried
only through the common `RetryPolicy` with no hidden retries, and side-effecting
capabilities use execution-derived idempotency.

Earlier notes call it M9.

**streamable-http: Streamable HTTP.** The Streamable HTTP transport for remote MCP
servers, with the same execution-owned session lifecycle as stdio.

Earlier notes call it M10.

**authenticated-integrations: OAuth and authenticated integrations.** OAuth and other
authenticated integrations, with credential references resolved through a declared
credential-provider resource into short-lived, execution-owned tokens that never enter
plans, catalogs, or items. It follows basic Streamable HTTP.

Earlier notes call it M11.

**site-integration: Site integration.** Lets site pipelines consume the capability
modules this package supplies, while protocol detection and authentication stay out of
the site package.

Earlier notes call it M12.

**capability-index: Deterministic capability indexing.** Keyword and index contracts
keyed by catalog and capability fingerprints, with no embeddings and no ranking changes
driven by execution history.

Earlier notes call it M13.

**security-fixtures: Deterministic evaluations and security fixtures.** Golden catalogs,
plans, audit records, and artifacts against fake MCP servers, plus SSRF, redirect, size,
stale-plan, and malicious-schema fixtures. It includes imported-operation fixtures
proving that an importer or AI proposal cannot widen policy.

Earlier notes call it M14.

**sandboxed-computation: Sandboxed computation.** Computation exposed only as an
external MCP capability with isolated filesystem, process, network, and resource limits
and explicit artifact inputs and outputs; its default approval is `always`.

Earlier notes call it M15.

**prompt-support: Prompt support.** Discovery and use of the prompts MCP servers
publish.

Earlier notes call it M16.

**mcp-server: MCP server.** An MCP server that exposes stable Riko capabilities, built
after the client contracts stabilize.

Earlier notes call it M17.

Operations as Code integration requires no new MCP slice: once `capability-catalog` and
`plan-validation` are stable, `riko-ops` consumes catalog, policy, and approval as an
external package.

---

## 24. Testing requirements

Unit/contract coverage includes:

* configuration precedence/redaction;
* Context resource declaration/resolution/cleanup;
* catalogs/fingerprints;
* schema/OpenAPI normalization;
* policy/approval/plan validation;
* result conversion/artifact streaming;
* telemetry;
* cancellation and child-process cleanup;
* bounded concurrency;
* shared RetryPolicy behavior with no nested retry loop;
* stable execution-derived idempotency for side-effecting capabilities;
* SSRF/private-network/redirect/size controls;
* stale catalog/schema plans;
* malicious schemas/invalid results;
* imported operation/compatibility proposals cannot expand allowlists or bypass
  effect/approval policy;
* changed referenced `CapabilityPlan` identity invalidates an operation-level approval
  supplied by a caller;
* strict Pyright for all public APIs.

Use fake MCP servers and golden catalogs/plans/operation lists/audit/artifact/candidate
fixtures. Keep SDK compatibility `Any` values inside `riko_mcp/sdk/`.

---

## 24.1 SaaS gateways and credential brokers

A token vending service is a credential provider behind a named resource/reference:

```text
credential reference
→ declared credential-provider Resource
→ execution-owned short-lived token/session
→ connector/OpenAPI executor
```

Token values never enter capability plans, catalog records, workflow documents,
operation specs, compatibility reports, artifacts, or normal items.

An authorizer-style API proxy is represented as configured OpenAPI capability providers,
not a special core module. Tenant/provider configuration comes from immutable `Context`
/ declared resources; approval/SSRF/host/schema-size policy is unchanged.

Stable connector operations may project into the unified capability catalog; connector
packages still own protocol sessions/data streaming.

---

## 25. Explicit non-goals

Do not initially implement:

* MCP as internal Riko pipe transport;
* a public MCP/agent execution context separate from `Context`/Pipeline execution;
* autonomous multi-agent execution;
* arbitrary model-selected server/schema URLs;
* generated Python tool functions;
* unsandboxed Python execution;
* automatic destructive calls;
* unbounded discovery/retry loops;
* automatic model training or hidden ranking changes;
* distributed session management;
* browser-based MCP clients;
* OAuth before basic Streamable HTTP works;
* an Operations as Code source-of-truth, compatibility, migration, or deployment model.

---

## 26. Initial implementation prompt requirements

The `client-spikes` slice must:

1. inspect the current Riko `Pipeline`/Context/resource lifecycle;
2. record retained/rejected Langly/AutoGen patterns;
3. verify/pin the tested MCP v2 SDK;
4. spike in-memory, stdio, and Streamable HTTP clients;
5. exercise pagination, structured/non-text results, cancellation, and clean shutdown;
6. fetch/rank APIs.guru directory candidates and inspect at most five schemas for the
   exchange-rate scenario without executing the third-party API;
7. record request counts/bytes/schema sizes;
8. write architecture decisions;
9. stop before production modules, OAuth, server, AI selection, or third-party
   execution.

---

## 27. Operations as Code boundary summary

Use these terms consistently across gameplans:

```text
CapabilityCatalog / CapabilityPlan / capability execute
    owned here

OperationSpec / OperationPlan / validate-plan-apply-verify / compatibility / drift
    operations-as-code.md

provider-native operation asset/deployment facts + OperationHandle waiting
    provider-integrations.md

ChangePlan
    microsoft-administration.md
```

The security rule is equally simple: **import/discovery proposes what exists; policy
decides what is allowed; approval authorizes an exact permitted plan; execution never
widens policy itself.**
