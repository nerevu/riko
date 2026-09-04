# Connectors gameplan

## 1. Mission

Create optional connector packages that let Riko read from and write to external systems without
placing protocol clients, credentials, or provider-specific behavior in Core.

This plan owns concrete connector/Target adapter behavior, credential/session mechanics,
acknowledgements, and optional protocol packages. It consumes:

- canonical `Target` / `Format` / `ReadNode` / `WriteNode` structure from `extensibility.md`;
- provider-neutral write/action behavior from `effects.md`;
- immutable `Context` / `Resource` and execution lifetime from `execution-semantics.md`;
- state/checkpoint semantics from `execution-semantics.md`;
- fan-out/pub-sub semantics from `fanout-topology.md`;
- file/artifact codecs from `artifact-conversion.md`;
- provider semantics from `provider-integrations.md` where the adapter is a SaaS/provider package.

## 2. Package boundaries

```text
nerevu/riko
    Target / Format definitions
    TargetRegistry contract
    ReadNode / WriteNode / ActionNode graph structure
    Context / Resource definitions
    Feed / FeedResult / FeedState contracts
    Publisher / Subscription protocols

nerevu/riko-connect
    concrete FILE / HTTP / object-storage / transfer / mail / broker adapters
    optional credential implementations
    connector capability projection

nerevu/riko-mcp
    OpenAPI and MCP capability execution/policy

nerevu/riko-microsoft
    Graph, ARM, Exchange, Service Bus, Event Grid, Microsoft credentials/actions
```

Provider-specific dependencies remain optional extras or separate distributions.

Core knows how to **describe** a Target and how an execution invokes a registered target contract;
it does not import every SDK needed to operate those targets.

## 3. Non-negotiable decisions

### 3.1 Target is the canonical endpoint definition

Do not create a parallel public `SourcePlan`/`SinkPlan` identity system.

```text
Target
    immutable endpoint/provider identity + reusable defaults

Format
    immutable interpretation/serialization identity

Resource
    execution-scoped client/session/resource value

ReadNode / WriteNode
    operation-specific behavior
```

Examples:

```python
Target(Targets.FILE, path="data.csv")
Target(Targets.HTTP, url="https://example/api")
Target(Targets.S3, bucket="reports", key="daily.jsonl")
```

Concrete optional packages register adapters for target names; Workflow v2 can still parse and
validate the Target definition without importing the SDK.

### 3.2 AnyIO runtime; protocols are orthogonal

Do not reintroduce Twisted as the **execution runtime**. A connector may wrap synchronous clients in
the common worker adapter or use async clients compatible with the AnyIO runtime. No connector starts
a private event loop/portal/task group.

Twisted protocol implementations are not categorically banned where they are genuinely superior;
when used, they cooperate with the execution's asyncio/AnyIO runtime inside the optional connector
package rather than becoming Riko's runtime.

### 3.3 Credentials are references

Serialized configuration contains references such as:

```json
{"credential": "clients/contoso/sftp"}
```

It never contains passwords, private keys, access tokens, or URI user-info. A credential Resource
resolves material inside execution scope and redacts it from events/errors.

### 3.4 Definition is not execution

A Target can be normalized, validated structurally, fingerprinted, displayed, and serialized without
opening a connection.

Execution preparation resolves:

```text
Target
-> registered adapter contract
-> declared Resource bindings / credentials
-> execution-owned session
-> read/write operation
```

No network probing occurs merely because a workflow file was loaded.

### 3.5 No hidden duplicate downloads

HTTP Format selection should reuse known Target/path/media metadata before making additional requests.
Network probing is explicit and bounded. Do not perform unconditional HEAD + GET solely for generic
format detection.

### 3.6 Streaming and lifecycle

Connectors return lazy records, batches, `FeedResult`s, or artifact references where appropriate.
Sessions are execution-owned Resources and close on exhaustion, cancellation, error, or early
consumer termination. Connections are not opened once per item unless the protocol requires it.

## 4. Target registry and execution handoff

A dedicated `TargetRegistry` parallels `ModuleRegistry`.

A target definition identifies its concrete backend/provider:

```text
FILE
HTTP
S3
GCS
AZURE_BLOB
POSTGRES
AIRTABLE
...
```

Registered adapters may implement sync, async, or both read/write protocols. The private execution
adapts missing modes once through its shared worker/portal boundary.

Conceptually:

```python
adapter = target_registry.resolve(target.name)
resource = resources.connector
records = adapter.read(target, format=fmt, resource=resource)
```

or:

```python
result = adapter.write(target, records, format=fmt, operation=write_conf, resource=resource)
```

Those are conceptual roles, not a second public API alongside `Pipeline.read()` / `Pipeline.write()`.

Duplicate target-name registrations fail deterministically unless the extension registration policy
explicitly allows a qualified namespace/override.

## 5. Format resolution and HTTP handling

Canonical Format resolution order is owned by Workflow v2/effects:

```text
explicit Format
-> Target default
-> path/URL extension
-> target media type
-> error
```

Connectors provide trustworthy media metadata; they do not silently override an explicit/path-derived
Format. Generic body sniffing is not the default contract.

An HTTP adapter should expose response metadata needed by downstream interpretation/provenance:
status, final URL, selected headers, content/media type, request/provider ids, and timing where useful.
Size/redirect/time limits remain explicit.

Content extraction such as PDF/DOCX/HTML-to-text is downstream interpretation/transformation, not an
arbitrary serialized `postprocess` callable hidden inside HTTP transport.

## 6. Storage and file Targets

Initial finite adapters:

```text
FILE
S3
GCS
AZURE_BLOB
FTP
SFTP
```

OpenDAL or other maintained storage abstractions may back several adapters internally, but public
errors/events identify the Riko target plus underlying cause.

Directory reads require explicit glob/recursive/maximum-count policy. Remote object metadata should
be accessible without forcing content materialization.

### 6.1 File write behavior

Generic `Pipeline.write()` semantics are owned by `effects.md`: records pass through unchanged,
completion is reported through `WriteResult`, and graph position determines terminality.

The FILE adapter specializes that contract:

- streamable formats such as CSV/JSONL may encode per logical item;
- framed document formats may emit bounded incremental framing when possible;
- atomic replacement may use temp-write + flush/fsync/close + atomic rename;
- failed/cancelled publication cleans partial artifacts best-effort and emits no success result;
- keyed reconciliation against an existing document may stream the existing file where practical
  (for example `ijson` for large JSON) instead of materializing it wholesale.

The shipped compatibility `write`/`sink` collection verbs and `riko/targets.py` are migration inputs.
The target architecture does **not** retain a separate public `sink()` terminal. Append/merge/replace/
delete/upsert-style semantics are write-operation modes validated against Target capabilities.

File-open flags remain adapter implementation detail rather than the semantic write-mode axis.

## 7. Database / record-store Targets

Database/store adapters such as POSTGRES/AIRTABLE may expose keyed mutation capabilities:

```text
append
merge/upsert
replace
delete
```

The generic semantics remain in `effects.md`:

- required keys are explicit;
- unsupported modes fail preparation;
- idempotency participation is declared;
- successful completion reports truthful WriteResult metadata;
- destructive policy/approval may be more restrictive in provider/domain layers.

Do not encode these capabilities by adding a second public collection verb.

## 8. Mail connectors

Examples:

```text
IMAP Target / mail source adapter
SMTP Target / send action/write adapter where semantics fit
```

Requirements:

- parsed message metadata and raw MIME content remain distinguishable;
- attachment bodies may become artifacts above a configured threshold;
- mailbox checkpointing uses stable UID validity/UID semantics rather than timestamps alone;
- mailbox state persists through common FeedState/StateStore;
- SMTP side effects declare idempotency limitations;
- Microsoft 365-specific administration should prefer Microsoft provider adapters when generic SMTP/
  IMAP semantics are insufficient.

## 9. Broker connectors

Initial adapters may include:

```text
ZeroMQ PUB/SUB
RabbitMQ
Azure Service Bus
```

Every adapter declares delivery/acknowledgement semantics. Publishers/consumers project the shared
`Publisher` / `Subscription` protocols where applicable. Sessions are execution Resources.

At-least-once consumers expose message/change identity and acknowledgement handles needed to map
successful disposition/checkpoint behavior. Best-effort transports state message-loss limitations
explicitly.

## 10. Structured source adapters

### 10.1 CKAN / public APIs

Use maintained APIs with explicit pagination/filter support, bounded retries, and credential
references. REST collection traversal/cursors remain owned by `rest-incremental.md`.

### 10.2 Prometheus exposition

Parse current exposition formats through maintained parsers where possible. Preserve metric name,
labels, value, timestamp, and sample type. One scrape is finite; recurrence belongs to
`Pipeline.poll()` / feed-monitoring or external orchestration according to the intended run boundary.

### 10.3 Tabular files

CSV remains core-compatible as a Format; XLS/XLSX and other optional formats live in connector/
artifact extras. Frame conversion follows the capability/cost model from execution/tabular owners;
connectors do not impose pandas as a universal dependency.

## 11. Singer compatibility

Do not add permanent `fetchtap`/`singerexport` core modules that bypass common state/schema contracts.

Singer adapters map:

```text
Singer SCHEMA -> common schema/RDP projection
Singer RECORD -> records/batches
Singer STATE  -> FeedState / StateStore
```

RDP may project state for wire interchange but does not become a second checkpoint owner.
Subprocesses are execution-owned Resources with cancellation, stderr capture, bounded line size,
exit-code validation, and secret redaction.

## 12. SaaS and REST APIs

Generic public APIs may be represented through OpenAPI/MCP capabilities or HTTP/REST Targets rather
than one core module per SaaS provider. Provider packages are justified when provider semantics,
long-running operations, batching, identity mapping, webhooks, auth, or administration exceed generic
transport semantics.

Provider-specific Actions remain actions; do not disguise commands as fake write modes.

## 13. Capability/module projection

A connector/provider package may expose:

- registered Target adapter(s);
- named source/operator modules where transformation semantics warrant them;
- registered Actions;
- MCP/capability records;
- CLI command providers.

These surfaces share service/resource implementations rather than duplicating execution logic.

## 14. Phases

### C0 — Contracts and lifecycle spikes

- Target adapter protocol/conformance fixtures;
- registry collision rules;
- HTTP response metadata;
- FILE/HTTP lifecycle tests;
- credential redaction tests.

### C1 — Core-compatible FILE/HTTP adapters

- FILE Target read/write adapter;
- HTTP Target read adapter;
- explicit metadata/probing rules;
- Format inference integration;
- document extraction boundary.

### C2 — Object/transfer storage

- S3/GCS/Azure Blob;
- FTP/SFTP;
- directory limits/artifactization.

### C3 — Mail/brokers

- IMAP/SMTP;
- ZeroMQ/RabbitMQ/Service Bus as useful;
- acknowledgement/delivery contracts.

### C4 — Structured ecosystems

- XLS/XLSX;
- CKAN/Prometheus;
- Singer/core-state/RDP bridge;
- initial DB/record-store adapter proof.

### C5 — Catalog/CLI integration

- capability/Target discovery projection;
- inspect/test commands;
- deterministic conformance fixtures.

Forward cross-cutting implementation order is owned by
[implementation-sequence.md](implementation-sequence.md); these connector phases specialize R11 and
do not create a competing Core sequence.

## 15. Definition of done

1. Core imports no optional connector protocol library merely to parse Workflow v2.
2. No connector starts a private event loop/task group/portal.
3. Credentials never appear in serialized Target definitions, records, or event payloads.
4. Targets can be inspected/validated structurally without execution.
5. HTTP probing is explicit/bounded and no generic hidden duplicate download is required.
6. Every execution-owned session closes on early termination/cancellation/error.
7. Long-lived/recurring source state uses common FeedState/StateStore semantics.
8. Broker delivery semantics are declared against shared pub/sub/disposition contracts.
9. Singer state maps to core state; RDP is an interchange projection rather than generic owner.
10. Concrete adapters implement the same read/write/effect contracts without inventing `SourcePlan`,
    `SinkPlan`, a second `sink()` API, or connector-specific execution lifecycle.