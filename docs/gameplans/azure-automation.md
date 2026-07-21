# Azure automation

For your Azure/Microsoft 365/PowerShell use case, the remaining work is less about AI and more about building a safe automation adapter layer around Riko.

Missing pieces
Capability  Inside Riko Outside/core optional
PowerShell execution    Generic processor contract, assignment, retries, parallelism    pwsh subprocess/runspace adapter
Microsoft Graph Generic HTTP/tool invocation    Graph authentication, pagination, throttling, SDK-free request adapter
Exchange Online Pipeline/tool interface ExchangeOnlineManagement PowerShell module
SharePoint/Teams    Pipeline/tool interface Graph, PnP.PowerShell, Teams modules
Intune/Entra    Pipeline/tool interface Graph endpoints and permission mappings
Azure resources Pipeline/tool interface ARM REST, Azure CLI, Az PowerShell modules
Authentication  Credential-provider protocol    Managed identity, service principal, certificate, delegated login
Long-running jobs   Poll/wait operator  Azure Automation, ARM operations, Graph async jobs
Approval controls   Context/policy hooks    Human approval UI or ticketing integration
Secrets Secret references only  Key Vault, environment, certificate store
Audit   Context events  Log Analytics, Sentinel, storage, SIEM exporters
Recommended architecture
Riko pipeline
    │
    ├── deterministic modules
    │     azure
    │     graph
    │     powershell
    │
    └── optional AI agent
          │
          └── explicitly registered Azure/365/PowerShell tools

Most Microsoft automation should remain deterministic:

(
    SyncPipe("input", source=users)
    .graph(
        conf={
            "method": "GET",
            "path": "/users/{id}/licenseDetails",
        },
        assign="licenses",
    )
    .powershell(
        conf={
            "command": "Set-Mailbox",
            "parameters": {
                "Identity": {"subkey": "userPrincipalName"},
                "HiddenFromAddressListsEnabled": True,
            },
        },
        assign="mailbox_result",
    )
)

Use an AI agent only when the model needs to select among approved operations or interpret unstructured requests.

1. PowerShell adapter

You need a native execution abstraction:

class PowerShellRunner(Protocol):
    def invoke(
        self,
        command: str,
        *,
        parameters: Mapping[str, object],
        modules: Sequence[str] = (),
        timeout: float | None = None,
    ) -> PowerShellResult: ...

    async def ainvoke(...) -> PowerShellResult: ...

Normalized result:

@dataclass(frozen=True, slots=True)
class PowerShellResult:
    value: object
    stdout: str
    stderr: str
    exit_code: int
    warnings: tuple[str, ...] = ()
    errors: tuple[str, ...] = ()

Implementation options:

Subprocess
Python → pwsh -NoProfile -NonInteractive

Best initial option:

simple;
process isolation;
works cross-platform;
easy timeout and cancellation;
no persistent session state.
Persistent runspace
Python → long-lived PowerShell host/runspace

Useful later for:

Exchange Online sessions;
repeated module imports;
reduced authentication overhead;
faster bulk operations.

More difficult lifecycle and concurrency management.

Remote execution

Optional adapters:

PowerShell remoting over WinRM;
PowerShell over SSH;
Azure Automation runbooks;
Azure Functions;
Hybrid Runbook Worker.

These should implement the same runner protocol.

2. Structured PowerShell I/O

Do not parse formatted PowerShell console output.

Wrap commands so results serialize predictably:

$result = Get-MgUser -UserId $UserId
$result | ConvertTo-Json -Depth 20 -Compress

For errors:

$ErrorActionPreference = "Stop"

try {
    $result = & $Command @Parameters

    @{
        success = $true
        result = $result
        errors = @()
    } | ConvertTo-Json -Depth 20 -Compress
}
catch {
    @{
        success = $false
        result = $null
        errors = @(
            @{
                message = $_.Exception.Message
                category = $_.CategoryInfo.Category.ToString()
                target = $_.CategoryInfo.TargetName
                stack = $_.ScriptStackTrace
            }
        )
    } | ConvertTo-Json -Depth 20 -Compress

    exit 1
}

This should be hidden inside the adapter.

3. PowerShell functions as agent tools

Langly’s tool concept maps well to PowerShell advanced functions.

A function already exposes:

name;
help synopsis;
description;
parameters;
types;
mandatory flags;
validation sets.

Example:

function Disable-NerevuUser {
    [CmdletBinding(SupportsShouldProcess)]
    param(
        [Parameter(Mandatory)]
        [string] $UserPrincipalName,

        [switch] $RevokeSessions
    )

    ...
}

A discovery process could run:

Get-Command Disable-NerevuUser |
    Select-Object Name, Parameters

and:

Get-Help Disable-NerevuUser -Full

Then generate a Riko tool:

ToolSpec(
    name="disable_nerevu_user",
    description="Disable a Microsoft 365 user account.",
    input_schema={
        "type": "object",
        "properties": {
            "user_principal_name": {"type": "string"},
            "revoke_sessions": {"type": "boolean"},
        },
        "required": ["user_principal_name"],
    },
    handler=...,
)

This is one of the most valuable pieces to extract from Langly’s schema-driven tool design.

4. Authentication abstraction

Authentication should not appear directly in pipeline configuration.

class TokenProvider(Protocol):
    def get_token(
        self,
        resource: str,
        scopes: Sequence[str] = (),
    ) -> str: ...

Implementations:

ManagedIdentityCredential
ClientSecretCredential
ClientCertificateCredential
DeviceCodeCredential
InteractiveBrowserCredential
AzureCliCredential

For production MSP automation, prefer:

managed identity when hosted in Azure;
certificate-based service principals;
workload identity where available;
client secrets only when unavoidable;
delegated interactive authentication for administrative workflows requiring user context.

Pipeline configuration should refer to a named credential:

{
    "credential": "client-contoso-automation",
}

The runtime resolves it.

5. Tenant and environment context

Every operation needs explicit tenant context.

@dataclass(frozen=True, slots=True)
class MicrosoftContext:
    tenant_id: str
    subscription_id: str | None = None
    credential: str | None = None
    cloud: str = "public"

This must not be mutable global state because Riko may process several clients concurrently.

Example item:

{
    "tenant": "contoso",
    "user_principal_name": "user@contoso.org",
}

Dynamic configuration:

{
    "tenant": {"subkey": "tenant"},
}

This is essential for MSP multi-tenancy.

6. Microsoft Graph adapter

A lightweight Graph adapter should support:

HTTP method;
relative path;
query parameters;
request body;
pagination;
throttling;
batch requests;
normalized errors.
pipe.graph(
    conf={
        "method": "GET",
        "path": "/users",
        "params": {
            "$filter": "accountEnabled eq true",
            "$select": "id,displayName,userPrincipalName",
        },
        "paginate": True,
    },
)

The Graph adapter should return records, allowing Riko to handle downstream transformation.

Graph retrieval → Riko stream → filter/normalize/join/export

Do not hide an entire data pipeline inside a Graph SDK abstraction.

7. Azure Resource Manager adapter

Azure resource automation needs similar primitives:

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

Options:

ARM REST adapter

Best general implementation:

low dependency footprint;
consistent request/response behavior;
easy integration with managed identity;
exposes Azure APIs directly.
Az PowerShell

Best when:

the operation already has a mature cmdlet;
command behavior is difficult to reproduce;
administrators need familiar scripts;
existing automation should be reused.
Azure CLI

Useful as a fallback, but less attractive as the main abstraction because JSON output and command behavior can vary more than direct REST.

8. Job and polling support

Several Azure and Microsoft operations are asynchronous.

Riko needs a generic poll operator or helper:

pipe.poll(
    conf={
        "status_field": "status",
        "complete_values": ["Succeeded", "Failed", "Cancelled"],
        "interval": 5,
        "timeout": 600,
    },
)

Or internally:

async def wait_for_operation(
    operation: OperationHandle,
    *,
    interval: float,
    timeout: float,
) -> OperationResult:
    ...

This covers:

ARM long-running operations;
Azure Automation jobs;
Intune actions;
reports;
exports;
provisioning jobs.
9. Idempotency and WhatIf

Administrative automation must distinguish:

read
create
update
delete
privileged/destructive

PowerShell tools should support ShouldProcess where possible:

[CmdletBinding(SupportsShouldProcess)]

Riko configuration:

{
    "what_if": True,
    "confirm": False,
}

For REST operations, adapters should support a dry-run planning layer:

@dataclass(frozen=True)
class ChangePlan:
    action: str
    target: str
    current: object
    proposed: object
    destructive: bool

Recommended flow:

discover → calculate desired state → create plan → approve → apply → verify
10. Policy and approval gate

Do not let an agent directly execute arbitrary Microsoft administrative operations.

Each tool should declare risk:

class Risk(StrEnum):
    READ = "read"
    WRITE = "write"
    PRIVILEGED = "privileged"
    DESTRUCTIVE = "destructive"
@dataclass(frozen=True)
class ToolSpec:
    ...
    risk: Risk = Risk.READ
    requires_approval: bool = False

Policy:

class ExecutionPolicy(Protocol):
    def authorize(
        self,
        tool: ToolSpec,
        arguments: Mapping[str, object],
        context: MicrosoftContext,
    ) -> AuthorizationResult: ...

Examples requiring approval:

user deletion;
license removal;
role assignment;
Conditional Access changes;
mailbox purge;
resource deletion;
secret rotation;
tenant-wide configuration changes.
11. Secret and certificate handling

Riko should only carry references:

{
    "credential": "contoso-graph-cert",
}

The credential resolver retrieves material from:

Azure Key Vault;
Windows certificate store;
environment variables;
mounted secret files;
managed identity.

Never place:

client secrets
private keys
access tokens
refresh tokens

inside serialized pipeline definitions or normal stream items.

12. Retry and throttling

Microsoft APIs require operation-aware retry handling.

@dataclass(frozen=True)
class RetryPolicy:
    attempts: int = 5
    backoff: float = 2
    maximum_delay: float = 60
    honor_retry_after: bool = True

Retryable:

HTTP 429;
HTTP 502/503/504;
PowerShell transient connection errors;
Exchange throttling;
Azure operation-in-progress conditions.

Usually not retryable:

permission failures;
malformed requests;
missing resources unless eventual consistency is expected;
invalid cmdlet parameters.

Error classification belongs in adapters. Retry orchestration can be generic Riko behavior.

13. Desired-state operations

Your use case will benefit more from desired-state tools than raw commands.

Instead of exposing:

Add-MgGroupMemberByRef
Remove-MgGroupMemberByRef

expose:

ensure_group_membership(
    user="user@contoso.org",
    group="Finance",
    present=True,
)

Instead of:

Set-MgUserLicense

expose:

ensure_license(
    user="user@contoso.org",
    sku="Microsoft 365 Business Premium",
    present=True,
)

The tool internally:

reads current state;
compares desired state;
makes changes only when needed;
returns whether anything changed;
verifies final state.

This provides idempotency and safer agent use.

Recommended modules
In Riko core

Avoid Microsoft-specific dependencies.

Add or reuse:

retry
poll
loop
broadcast
dispatch
udf
HTTP request support
Context events
tool protocol
Optional riko-microsoft package
riko_microsoft/
  auth.py
  context.py
  graph.py
  arm.py
  powershell.py
  tools.py
  policy.py
  errors.py

  modules/
    graph.py
    azure.py
    powershell.py

Optional extras:

[project.optional-dependencies]
graph = ["azure-identity", "httpx"]
powershell = []
azure = ["azure-identity", "httpx"]
all = [...]

A PowerShell subprocess implementation may require no Python package beyond the standard library.

Initial implementation order
PowerShellRunner using pwsh subprocesses.
Structured JSON input/output wrapper.
Certificate/managed-identity credential resolver.
Lightweight Microsoft Graph REST client.
powershell and graph processors.
Tool generation from PowerShell advanced functions.
Risk classification and approval policy.
Retry, throttling, and async job polling.
Desired-state tools for common MSP operations.
Optional agent integration.

The most useful first vertical slice for your MSP work would be:

input user request
    → resolve tenant
    → query user through Graph
    → generate change plan
    → approval gate
    → run PowerShell/Graph operation
    → verify resulting state
    → emit audit record

That gives you reusable Microsoft automation without making Riko Microsoft-specific or allowing the AI layer to bypass operational controls.

.poll should treat pub/sub as a wake-up mechanism, not as a separate execution model.

The recommended behavior is hybrid:

start operation
    ↓
subscribe to relevant events
    ↓
check authoritative status
    ↓
wait for either:
    event received ───────┐
    polling interval ─────┼─→ recheck authoritative status
    timeout/cancel ───────┘
Integration with existing send/receive

Riko already has the local pieces:

send publishes each stream item to one or more named receivers while passing the item downstream.
receive registers a named coroutine, buffers incoming items, yields StreamState.PENDING while waiting, and stops on StreamState.DONE or timeout.

So .poll could consume either:

timer ticks;
items delivered through send;
both.

Conceptually:

result = (
    operation
    .poll(
        check=get_operation_status,
        conf={
            "interval": 30,
            "timeout": 900,
            "until": ["succeeded", "failed", "cancelled"],
            "subscription": "azure-operations",
            "correlation_field": "operation_id",
            "mode": "hybrid",
        },
    )
)
Three modes
Poll-only
{"mode": "interval", "interval": 30}

Periodically calls the status function.

Best when the service does not publish events.

Event-only
{"mode": "event", "subscription": "azure-operations"}

Waits for a matching event and returns its result.

This is efficient, but risky when messages can be delayed, dropped, duplicated, or lack complete status information.

Hybrid
{
    "mode": "hybrid",
    "subscription": "azure-operations",
    "interval": 30,
}

Waits for an event for up to 30 seconds. On either an event or timeout, it checks the authoritative API.

This should be the default for Azure and Microsoft 365.

Core loop
def poll(
    initial,
    *,
    check,
    subscription=None,
    interval=30,
    timeout=900,
    is_done,
):
    started = monotonic()
    current = check(initial)

    while not is_done(current):
        remaining = timeout - (monotonic() - started)

        if remaining <= 0:
            raise PollTimeoutError(initial)

        wait = min(interval, remaining)

        if subscription is not None:
            subscription.receive(timeout=wait)
        else:
            sleep(wait)

        current = check(initial)

    return current

The event does not have to contain the final result. Its primary meaning is:

“Something changed; check again now.”

That avoids coupling .poll to Azure Event Grid, Service Bus, Graph webhooks, or PowerShell job-event payload formats.

Transport protocol

Riko core should define only a minimal subscription interface:

class Subscription(Protocol):
    def receive(
        self,
        *,
        timeout: float | None = None,
    ) -> object | None: ...

    def close(self) -> None: ...

Async equivalent:

class AsyncSubscription(Protocol):
    async def receive(
        self,
        *,
        timeout: float | None = None,
    ) -> object | None: ...

    async def aclose(self) -> None: ...

Implementations can live outside core:

LocalSubscription          existing send/receive registry
AzureServiceBusSubscription
AzureEventGridSubscription
GraphWebhookSubscription
RedisSubscription
PowerShellEventSubscription
Existing local adapter

The current _registry and receive queues can back an in-process subscription:

class RikoSubscription:
    def __init__(self, name: str):
        self.name = name

    def receive(self, *, timeout=None):
        queue = _get_receive_queue()[self.name]
        deadline = None if timeout is None else monotonic() + timeout

        while not queue:
            if deadline is not None and monotonic() >= deadline:
                return None

            sleep(0.1)

        state, item = queue.popleft()

        if state is StreamState.DONE:
            return None

        return item

External subscribers can publish into Riko with the existing function:

send(
    "azure-operations",
    {
        "operation_id": operation_id,
        "event_type": "status_changed",
    },
)
Correlation

A shared subscription will receive events for many operations, so .poll needs correlation:

{
    "subscription": "azure-operations",
    "correlation_field": "operation_id",
    "correlation_value": {
        "subkey": "operation.id",
    },
}

The poller ignores unrelated events:

event = subscription.receive(timeout=wait)

if event and event.get(correlation_field) != correlation_value:
    continue

A stronger design lets the subscriber filter server-side:

subscription = broker.subscribe(
    topic="azure-operations",
    correlation={
        "operation_id": operation_id,
    },
)
Avoiding the subscription race

Subscribe before starting the operation:

wrong:
start operation → subscribe
                  event may already be lost

right:
subscribe → start operation → initial status check → wait

For APIs where the operation ID is unavailable until creation:

subscribe broadly using tenant or request correlation;
start the operation with a client-generated correlation ID;
narrow filtering once the operation ID is returned.
Riko pipeline shape
subscription = subscriptions.open(
    "azure-operations",
    tenant=item["tenant_id"],
)

result = (
    SyncPipe("azurestart", source=[item])
    .poll(
        check=azure_status,
        subscription=subscription,
        conf={
            "field": "operation",
            "status_field": "status",
            "complete": [
                "Succeeded",
                "Failed",
                "Cancelled",
            ],
            "interval": 30,
            "timeout": 900,
        },
        assign="operation",
    )
)

The resulting record remains one normal Riko item:

{
    "operation": {
        "id": "...",
        "status": "Succeeded",
        "result": {...},
    }
}

Intermediate status events should normally go through Context events rather than become downstream records:

context.emit(
    "poll.status",
    operation_id=operation_id,
    status=current["status"],
)
Recommended boundary
Riko core
    poll loop
    timeout
    interval fallback
    completion predicate
    correlation
    subscription protocol
    StreamState integration

Riko local runtime
    adapter over send/receive queues

External packages
    Azure Service Bus
    Event Grid
    Graph webhooks
    Redis
    PowerShell event transports

Thus .poll remains a generic wait-and-check operator. Pub/sub merely lets it recheck immediately instead of sleeping until the next interval.

