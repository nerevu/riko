# Connectors gameplan

## 1. Mission

Create optional connector packages that let Riko resolve and execute external data
sources and sinks without placing protocol clients, credentials, or a monolithic fetch
dispatcher in core.

This plan promotes the useful parts of Shelf milestones 5, 6, 11, 12, and 13 while
aligning them with AnyIO, immutable `Context`/`Resource` definitions, the module registry,
RDP, MCP policy, and private execution lifecycles.

## 2. Package boundaries

```text
nerevu/riko
    SourcePlan and minimal resolver protocol, only if multiple packages need them
    Context / Resource definitions and execution-owned resource lifecycle
    module/export registries
    Feed / FeedResult / FeedState contracts
    Publisher / Subscription protocols

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

Connectors return lazy records, batches, `FeedResult`s, or artifact references. Sessions are
resolved as execution-owned resources and close on exhaustion, cancellation, error, or early
consumer termination. Connections are never opened once per item unless the protocol requires it.

`Context` contains immutable resource definitions; live sessions/clients are not stored on the
public Context.

## 4. Resolver registry and execution handoff

```python
class SourceResolver(Protocol):
    name: str
    schemes: frozenset[str]

    def resolve(self, request: SourceRequest) -> SourcePlan | None: ...
```

A connector implementation is bound to a Pipeline node through the normal Riko module/resource
preparation path. The node declares its direct resource dependencies, and the existing wrapper
machinery passes the execution-bound `resources` view. Do not introduce a second public
`ExecutionContext` or a connector-specific dependency-injection system.

Conceptually:

```python
def parser(plan: SourcePlan, resources, **kwargs):
    return resources.connector.open(plan)
```

where `resources.connector` is the live execution-local handle resolved from an immutable
`Context` `Resource` definition.

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

### 6.1 Sink verb vocabulary

Writes use two collection verbs on a shared destination model. `write(dest, format=, mode=)` is a
passthrough emit (fire-and-forget copy, non-keyed `append`/`replace`, returns the stream);
`sink(dest, mode=, keys=, idempotency_key=)` is the terminal reconciler (keyed/destructive modes,
returns a `SinkResult`/`Plan`). A destination resolves like a pipe module — bare name / `Sinks`
enum / typed target object — with a path-signalled string defaulting to `File`. The write-mode
contract (`SinkMode`, `SinkWrite`, `sink_write`) lives in `riko/sinks.py`; `output` is a compiler
DAG terminal, not a sink. Full decision record: `monthly-dashboard.md` §5.

### 6.2 File write serialization and reconciliation

`Shipped:` `riko/targets.py` — the `File` target, capability-aware `build_write`, and the
`file_writer` used by the `write` verb. `write` desugars to `subscribe(on_receive=…)` (riko has no
"taps"): a **streamable** format (`csv`/`jsonl`, `STREAMABLE_FORMATS`, overridable via
`write(stream=…)`) is written per item as it flows; any other format buffers and writes **one
document** when the publisher completes — full consumption or a graceful `close()`/context-manager
exit — while an abrupt `terminate()` discards the partial buffer. `sink` (terminal, sync + async)
resolves the target, validates the mode against its capabilities, and delivers.

`Current gap:`
- **(C) Incremental framing for buffered document formats** — emit the open/separator/close frame
  per format (`[ … ]` for json, a `FeatureCollection` wrapper for geojson, header/footer for
  ofx/qif) so those formats also stream without holding the whole buffer, closing the frame on
  completion/graceful close. This is hand-rolled framing over the per-item encoder, **not** an
  `ijson` job — `ijson` is a streaming *parser*, not a serializer.
- **Keyed file reconciliation** — `merge`/`replace`/`delete` against an existing file destination
  needs to read the current document to diff incoming records against it. Stream that read with
  `ijson` (the `perf` extra, already used for large-JSON ingest in `riko/parsers.py`) so a large
  destination is reconciled without full materialization. File targets today expose only the
  non-keyed `append`/`replace`; keyed modes stay a record-store (`build_write` `serializes=False`)
  concern until this lands.
- **Async `write`** — the `on_receive` writer over `async_hub`; `AsyncPipe/AsyncCollection.write`
  raise `NotImplementedError` until then. `sink` is already async.

`Dependencies:` the mode contract (`riko/sinks.py`) and target adapters (`riko/targets.py`) are in
place; keyed reconciliation also depends on the plan/apply gate (`monthly-dashboard.md` §8) for the
destructive modes.

## 7. Mail connectors

```text
imapread
smtpwrite
```

Requirements:

* parsed message metadata and raw MIME content are distinct fields;
* attachment bodies may become artifacts above a size threshold;
* mailbox checkpointing uses UID validity and UID, not only timestamps;
* mailbox state persists through the common `FeedState` / `StateStore` contract;
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
consumers implement/project the shared `Publisher` / `Subscription` protocols where applicable.
Broker sessions are execution resources. At-least-once consumers expose message IDs and
acknowledgement handles; best-effort transports clearly state message-loss behavior.

## 9. Structured source adapters

### 9.1 CKAN

Use CKAN APIs with explicit pagination, server-side filters where supported, resource
hash metadata, and bounded retries. API keys are credential references.

### 9.2 Prometheus exposition

Parse the current exposition format through a maintained parser when available. Preserve
metric name, labels, value, timestamp, and sample type. One scrape is finite and bounded.

Repeated observations **inside one Riko workflow** use `Pipeline.poll(...)` and the recurring
observation/state semantics owned by [feed-monitoring.md](feed-monitoring.md). External schedulers may
rerun the whole finite Pipeline through [orchestration.md](orchestration.md), but orchestration is not
the only recurrence mechanism.

### 9.3 Tabular files

CSV remains core-compatible. XLS/XLSX and other optional formats live in connector extras.
Rows normalize through the accepted frame/Arrow interchange without requiring pandas.

## 10. Singer compatibility

Do not add permanent `fetchtap` and `singerexport` core modules that bypass the common state/schema
contracts.

Create a Singer adapter whose runtime state maps to core state first:

```text
Singer SCHEMA -> RDP/schema projection
Singer RECORD -> RDP record/batch projection when interchange is required
Singer STATE  -> FeedState / StateStore
```

RDP may project that state for wire interchange, but it does not own a second generic checkpoint
model. The reverse adapter may emit Singer STATE from the committed source/observation state when a
Singer target requires it.

Subprocesses are execution resources with cancellation, stderr capture, bounded line size,
exit-code validation, and secret redaction.

## 11. SaaS and REST APIs

Generic public APIs remain OpenAPI capabilities in `riko-mcp`. An authorizer-style proxy
is simply a configured OpenAPI provider. A token-vending service is a credential provider.
Do not add one module per SaaS provider unless streaming behavior cannot be represented by
OpenAPI or a generic HTTP connector.

REST collection traversal/pagination/cursor semantics are owned by
[rest-incremental.md](rest-incremental.md); connectors provide transport/session capabilities rather
than a second REST state model.

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
* Singer/core-state/RDP bridge.

### C5 — Catalog and CLI integration

* capability projection;
* source inspection and test commands;
* deterministic evaluation fixtures.

Forward cross-cutting implementation order is owned by
[implementation-sequence.md](implementation-sequence.md); these connector phases describe package
specialization only.

## 14. Definition of done

1. Core imports no connector protocol library.
2. No connector starts a private event loop.
3. Credentials never appear in serialized plans or records.
4. Resolution can be inspected without execution.
5. HTTP probing is explicit and bounded.
6. Every execution-owned session closes on early termination.
7. Long-lived/recurring source state uses common `FeedState` / `StateStore` semantics.
8. Broker delivery semantics are declared and tested against shared pub/sub protocols where used.
9. Singer state maps to core state; RDP is an interchange projection rather than the generic owner.
10. Plugin modules, capabilities, and CLI commands share one execution service.
