# Riko Azure and Microsoft Adapter Gameplan

## 1. Mission

Define the Microsoft-specific execution adapters Riko needs for Azure, Microsoft Graph,
Exchange Online, Teams, Intune, Entra, and PowerShell without creating a second execution,
credential, retry, capability, or administrative-policy framework.

This plan owns **Microsoft adapter mechanics**. It does not own generic credential storage,
retry policy, capability metadata, long-running-operation waiting, or desired-state
administration.

Related authoritative plans:

* `connectors.md` — connector/session lifecycle and credential references;
* `rest-incremental.md` — REST pagination and collection semantics;
* `execution-semantics.md` — retry, timeout, cancellation, and error policy;
* `mcp.md` — common capability catalog, effects, schemas, and execution policy;
* `provider-integrations.md` — provider auth lifecycle and `OperationHandle`/operation wait;
* `microsoft-administration.md` — ChangePlan, desired state, dry-run, approval, verification,
  audit evidence, certificate workflows, and handoffs.

## 2. Ownership boundary

This plan owns:

```text
MicrosoftContext
PowerShellRunner and structured PowerShell envelopes
Microsoft credential-provider adapters
Microsoft Graph adapter
Azure Resource Manager adapter
Exchange/Teams/Intune/Entra adapter selection
Microsoft-specific retry/throttle classification
Microsoft operation-handle/status adapters
projection of Microsoft operations into the shared capability catalog
```

It intentionally does **not** redefine:

```text
CredentialProvider / secret storage          connectors.md
RetryPolicy / timeout / cancellation          execution-semantics.md
CapabilityInfo / CapabilityCatalog / policy   mcp.md
OperationHandle wait algorithm                provider-integrations.md
ChangePlan / approval / desired state         microsoft-administration.md
```

## 3. Package boundary

Microsoft dependencies stay optional:

```text
nerevu/riko
    generic stream/runtime contracts only

nerevu/riko-connect
    generic HTTP and connector infrastructure

nerevu/riko-mcp
    capability catalog and policy

nerevu/riko-microsoft
    auth adapters
    MicrosoftContext
    Graph / ARM clients
    PowerShell runner
    Exchange / Teams / Intune / Entra adapters
    operation-status adapters
    capability projections
```

No Microsoft SDK or PowerShell dependency becomes required by core Riko.

## 4. Microsoft execution context

Every Microsoft operation carries explicit tenant/environment context:

```python
@dataclass(frozen=True, slots=True, kw_only=True)
class MicrosoftContext:
    tenant_id: str
    credential: str
    cloud: Literal["public", "government", "china"] = "public"
    subscription_id: str | None = None
    operator_id: str | None = None
    correlation_id: str | None = None
```

`credential` is a **reference** resolved through `connectors.md`; this type does not contain
secret material.

The context is immutable and execution-scoped. Never store the active tenant, subscription,
credential, or PowerShell session in process-global mutable state because MSP workloads may
run several client operations concurrently.

## 5. PowerShell runner

PowerShell is an optional execution adapter:

```python
class PowerShellRunner(Protocol):
    def invoke(
        self,
        command: str,
        *,
        parameters: Mapping[str, JsonValue],
        modules: Sequence[str] = (),
        timeout: float | None = None,
        context: MicrosoftContext,
    ) -> PowerShellResult: ...

    async def ainvoke(...) -> PowerShellResult: ...
```

Normalized result:

```python
@dataclass(frozen=True, slots=True, kw_only=True)
class PowerShellResult:
    value: JsonValue | None
    stdout: str
    stderr: str
    exit_code: int
    warnings: tuple[str, ...] = ()
    errors: tuple[PowerShellError, ...] = ()
```

Initial implementation:

```text
Python
→ pwsh -NoProfile -NonInteractive
→ structured JSON envelope
```

This gives process isolation, straightforward timeout/cancellation, and no accidental
persistent shell state.

A later persistent-runspace implementation may reduce repeated Exchange/module/auth startup
cost but must implement the same runner contract and execution-resource lifecycle.

Optional remote implementations may include WinRM/SSH, Azure Automation, Azure Functions,
or Hybrid Runbook Worker.

## 6. Structured PowerShell I/O

Never parse formatted console tables.

The adapter wraps commands so machine output contains a structured envelope such as:

```text
success
result
warnings
errors
exit_code
```

Raw stdout/stderr remain diagnostic fields and are subject to the same redaction policy as
other connector logs.

PowerShell exceptions should normalize at least:

```text
message
category
target
script stack where available
```

The wrapping/serialization behavior belongs inside the adapter so every PowerShell-backed
capability behaves consistently.

## 7. Microsoft credential adapters

Do not define a Microsoft-only `TokenProvider` protocol. Implement the credential-provider
contract from `connectors.md`.

Useful Microsoft implementations include:

```text
managed identity
workload identity
certificate service principal
client-secret service principal
device-code delegated login
interactive-browser delegated login
Azure CLI development credential
```

Production preference is generally:

```text
managed/workload identity when hosted appropriately
→ certificate service principal
→ client secret only when unavoidable
```

Interactive/delegated setup and provider-facing status/refresh/revoke behavior follow
`provider-integrations.md`. Serialized workflows carry only named credential references.

## 8. Microsoft Graph adapter

A lightweight Graph adapter should expose Microsoft semantics without hiding a data
pipeline inside an SDK.

It supports:

```text
HTTP method
relative Graph path
query parameters
request body
Graph pagination
batch requests
normalized Graph errors/request IDs
MicrosoftContext
```

Example:

```python
pipe.graph(
    conf={
        "method": "GET",
        "path": "/users",
        "params": {
            "$filter": "accountEnabled eq true",
            "$select": "id,displayName,userPrincipalName",
        },
    },
    assign="users",
)
```

Graph collection/pagination should reuse the REST collection machinery where its semantics
fit rather than maintain a second paginator implementation.

Graph results become ordinary Riko records or action results for downstream processing.

## 9. Azure Resource Manager adapter

ARM follows the same adapter pattern:

```python
pipe.azure(
    conf={
        "method": "GET",
        "resource": (
            "/subscriptions/{subscription_id}"
            "/resourceGroups/{resource_group}"
            "/providers/Microsoft.Compute/virtualMachines"
        ),
        "api_version": "...",
    },
)
```

Direct ARM REST is the preferred generic path because it has a small dependency footprint,
uses the same credential/session model, and exposes Azure API behavior directly.

Use Az PowerShell when a mature cmdlet is materially safer or more complete than reproducing
its behavior. Azure CLI may be a fallback adapter, not the primary public abstraction.

## 10. Exchange, Teams, Intune, and Entra

Choose the adapter per operation rather than forcing one technology across Microsoft 365:

```text
Microsoft Graph
    preferred for supported resource APIs

ExchangeOnlineManagement / Teams / PnP PowerShell
    optional adapters where service-specific cmdlets provide required behavior

ARM REST
    Azure resource management
```

All adapters still share:

* `MicrosoftContext`;
* connector credential resolution;
* execution-scoped sessions/resources;
* common retry/error contracts;
* common capability projection.

IMAP/SMTP are not substitutes when Microsoft-specific mailbox semantics require Graph or
Exchange APIs.

## 11. Capability projection

Microsoft operations project into the common capability model owned by `mcp.md`.

PowerShell advanced functions are useful discovery sources because `Get-Command` and
`Get-Help` expose parameter names, types, required flags, validation sets, and descriptions.

The projection flow is:

```text
PowerShell command / Graph operation / ARM operation
→ adapter metadata
→ CapabilityInfo / provider-specific CapabilitySpec
→ common policy/catalog
→ optional CLI, MCP, or agent surface
```

Do not define a second `ToolSpec`, risk enum, or catalog in `riko-microsoft`.
Administrative extensions such as required scopes or `supports_what_if` are described by
`microsoft-administration.md` and attached to the shared capability identity.

## 12. Long-running Microsoft operations

ARM deployments, Azure Automation jobs, Intune actions, exports, provisioning, and similar
operations often return provider-specific status URLs or IDs.

Microsoft adapters normalize those responses into the `OperationHandle` contract owned by
`provider-integrations.md` and expose an authoritative status capability.

Example mapping:

```text
Azure/Graph response
→ Microsoft operation ID/status URL
→ OperationHandle(provider="microsoft", ...)
→ shared wait_operation(...)
```

The Microsoft adapter owns:

* how to derive the operation ID/status endpoint;
* how to read and normalize provider status;
* provider terminal-state mapping;
* provider request/correlation IDs.

It does **not** implement another generic `.poll()` loop, timeout type, event-wait protocol,
or subscription abstraction.

## 13. Retry and throttling classification

`execution-semantics.md` owns `RetryPolicy` and retry ordering. Microsoft adapters only
classify provider outcomes and expose retry hints.

Typical transient conditions:

```text
HTTP 429 with Retry-After
HTTP 502/503/504
Exchange throttling
transient PowerShell connectivity failures
provider "operation in progress" states where retry is semantically valid
```

Typical non-retryable conditions:

```text
permission/scope failures
malformed requests
invalid command parameters
missing resources unless documented eventual consistency applies
```

An adapter may supply provider delay hints such as `Retry-After`; it must not silently add a
second retry loop around a Riko operation already governed by `RetryPolicy`.

## 14. Connector and event integration

Microsoft packages implement the same shared connector boundaries as other providers:

```text
Graph / ARM
    HTTP/resource capability adapters

Exchange / PowerShell
    command/action adapters

Service Bus / Event Grid / Graph webhooks
    event source/sink adapters

Key Vault / managed identity / certificate services
    credential-provider adapters
```

Broker and webhook sessions are execution-scoped resources. Event subscriptions may wake an
operation waiter, but authoritative completion still comes from the Microsoft status API as
defined by `provider-integrations.md`.

## 15. Package layout

Suggested package:

```text
riko_microsoft/
    auth.py
    context.py
    graph.py
    arm.py
    powershell.py
    operations.py
    errors.py
    capabilities.py

    modules/
        graph.py
        azure.py
        powershell.py
```

Optional extras might include:

```text
graph
powershell
exchange
teams
all
```

A subprocess PowerShell runner may need no Python package beyond the standard library, but
requires a compatible `pwsh` executable.

## 16. Testing strategy

Adapter contract tests should cover:

1. concurrent tenant contexts cannot leak tenant/credential/session state;
2. credential references resolve through the shared connector provider;
3. PowerShell JSON success/warning/error envelopes normalize deterministically;
4. cancellation/timeout terminate subprocess resources according to runtime semantics;
5. Graph pagination uses the shared collection contract where applicable;
6. Graph throttling exposes `Retry-After` without creating nested retry loops;
7. ARM status responses normalize into `OperationHandle`;
8. provider terminal states map consistently;
9. PowerShell/Graph/ARM operations project into the shared capability catalog;
10. optional dependencies fail with clear adapter-specific errors;
11. logs/events redact tokens, private keys, and sensitive command inputs.

Administrative desired-state/approval tests belong in `microsoft-administration.md`.

## 17. Phases

```text
AZ0  MicrosoftContext + adapter interfaces
AZ1  PowerShell subprocess runner + structured I/O
AZ2  Microsoft credential-provider implementations
AZ3  Graph REST adapter
AZ4  ARM REST adapter
AZ5  Exchange/Teams/Intune/Entra optional adapters
AZ6  OperationHandle/status normalization
AZ7  shared capability projection
AZ8  cross-adapter lifecycle/throttle tests
```

## 18. Definition of done

1. Microsoft-specific dependencies remain outside core Riko.
2. Tenant/cloud/subscription context is explicit and execution-scoped.
3. Credential material is resolved by the shared connector contract, not a Microsoft-only
   secret system.
4. PowerShell results are structured rather than parsed from console formatting.
5. Graph and ARM expose ordinary Riko records/actions.
6. Microsoft long-running jobs normalize to the shared `OperationHandle` contract.
7. Generic retry, timeout, operation waiting, capability policy, and admin planning are
   referenced from their authoritative gameplans rather than redefined here.
8. The Microsoft package can serve deterministic pipelines, CLI, MCP, and approved agent
   tools through one set of adapter implementations.
