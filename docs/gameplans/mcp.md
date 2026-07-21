# Authoritative Riko MCP Implementation Gameplan

## 1. Mission

Create an optional `riko-mcp` package that allows Riko to discover, validate, and execute external capabilities while preserving Riko’s existing stream-processing model.

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

AI-based ranking, decomposition, synthesis, and verification belong in `riko-ai`, not `riko-mcp`.

---

# 2. Prerequisites

This work begins only after the Riko AnyIO migration is complete.

Assume Riko provides:

* native AnyIO execution;
* async iterable pipelines;
* execution-scoped resources;
* cancellation propagation;
* deterministic resource cleanup;
* a supported sync bridge over the AnyIO runtime;
* a module registry;
* an export-target registry;
* one-shot pipe lifecycle semantics.

Do not add a second async runtime or a private per-package event loop.

---

# 3. Package boundaries

## `nerevu/riko`

Riko core owns:

* pipeline execution;
* module resolution;
* export-target resolution;
* `ExecutionContext`;
* lifecycle and cancellation;
* stream composition;
* sync/async bridging.

Only generic extension hooks should be added to Riko core.

## `nerevu/riko-mcp`

Create a separate distributable package:

```text
riko_mcp
```

It owns:

* MCP v2 SDK integration;
* session and transport lifecycle;
* MCP capability discovery;
* native Riko capability projection;
* APIs.guru discovery;
* OpenAPI normalization;
* capability catalogs;
* deterministic filtering;
* plan validation;
* execution policy;
* approval policy;
* MCP and OpenAPI execution;
* result normalization;
* artifacts;
* audit records;
* deterministic evaluation;
* future MCP server functionality.

## `nerevu/riko-ai`

It owns:

* model providers;
* semantic capability retrieval;
* AI capability selection;
* task decomposition;
* model-based verification;
* summarization;
* research;
* model routing and optimization.

`riko-ai` consumes the public `riko-mcp` capability contracts.

---

# 4. Source design retained from Langly and AutoGen

The reviewed AutoGen work supported declarative scenarios, OpenAPI-to-function conversion, and dynamic discovery of APIs through APIs.guru.

The intended flow was:

```text
identify missing capability
→ search APIs.guru
→ download an OpenAPI schema
→ convert operations into functions
→ invoke the new capability
```

Langly scenarios expanded this into explicit API selection and task workflows, including exchange-rate, translation, and API-research examples.

Retain:

* declarative capability discovery;
* APIs.guru as an API directory;
* OpenAPI as the executable HTTP contract;
* dynamic capability expansion;
* explicit tool availability;
* scenario-based evaluation;
* structured result handling;
* large-result redirection;
* cost, latency, and success telemetry.

Do not retain:

* LangChain or LangGraph as required dependencies;
* mutable mid-conversation tool registration;
* generated `FunctionType` objects;
* code-object mutation;
* arbitrary model-selected schema URLs;
* prompt-only security rules;
* unrestricted local Python execution;
* unbounded agent retries;
* conversational multi-agent routing as the execution engine.

The earlier implementation dynamically changed Python function signatures and registered functions into a running conversation.  The replacement is:

```text
OpenAPI document
→ immutable OpenApiOperationSpec
→ immutable OpenApiOperationPlan
→ generic validated HTTP executor
```

---

# 5. Non-negotiable architecture decisions

## 5.1 MCP client before MCP server

Implement:

```text
client foundation
→ discovery
→ catalog
→ execution
→ OpenAPI discovery
→ HTTP and authentication
→ production integrations
→ MCP server
```

Do not begin MCP-server implementation until the client contracts are stable.

## 5.2 MCP v2 only

Target the official MCP Python SDK v2.

During prerelease development, pin the exact tested beta:

```toml
mcp==<exact-v2-beta>
```

After stable v2 is verified:

```toml
mcp>=2.0,<3
```

All direct SDK imports must remain under:

```text
riko_mcp/sdk/
```

Do not expose SDK classes from public package APIs.

## 5.3 Stdio first

Transport sequence:

```text
Phase M0
    in-memory spike
    stdio spike
    Streamable HTTP smoke test

First production transport
    stdio

Second production transport
    Streamable HTTP

Then
    static remote authentication
    OAuth
```

This keeps the initial lifecycle manageable without embedding stdio assumptions in public abstractions.

## 5.4 One unified capability catalog

The catalog includes:

```text
native Riko modules
native Riko export targets
MCP tools
MCP resources
MCP resource templates
OpenAPI operations
```

The first selector chooses one capability.

Multi-step task planning belongs in `riko-ai`.

## 5.5 No persisted derived tags

Do not independently store values such as:

```text
origin:mcp
kind:tool
effect:read
runtime:remote
```

These are computed from typed fields.

Permit only non-derivable operator labels:

```text
approved-vendor
preferred
low-cost
internal
production-tested
```

## 5.6 Discovery, selection, and execution remain separate

```text
discover catalog
→ deterministically filter
→ AI proposes a plan
→ validate the plan
→ apply policy
→ request approval where required
→ execute
```

AI selection must never perform execution implicitly.

## 5.7 Context configuration takes precedence

Configuration precedence:

```text
package defaults
→ mcp.toml
→ environment interpolation
→ ExecutionContext overrides
```

A same-name server supplied through `ExecutionContext` replaces the entire file-defined server configuration. It is not deep-merged.

## 5.8 Approval is configurable

```python
class ExecutionApproval(StrEnum):
    NEVER = "never"
    POLICY = "policy"
    ALWAYS = "always"
```

Default:

```text
policy
```

Recommended behavior:

```text
known read-only capability
    may run automatically

unknown effects
    confirmation required

write operation
    confirmation required by default

destructive operation
    confirmation required unless an explicit
    operator policy permits unattended execution
```

Model confidence never overrides policy.

## 5.9 Sessions are execution-scoped

Do not establish a new MCP session or launch a subprocess for every item.

Default session scope:

```text
pipeline execution
```

Sessions must be reusable across stages through `ExecutionContext.resources`.

## 5.10 MCP is not Riko’s internal transport

Do not use MCP between:

```text
rename
filter
sort
infer
siteartifact
sitespec
export
```

Internal Riko stages remain direct Python streams and protocols.

---

# 6. Core domain model

Use frozen, slotted, keyword-only dataclasses.

Do not expose MCP SDK models publicly.

## 6.1 Capability origins

```python
class CapabilityOrigin(StrEnum):
    RIKO_MODULE = "riko_module"
    RIKO_EXPORT = "riko_export"
    MCP_TOOL = "mcp_tool"
    MCP_RESOURCE = "mcp_resource"
    MCP_RESOURCE_TEMPLATE = "mcp_resource_template"
    OPENAPI_OPERATION = "openapi_operation"
```

## 6.2 Capability kinds

```python
class CapabilityKind(StrEnum):
    SOURCE = "source"
    PROCESSOR = "processor"
    OPERATOR = "operator"
    AGGREGATOR = "aggregator"
    EXPORT = "export"
    RESOURCE = "resource"
    TOOL = "tool"
```

## 6.3 Data shapes

```python
class DataShape(StrEnum):
    UNKNOWN = "unknown"
    TEXT = "text"
    JSON = "json"
    RECORD = "record"
    RECORDS = "records"
    BINARY = "binary"
    STREAM = "stream"
    ARTIFACT = "artifact"
```

## 6.4 Effects

```python
@dataclass(frozen=True, slots=True, kw_only=True)
class CapabilityEffects:
    read_only: bool | None = None
    destructive: bool | None = None
    idempotent: bool | None = None
    open_world: bool | None = None
```

Protocol annotations are hints, not proof of safety.

Local policy may make effects more restrictive but not less restrictive without an explicit operator override.

## 6.5 Common capability information

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

## 6.6 Capability union

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

## 6.7 Catalog

```python
@dataclass(frozen=True, slots=True, kw_only=True)
class CapabilityCatalog:
    generation: int
    fingerprint: str
    capabilities: tuple[CapabilitySpec, ...]
    created_at: datetime
```

Catalog serialization must be deterministic.

## 6.8 Computed facets

Provide optional generated facets for display and model serialization:

```python
@property
def facets(self) -> frozenset[str]:
    ...
```

Computed facets:

* are not persisted independently;
* are not accepted as configuration overrides;
* are not included in identity;
* cannot drift from typed fields.

---

# 7. Capability providers

```python
class CapabilityProvider(Protocol):
    name: str

    async def discover(
        self,
        request: CapabilityDiscoveryRequest,
        *,
        context: ExecutionContext,
    ) -> CapabilityCatalogFragment:
        ...
```

Initial providers:

```text
RikoModuleProvider
RikoExportProvider
McpProvider
ApisGuruProvider
OpenApiProvider
```

The catalog builder merges fragments, validates identity conflicts, and creates one catalog fingerprint.

---

# 8. Plan model

## 8.1 Plan union

```python
type CapabilityPlan = (
    NativeModulePlan
    | NativeExportPlan
    | McpToolPlan
    | McpResourcePlan
    | OpenApiOperationPlan
)
```

## 8.2 Selection outcomes

```python
type SelectionOutcome = (
    CapabilityPlan
    | CapabilityDiscoveryPlan
    | NoCapabilityMatch
)
```

## 8.3 Native module plan

```python
@dataclass(frozen=True, slots=True, kw_only=True)
class NativeModulePlan:
    capability_id: str
    module: str

    conf: JsonObject
    kwargs: JsonObject

    confidence: float
    rationale: str

    catalog_fingerprint: str
```

## 8.4 MCP tool plan

```python
@dataclass(frozen=True, slots=True, kw_only=True)
class McpToolPlan:
    capability_id: str

    server: str
    tool: str
    arguments: JsonObject

    confidence: float
    rationale: str
    requires_confirmation: bool

    catalog_fingerprint: str
```

## 8.5 OpenAPI operation plan

```python
@dataclass(frozen=True, slots=True, kw_only=True)
class OpenApiOperationPlan:
    capability_id: str

    api_provider: str
    operation_id: str
    schema_fingerprint: str

    method: str
    url: str

    path_arguments: JsonObject
    query_arguments: JsonObject
    header_arguments: JsonObject
    body: JsonValue | None

    credential_ref: str | None

    confidence: float
    rationale: str
    requires_confirmation: bool

    catalog_fingerprint: str
```

The model may not supply:

* a new base URL;
* a new schema URL;
* undeclared headers;
* raw credential values;
* a method different from the operation;
* arguments not allowed by the input schema.

## 8.6 Discovery plan

```python
@dataclass(frozen=True, slots=True, kw_only=True)
class CapabilityDiscoveryPlan:
    provider: str
    query: str

    summary_limit: int
    schema_limit: int
    operation_limit: int

    catalog_fingerprint: str
```

A discovery plan may expand the catalog. It may not execute the final user request.

---

# 9. Configuration

## 9.1 File configuration

```toml
[servers.filesystem]
transport = "stdio"
command = "npx"
args = [
    "-y",
    "@modelcontextprotocol/server-filesystem",
    "/workspace",
]
trust = "read"

[servers.content]
transport = "streamable-http"
url = "https://content.example.org/mcp"
auth = "oauth"
trust = "read"
```

## 9.2 Environment interpolation

```toml
[servers.github.env]
GITHUB_TOKEN = "${GITHUB_TOKEN}"
```

Do not write resolved secrets to:

* logs;
* exceptions;
* catalogs;
* plans;
* manifests;
* audit records;
* pipeline items.

## 9.3 Context override

```python
context = Context(
    resources={
        "capabilities": CapabilityManager(
            mcp=McpClientConfig(
                servers={
                    "content": StreamableHttpServerConfig(
                        url="http://localhost:9000/mcp",
                        trust="read",
                    )
                }
            )
        )
    }
)
```

Context is also the location for:

* injected test sessions;
* secret providers;
* already-open sessions;
* request-specific policy;
* runtime credentials;
* artifact stores.

---

# 10. Public Riko modules

## `capabilitycatalog`

Build a catalog from configured providers.

```python
catalog = SyncPipe(
    "capabilitycatalog",
    conf={
        "include": {
            "riko_modules": True,
            "riko_exports": True,
            "mcp": True,
            "openapi": False,
        },
        "mcp_servers": [
            "filesystem",
            "git",
            "fetch",
        ],
    },
    context=context,
)
```

## `mcpdiscover`

Return normalized MCP entries only.

```python
SyncPipe(
    "mcpdiscover",
    conf={
        "servers": ["filesystem"],
        "include": [
            "tools",
            "resources",
            "resource_templates",
        ],
    },
    context=context,
)
```

## `mcpresource`

Read a known resource.

```python
SyncPipe(
    "mcpresource",
    conf={
        "server": "content",
        "uri": "cms://posts/published",
        "result": "records",
    },
    context=context,
)
```

## `mcpresources`

List resources or resolve a template.

## `mcptool`

Execute a statically selected MCP tool.

## `capabilitydiscover`

Consume a validated discovery plan and return an expanded catalog.

## `capabilityexecute`

Consume a validated `CapabilityPlan`.

AI-backed `capabilityselect` belongs in `riko-ai`.

---

# 11. APIs.guru progressive discovery

## 11.1 Goal

Given:

```text
Convert 100 USD to GBP.
```

the system should:

1. Search the APIs.guru directory.
2. Shortlist exchange-rate APIs using lightweight metadata.
3. Fetch only the top-N OpenAPI schemas.
4. Extract compatible operations.
5. Ask `riko-ai` to choose the best operation.
6. Validate the plan.
7. Apply network and credential policy.
8. Execute only after approval policy is satisfied.

## 11.2 Directory summaries

```python
@dataclass(frozen=True, slots=True, kw_only=True)
class ApiSummary:
    provider: str
    title: str
    description: str | None

    preferred_version: str
    openapi_url: str

    categories: tuple[str, ...]
    added_at: datetime | None
    updated_at: datetime | None

    logo_url: str | None
    source_url: str | None
```

Directory summaries are not executable capabilities.

## 11.3 Task-scoped candidate set

```python
@dataclass(frozen=True, slots=True, kw_only=True)
class ApiCandidateSet:
    task: str
    candidates: tuple[ApiSummary, ...]
    rationale: Mapping[str, str]
```

This permits schema inspection only. It does not permit API execution.

## 11.4 Expansion policy

```python
@dataclass(frozen=True, slots=True, kw_only=True)
class ApiExpansionPolicy:
    directory_limit: int = 20
    schema_limit: int = 5
    operation_limit: int = 30
    maximum_discovery_rounds: int = 1
```

## 11.5 OpenAPI operation

```python
@dataclass(frozen=True, slots=True, kw_only=True)
class OpenApiOperationSpec:
    id: str

    api_provider: str
    api_title: str
    api_version: str
    schema_fingerprint: str

    operation_id: str
    method: str
    base_url: str
    path: str

    summary: str | None
    description: str | None

    input_schema: JsonObject
    output_schema: JsonObject | None

    security: tuple[SecurityRequirement, ...]
    effects: CapabilityEffects

    input_shape: DataShape
    output_shape: DataShape

    labels: frozenset[str] = frozenset()
```

## 11.6 Initial OpenAPI execution scope

Support:

* OpenAPI 2.0;
* OpenAPI 3.0;
* OpenAPI 3.1;
* `GET`;
* path parameters;
* query parameters;
* schema-declared headers;
* JSON responses;
* text responses;
* no-auth APIs;
* API-key auth;
* bearer-token auth;
* internal and local `$ref`;
* explicitly permitted remote `$ref`.

Defer:

* POST, PUT, PATCH, DELETE;
* multipart;
* uploads;
* callbacks;
* webhooks;
* OAuth API operation flows;
* custom request signing;
* GraphQL;
* SOAP;
* generated SDKs.

---

# 12. MCP result model

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

Extraction modes:

```text
raw
structured
text
content
records
artifact
```

Do not silently discard non-text blocks.

Distinguish:

```text
transport failure
protocol failure
tool-level error
schema failure
policy rejection
approval requirement
result-conversion failure
```

---

# 13. Security policies

## 13.1 Execution policy

```python
@dataclass(frozen=True, slots=True, kw_only=True)
class CapabilityExecutionPolicy:
    allowed_servers: tuple[str, ...] = ()
    denied_capabilities: tuple[str, ...] = ()

    maximum_trust: str = "read"

    allow_destructive: bool = False
    allow_open_world: bool = False
    allow_private_networks: bool = False

    approval: ExecutionApproval = (
        ExecutionApproval.POLICY
    )

    maximum_result_bytes: int = 10_000_000
    timeout_seconds: float = 60
```

## 13.2 Schema discovery policy

```python
@dataclass(frozen=True, slots=True, kw_only=True)
class SchemaDiscoveryPolicy:
    allowed_catalogs: tuple[str, ...] = (
        "apis_guru",
    )

    allowed_schema_hosts: tuple[str, ...] = ()

    maximum_directory_entries: int = 5_000
    maximum_candidates: int = 20
    maximum_schemas: int = 5
    maximum_schema_bytes: int = 10_000_000

    maximum_redirects: int = 3
    allow_remote_refs: bool = False
```

## 13.3 API policy

```python
@dataclass(frozen=True, slots=True, kw_only=True)
class ApiExecutionPolicy:
    allowed_hosts: tuple[str, ...]
    allowed_methods: tuple[str, ...] = ("GET",)

    allow_private_networks: bool = False

    maximum_response_bytes: int = 10_000_000
    timeout_seconds: float = 30

    approval: ExecutionApproval = (
        ExecutionApproval.POLICY
    )
```

A discovered OpenAPI server URL is not automatically added to the execution allowlist.

## 13.4 Stdio policy

* Commands must come from trusted configuration.
* AI output may not define commands or arguments.
* Support executable allowlists.
* Support working-directory allowlists.
* Pass a minimal environment.
* Do not inherit all parent secrets.
* Capture bounded stderr.
* Terminate owned processes on cancellation.

---

# 14. Session lifecycle

```python
class McpClientManager:
    async def session(
        self,
        server: str,
    ) -> AsyncContextManager[McpSession]:
        ...
```

Default scope:

```text
pipeline
```

Possible scopes:

```python
class McpSessionScope(StrEnum):
    CALL = "call"
    STAGE = "stage"
    PIPELINE = "pipeline"
```

Requirements:

* reuse sessions;
* bound concurrent calls per server;
* close HTTP clients;
* stop owned child processes;
* preserve original exceptions;
* cancel in-flight calls;
* do not close externally supplied sessions.

---

# 15. Large-result artifactization

AutoGen redirected oversized responses into retrieval storage rather than returning everything inline.

Formalize this behavior.

```python
class ResultDisposition(StrEnum):
    INLINE = "inline"
    ARTIFACT = "artifact"
    INDEXED = "indexed"
    STREAM = "stream"
```

```python
@dataclass(frozen=True, slots=True, kw_only=True)
class ResultPolicy:
    maximum_inline_bytes: int = 250_000
    oversized: ResultDisposition = (
        ResultDisposition.ARTIFACT
    )
    preview_bytes: int = 4_096
```

```python
@dataclass(frozen=True, slots=True, kw_only=True)
class CapabilityArtifact:
    uri: str
    media_type: str

    size_bytes: int
    content_hash: str
    preview: str | None

    source_capability_id: str
    created_at: datetime
    expires_at: datetime | None
```

Requirements:

* stream directly to storage;
* hash while streaming;
* preserve binary content;
* return a bounded preview;
* preserve provenance;
* support later partial reads;
* avoid loading the full response into memory.

---

# 16. Deterministic verification and recovery

Support:

* JSON Schema validation;
* status-code validation;
* media-type validation;
* required fields;
* numeric bounds;
* known currency and country codes;
* freshness limits;
* response-size limits;
* catalog and schema fingerprints.

```python
@dataclass(frozen=True, slots=True, kw_only=True)
class ExecutionRecoveryPolicy:
    retry_transport_errors: bool = True
    retry_rate_limits: bool = True
    retry_tool_errors: bool = False

    maximum_attempts: int = 2
    maximum_backoff_seconds: float = 30
```

Do not automatically reselect another capability. Reselection belongs in `riko-ai`.

---

# 17. Parallel execution

```python
@dataclass(frozen=True, slots=True, kw_only=True)
class ParallelExecutionPolicy:
    maximum_concurrency: int = 8

    failure_mode: Literal[
        "fail_fast",
        "collect",
        "minimum_success",
    ] = "fail_fast"

    minimum_successes: int | None = None
```

Use AnyIO task groups and preserve per-plan results and exceptions.

Langly executed multiple tool calls concurrently but converted errors into textual tool messages.  The new implementation must keep failures structured.

---

# 18. Capability indexing interface

`riko-mcp` provides a deterministic index contract but does not require embeddings.

```python
@dataclass(frozen=True, slots=True, kw_only=True)
class CapabilityDocument:
    capability_id: str
    catalog_fingerprint: str

    title: str
    description: str
    searchable_text: str

    authoritative_metadata: Mapping[str, JsonValue]
    content_hash: str
```

```python
class CapabilityIndex(Protocol):
    async def upsert(
        self,
        documents: Iterable[CapabilityDocument],
    ) -> None:
        ...

    async def search(
        self,
        query: str,
        *,
        limit: int,
    ) -> tuple[str, ...]:
        ...
```

Initial search:

* keyword matching;
* title weighting;
* operation ID matching;
* parameter-name matching;
* provider matching.

Semantic search belongs in `riko-ai`.

---

# 19. Telemetry and history

## Capability usage

```python
@dataclass(frozen=True, slots=True, kw_only=True)
class CapabilityUsage:
    capability_id: str
    origin: CapabilityOrigin

    server: str | None
    transport: str | None

    request_bytes: int
    response_bytes: int
    latency_ms: int

    retries: int
    status: str

    rate_limit_remaining: int | None = None
    monetary_cost: Decimal | None = None
```

## Execution history

```python
@dataclass(frozen=True, slots=True, kw_only=True)
class CapabilityExecutionRecord:
    task_fingerprint: str
    capability_id: str

    plan_fingerprint: str
    catalog_fingerprint: str

    status: str
    latency_ms: int
    cost: Decimal | None

    validation_passed: bool
    reviewer_outcome: str = "unknown"
```

`riko-mcp` may expose deterministic success and latency statistics.

It may not silently alter ranking.

---

# 20. Sandboxed computation

Do not expose an in-process Python REPL.

Use an MCP sandbox server:

```text
Riko
→ MCP client
→ isolated execution server
```

Initial capabilities:

```text
python.evaluate
python.run_file
sql.query_readonly
notebook.execute_cell
```

Required controls:

* ephemeral filesystem;
* no inherited secrets;
* no host filesystem access;
* network disabled by default;
* memory limit;
* CPU limit;
* process limit;
* timeout;
* explicit input artifacts;
* explicit output artifacts;
* read-only database credentials.

Default approval:

```text
always
```

---

# 21. Initial integrations

## Protocol and CI

### MCP Everything test server

Use for:

* tools;
* resources;
* templates;
* prompts;
* structured results;
* errors;
* pagination;
* change notifications.

Do not treat it as a production integration.

## First production integration

### Filesystem MCP over stdio

Start read-only.

Use cases:

* inspect Riko modules;
* locate site configuration;
* read approval JSON;
* find documentation;
* inspect generated manifests.

## Second production integration

### Git MCP over stdio

Start read-only.

Use cases:

* repository history;
* diffs;
* release changes;
* change attribution;
* file history.

## Selection evaluation

### Native `fetchdata` versus Fetch MCP

Expected:

```text
JSON API into records
    native fetchdata

web page into model-readable text
    Fetch MCP
```

## Dynamic external capability integration

### APIs.guru and OpenAPI

Acceptance request:

```text
Convert 100 USD to GBP.
```

Expected flow:

```text
no existing match
→ APIs.guru discovery
→ top exchange-rate candidates
→ top five schemas
→ compatible GET operations
→ operation plan
→ validated execution
```

## First remote MCP integration

### Content/CMS MCP

Use for:

* live blog feed;
* article content;
* authors;
* categories;
* media metadata;
* revisions.

## Authenticated service

### GitHub MCP

Initially read-only:

* repositories;
* issues;
* pull requests;
* releases;
* Actions status.

## Enterprise data

### PostgreSQL or analytics MCP

Use:

* read-only credentials;
* statement timeout;
* row limit;
* result-byte limit;
* sensitive-column policy.

---

# 22. Proposed repository layout

```text
riko_mcp/
├── __init__.py
├── py.typed
├── exceptions.py
│
├── sdk/
│   ├── protocol.py
│   └── v2.py
│
├── types/
│   ├── capabilities.py
│   ├── plans.py
│   ├── results.py
│   ├── effects.py
│   ├── policy.py
│   ├── usage.py
│   └── servers.py
│
├── config/
│   ├── loading.py
│   ├── interpolation.py
│   └── validation.py
│
├── providers/
│   ├── riko_modules.py
│   ├── riko_exports.py
│   ├── mcp.py
│   ├── apis_guru.py
│   └── openapi.py
│
├── client/
│   ├── manager.py
│   ├── session.py
│   ├── discovery.py
│   ├── resources.py
│   └── tools.py
│
├── transports/
│   ├── stdio.py
│   ├── streamable_http.py
│   └── auth.py
│
├── catalog/
│   ├── builder.py
│   ├── cache.py
│   ├── fingerprint.py
│   ├── filtering.py
│   └── indexing.py
│
├── openapi/
│   ├── directory.py
│   ├── loading.py
│   ├── normalization.py
│   ├── references.py
│   ├── operations.py
│   └── execution.py
│
├── execution/
│   ├── executor.py
│   ├── validation.py
│   ├── approval.py
│   ├── parallel.py
│   ├── recovery.py
│   └── results.py
│
├── artifacts/
│   ├── protocol.py
│   └── local.py
│
├── audit/
│   ├── protocol.py
│   └── jsonl.py
│
├── modules/
│   ├── capabilitycatalog.py
│   ├── capabilitydiscover.py
│   ├── capabilityexecute.py
│   ├── mcpdiscover.py
│   ├── mcpresource.py
│   ├── mcpresources.py
│   └── mcptool.py
│
├── evaluations/
│   ├── scenarios.py
│   ├── evaluators.py
│   └── fixtures.py
│
└── server/
    ├── app.py
    ├── tools/
    ├── resources/
    └── prompts/
```

---

# 23. Implementation phases

## M0 — Architecture, repository archaeology, and MCP v2 spikes

* inspect current Riko AnyIO lifecycle;
* inspect current Langly and AutoGen snapshots;
* pin exact MCP v2 version;
* test in-memory client;
* test stdio client;
* smoke-test Streamable HTTP;
* test tools and resources;
* test structured and non-text results;
* test cancellation;
* test cleanup after success and failure;
* spike APIs.guru directory ranking;
* fetch only top-five candidate schemas;
* do not execute third-party APIs.

**Acceptance:** all decisions are recorded and no production modules exist.

## M1 — Capability domain and providers

* implement domain types;
* implement computed facets;
* implement operator labels;
* implement catalog fragments;
* implement native module provider;
* implement native export provider;
* implement MCP provider contracts;
* implement catalog fingerprints.

**Acceptance:** deterministic combined catalog without AI.

## M2 — Configuration and stdio lifecycle

* implement `mcp.toml`;
* implement environment interpolation;
* implement context replacement;
* implement stdio sessions;
* implement resource ownership;
* implement cancellation;
* add fake MCP servers;
* add Filesystem acceptance tests.

**Acceptance:** no leaked subprocesses or secrets.

## M3 — MCP discovery and static execution

* discover tools, resources, templates, and prompts;
* consume pagination;
* normalize MCP types;
* implement `mcpdiscover`;
* implement `mcpresource`;
* implement `mcpresources`;
* implement `mcptool`;
* validate tool inputs and outputs.

**Acceptance:** known MCP capabilities work without AI.

## M4 — APIs.guru provider

* fetch directory;
* normalize summaries;
* cache directory;
* rank summaries deterministically;
* construct task-scoped candidate sets;
* enforce discovery bounds.

**Acceptance:** exchange-rate candidates found without downloading every schema.

## M5 — OpenAPI provider

* support OpenAPI 2, 3.0, and 3.1;
* normalize operations;
* resolve permitted references;
* fingerprint schemas;
* cache schemas;
* derive operation capabilities;
* validate operation schemas.

**Acceptance:** selected API schemas produce stable operation catalogs.

## M6 — Read-only OpenAPI executor

* implement GET;
* separate path, query, header, and body values;
* resolve credential references;
* enforce host policy;
* execute through shared HTTP client;
* validate responses;
* normalize results.

**Acceptance:** exchange-rate example executes from a validated plan.

## M7 — Unified plan validation and execution

* implement plan union;
* implement `capabilitydiscover`;
* implement `capabilityexecute`;
* revalidate catalog and schema fingerprints;
* apply approval;
* apply execution policy;
* emit audit records.

**Acceptance:** native, MCP, and OpenAPI plans share one execution boundary.

## M8 — Result artifacts and telemetry

* implement artifacts;
* implement streaming writes;
* implement previews;
* implement capability usage;
* implement execution history;
* implement local artifact store.

**Acceptance:** large results do not require full in-memory materialization.

## M9 — Parallel execution and deterministic recovery

* implement bounded parallel execution;
* implement transient retry policy;
* respect server concurrency;
* preserve structured errors;
* add rate-limit handling.

**Acceptance:** independent calls run concurrently without hidden failures.

## M10 — Streamable HTTP

* implement remote session lifecycle;
* implement TLS policy;
* implement static authentication;
* implement reconnect behavior;
* implement CMS test server.

**Acceptance:** module APIs remain transport-neutral.

## M11 — OAuth and authenticated integrations

* use official MCP v2 OAuth support;
* implement secure token-store protocol;
* add GitHub read-only integration;
* handle expiration and refresh;
* prevent token leakage.

**Acceptance:** credentials never enter plans or pipeline records.

## M12 — Site integration

* read CMS blog content;
* generate initial SEO snapshot;
* emit live feed configuration;
* call AI-selected enrichment where configured;
* apply draft review;
* export through `riko-site`.

**Acceptance:** end-to-end CMS-to-WEI workflow.

## M13 — Capability indexing

* implement deterministic keyword index;
* index catalog documents;
* support incremental catalog updates;
* expose semantic index protocol for `riko-ai`.

**Acceptance:** large catalogs are searchable without an LLM dependency.

## M14 — Deterministic evaluations

* port relevant Langly/AutoGen scenarios;
* test exact, numeric, schema, contains, policy, and timeout outcomes;
* test APIs.guru discovery;
* test catalog drift;
* test unavailable credentials;
* test malicious schemas.

**Acceptance:** protocol and execution regressions fail CI without a model.

## M15 — Sandboxed computation

* integrate an isolated MCP sandbox;
* support Python and read-only SQL;
* require approval;
* enforce resource limits;
* return artifacts.

**Acceptance:** no generated code runs inside the Riko process.

## M16 — Prompt support

* discover prompts;
* retrieve prompt definitions;
* validate arguments;
* expose normalized messages;
* do not automatically execute prompt output.

## M17 — MCP server

Expose stable functionality only after client contracts are mature.

Initial resources:

```text
riko://modules
riko://exports
riko://capabilities
riko://sites/{site}/spec
riko://sites/{site}/drafts
riko://builds/{build}/manifest
```

Initial tools:

```text
riko.pipeline.validate
riko.pipeline.describe
riko.site.validate
riko.site.build_preview
riko.site.approve_draft
riko.site.reject_draft
```

---

# 24. Testing requirements

## Unit tests

Cover:

* configuration;
* redaction;
* lifecycle;
* catalogs;
* fingerprints;
* schema validation;
* OpenAPI normalization;
* policy;
* approval;
* plan validation;
* result conversion;
* artifacts;
* telemetry.

## Fake MCP servers

Provide deterministic fixtures for:

* tools only;
* resources only;
* mixed capabilities;
* pagination;
* list changes;
* invalid schemas;
* binary results;
* tool errors;
* cancellation;
* process crash;
* slow calls.

## Golden fixtures

Use golden files for:

* catalogs;
* plans;
* OpenAPI operation lists;
* audit records;
* artifacts;
* APIs.guru candidate sets.

## Type checking

All public code must pass strict Pyright.

Keep SDK compatibility `Any` values inside `riko_mcp/sdk/`.

## Security tests

Test:

* command allowlists;
* environment scrubbing;
* SSRF protection;
* private-network rejection;
* redirect limits;
* oversized schemas;
* oversized results;
* stale plans;
* stale schemas;
* destructive-tool rejection;
* secret redaction.

---

# 25. Explicit non-goals

Do not implement initially:

* MCP as an internal Riko stage transport;
* autonomous multi-agent execution;
* arbitrary model-selected server URLs;
* arbitrary model-selected schema URLs;
* generated Python tool functions;
* unsandboxed Python execution;
* automatic destructive calls;
* unbounded discovery loops;
* unbounded retries;
* automatic model training;
* hidden ranking changes;
* distributed session management;
* browser-based MCP clients;
* OAuth before basic Streamable HTTP works.

---

# 26. Initial Claude Code prompt

```text
You are implementing Phase M0 of the authoritative Riko MCP roadmap.

Repositories:
- nerevu/riko, most current branch
- nerevu/langly, latest reachable snapshot
- nerevu/autogen, latest reachable snapshot
- new repository nerevu/riko-mcp

Assumptions:
- Riko’s AnyIO migration is complete.
- Target MCP Python SDK v2 only.
- The unified catalog will include native Riko modules,
  native export targets, MCP capabilities, and OpenAPI operations.
- AI selection will be implemented separately in riko-ai.
- Selection, discovery, validation, approval, and execution remain separate.
- Stdio is the first production transport.

Execute Phase M0 only.

Required:
1. Inspect Riko’s AnyIO and execution-resource lifecycle.
2. Record retained and rejected Langly/AutoGen patterns.
3. Verify the current stable or beta MCP v2 SDK.
4. Pin the exact tested version.
5. Spike:
   - in-memory MCP client
   - stdio MCP client
   - Streamable HTTP smoke test
   - paginated tools/resources
   - structured result
   - non-text result
   - cancellation
   - clean shutdown
6. Fetch the APIs.guru directory.
7. For “Convert 100 USD to GBP”:
   - rank lightweight API candidates
   - fetch at most five preferred schemas
   - normalize read-only operations
   - report the best apparent operation
   - do not execute the API
8. Record request counts, bytes, and schema sizes.
9. Write architecture decision records.
10. Stop after Phase M0.

Do not add production Riko modules, OAuth, an MCP server,
AI selection, or third-party API execution.
```
