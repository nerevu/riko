# Authoritative Riko Connector Implementation Gameplan

## 1. Mission

Create optional connector packages that let Riko resolve and execute external data
sources and sinks without placing protocol clients, credentials, or a monolithic fetch
dispatcher in core.

This plan promotes the useful parts of Shelf milestones 5, 6, 11, 12, and 13 while
aligning them with AnyIO, `ExecutionContext`, the module registry, RDP, MCP policy, and
one-shot pipeline semantics.

## 2. Package boundaries

```text
nerevu/riko
    SourcePlan and minimal resolver protocol, only if multiple packages need them
    ExecutionContext resource lifecycle
    module/export registries
    Feed and one-shot execution

nerevu/riko-connect
    source resolver registry
    HTTP response adapter
    file and object-storage connectors
    FTP/SFTP
    IMAP/SMTP
    broker publishers and consumers
    tabular file readers
    CKAN and Prometheus adapters
    connector capability projection

nerevu/riko-mcp
    OpenAPI and MCP capability execution and policy

nerevu/riko-microsoft
    Graph, ARM, Exchange, Service Bus, Event Grid, and Microsoft credentials
```

Provider-specific dependencies remain optional extras or separate distributions.

## 3. Non-negotiable decisions

### 3.1 AnyIO runtime; protocols are orthogonal

Do not reintroduce Twisted as the **execution runtime**. A connector may wrap a synchronous
stdlib or third-party client in a worker thread, or use an async client compatible with the
AnyIO runtime (prefer asyncio-native protocol libraries: `asyncssh`, `aiosmtplib`/`aiosmtpd`,
`aioftp`, `aioimaplib`, `bottom`, `slixmpp`). No connector starts a private event loop.

**Twisted protocol implementations are not banned — only Twisted-as-runtime is.** Protocol
support is an orthogonal adapter-layer concern (ROADMAP §23.1). Where a Twisted implementation is
genuinely superior (chiefly server-side roles and AMP — see
[twisted-protocol-servers.md](twisted-protocol-servers.md)), a connector may run it on the shared
asyncio loop via `twisted.internet.asyncioreactor` **inside that connector package** — this is not
"starting a private event loop," it is installing the asyncio reactor so Twisted protocol code
cooperates with the AnyIO/asyncio loop the engine already runs on.

### 3.2 Credentials are references

Serialized configuration contains:

```json
{"credential": "clients/contoso/sftp"}
```

It never contains passwords, private keys, access tokens, or URI user-info. A credential
provider resolves material inside execution scope and redacts it from events and errors.

### 3.3 Resolution is not execution

```text
URI + explicit hints
→ SourcePlan
→ policy and credential resolution
→ connector session
→ records or artifacts
```

`SourcePlan` is immutable, serializable, fingerprinted, and inspectable.

```python
@dataclass(frozen=True, slots=True, kw_only=True)
class SourcePlan:
    resolver: str
    uri: str
    capability_id: str
    media_type: str | None
    boundedness: Literal["finite", "unbounded", "unknown"]
    options: Mapping[str, JsonValue]
```

### 3.4 Do not steal `fetch` silently

Keep the existing RSS `fetch` behavior through the current compatibility window and make
`fetchrss` the documented canonical name. Introduce the resolver-backed entry point as
`source` or `fetchauto` first. A future major release may rename it to `fetch` after
warnings, migration tooling, and fixtures prove compatibility.

### 3.5 No hidden duplicate downloads

HTTP type detection must reuse one response when possible. A resolver may use path and
configured media type without I/O. Network probing is explicit, bounded, cached, and
visible in the plan or events. It must not issue an unconditional HEAD followed by a
second GET for every source.

### 3.6 Streaming and lifecycle

Connectors return lazy records, batches, or artifact references. Sessions open on
iteration and close on exhaustion, cancellation, error, or early consumer termination.
Connections are never opened once per item unless the protocol requires it.

## 4. Resolver registry

```python
class SourceResolver(Protocol):
    name: str
    schemes: frozenset[str]

    def resolve(
        self,
        request: SourceRequest,
    ) -> SourcePlan | None: ...


class Connector(Protocol):
    async def open(
        self,
        plan: SourcePlan,
        context: ExecutionContext,
    ) -> Feed: ...
```

Resolution precedence:

```text
explicit connector/capability
→ explicit media type
→ exact URI scheme resolver
→ HTTP path/header/body resolver when probing is allowed
→ unsupported-source error
```

Duplicate exact-scheme claims fail registry construction unless an operator explicitly
selects one resolver.

## 5. HTTP response and document handling

The HTTP connector emits a normalized response record with body, status, content type,
final URL, selected headers, and timing metadata. Size limits and redirect limits are
required.

Content extraction is a downstream named capability:

```text
http
→ documenttext
→ markdown
→ contactextract
```

PDF and DOCX extraction are optional document extras. Fetching does not accept an
arbitrary `postprocess` callable in serialized configuration.

## 6. Storage and file connectors

Initial finite connectors:

```text
file
S3
GCS
Azure Blob
FTP
SFTP
XLS/XLSX
```

OpenDAL may back object and file storage behind an adapter, but public errors and events
identify the Riko connector and the underlying cause. The implementation dependency is
not treated as secret.

Directory reads require an explicit glob, recursive flag, and maximum object count.
Remote object metadata should be available without forcing content materialization.

## 7. Mail connectors

```text
imapread
smtpwrite
```

Requirements:

* parsed message metadata and raw MIME content are distinct fields;
* attachment bodies may become artifacts above a size threshold;
* mailbox checkpointing uses UID validity and UID, not only timestamps;
* SMTP write operations declare side effects and idempotency limitations;
* Microsoft 365-specific behavior should prefer the `riko-microsoft` Graph/Exchange
  adapter when mailbox semantics exceed generic IMAP/SMTP.

## 8. Broker connectors

Initial adapters may include:

```text
ZeroMQ PUB/SUB
RabbitMQ
Azure Service Bus
```

Every adapter declares delivery semantics and acknowledgement behavior. Publishers and
consumers are paired capabilities. Broker sessions are execution resources. At-least-once
consumers expose message IDs and acknowledgement handles; best-effort transports clearly
state message-loss behavior.

## 9. Structured source adapters

### 9.1 CKAN

Use CKAN APIs with explicit pagination, server-side filters where supported, resource
hash metadata, and bounded retries. API keys are credential references.

### 9.2 Prometheus exposition

Parse the current exposition format through a maintained parser when available. Preserve
metric name, labels, value, timestamp, and sample type. A scrape is finite; continuous
monitoring belongs in orchestration.

### 9.3 Tabular files

CSV remains core-compatible. XLS/XLSX and other optional formats live in connector extras.
Rows normalize through the accepted frame/Arrow interchange without requiring pandas.

## 10. Singer compatibility through RDP

Do not add permanent `fetchtap` and `singerexport` core modules that bypass RDP state and
schema contracts.

Create a Singer adapter:

```text
Singer SCHEMA → RDP schema
Singer RECORD → RDP record/batch
Singer STATE  → RDP state
```

and the reverse adapter for Singer targets where required. Subprocesses are execution
resources with cancellation, stderr capture, bounded line size, exit-code validation,
and secret redaction.

## 11. SaaS and REST APIs

Generic public APIs remain OpenAPI capabilities in `riko-mcp`. An authorizer-style proxy
is simply a configured OpenAPI provider. A token-vending service is a credential provider.
Do not add one module per SaaS provider unless streaming behavior cannot be represented by
OpenAPI or a generic HTTP connector.

## 12. Capability and module projection

A connector may expose:

* a named Riko source/operator for fluent pipelines;
* a capability record for MCP/AI selection;
* a CLI command provider.

All three project the same service object and configuration schema. They do not duplicate
execution logic.

## 13. Phases

### C0 — Contracts and spikes

* source request and plan fixtures;
* resolver collision rules;
* HTTP response envelope;
* file and HTTP lifecycle spikes;
* credential redaction tests.

### C1 — HTTP and local files

* resolver registry;
* explicit probing;
* `fetchrss` compatibility aliasing;
* `source`/`fetchauto` entry point;
* document extraction boundary.

### C2 — Object and transfer storage

* S3/GCS/Azure Blob adapters;
* FTP/SFTP;
* directory limits and artifactization.

### C3 — Mail and brokers

* IMAP/SMTP;
* ZeroMQ and RabbitMQ;
* acknowledgement and delivery contracts.

### C4 — Structured ecosystems

* XLS/XLSX;
* CKAN;
* Prometheus;
* Singer/RDP bridge.

### C5 — Catalog and CLI integration

* capability projection;
* source inspection and test commands;
* deterministic evaluation fixtures.

## 14. Definition of done

1. Core imports no connector protocol library.
2. No connector starts a private event loop.
3. Credentials never appear in serialized plans or records.
4. Resolution can be inspected without execution.
5. HTTP probing is explicit and bounded.
6. Every session closes on early termination.
7. Long-lived sources require checkpoint policy.
8. Broker delivery semantics are declared and tested.
9. Singer state and schema map through RDP.
10. Plugin modules, capabilities, and CLI commands share one execution service.
