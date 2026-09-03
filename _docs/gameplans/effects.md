# Effects, write, and action gameplan

## 1. Mission

Define Riko's provider-neutral side-effect contract: `Pipeline.write()`, first-class action nodes,
completion/result reporting, and the boundary between graph semantics and concrete provider adapters.

This plan owns:

- `WriteNode` and `ActionNode` runtime semantics;
- pass-through dataflow behavior for effects;
- `WriteResult` / `ActionResult` reporting;
- provider-neutral Target/action invocation contracts;
- the relationship between effects and the execution `EventSink`;
- idempotency-capability participation consumed by state/retry semantics.

It consumes:

- `Target`/`Format`/Workflow v2 structural definitions from `extensibility.md`;
- execution/lifetime/EventSink transport from `execution-semantics.md`;
- idempotency key derivation from `execution-semantics.md`;
- concrete connector/provider implementations from `connectors.md` and
  `provider-integrations.md`;
- implementation ordering from `implementation-sequence.md`.

## 2. One public write effect

`write()` is a public Pipeline operation/effect, not a public module category and not a terminal by
definition:

```python
flow = flow.write(target, format=...)
```

On success, input records continue downstream unchanged. If the write is the graph leaf, ordinary
iteration naturally makes it terminal; if more nodes follow, chaining continues.

There is no separate target public `sink()` terminal. A second verb would encode terminality and
reconciliation as a separate surface even though both are properties of the write operation/graph
position.

Compatibility is intentionally asymmetric:

- the unreleased `sink()` API and sink-specific public/discovery/serialization surfaces are removed
  outright; there is no alias, deprecation period, or loader compatibility for them;
- the shipped `riko.modules.write` Python module remains only until R5C replaces it with
  `Pipeline.write()` / `WriteNode`, then is removed with no deprecated wrapper or discovery entry;
- released v1 workflow documents that contain the legacy `write` module are migrated at the v1
  loader boundary to canonical `WriteNode` during the bounded v1 compatibility window owned by
  `extensibility.md`.

Useful writer/adapter/codec mechanics may be refactored behind `WriteNode`; retaining implementation
mechanics does not retain either superseded public API.

## 3. Target, Format, Resource

The roles are deliberately separate:

```text
Target
    immutable endpoint/provider identity and reusable defaults

Format
    immutable serialization/interpretation identity and options

Resource
    live execution-owned client/session/credential-backed handle

ReadNode / WriteNode
    operation-specific acquisition or mutation semantics
```

Target does not own live clients. Resource bindings do not become durable Target data. Write mode,
keys, reconciliation policy, or per-operation idempotency options belong to the write operation, not
to reusable Target identity unless genuinely target-wide.

Concrete Target granularity follows actual backends/providers:

```text
FILE
HTTP
S3
POSTGRES
AIRTABLE
INTUNE
...
```

Formats are data formats:

```text
CSV
JSON
JSONL
GEOJSON
RSS
XML
TEXT
...
```

Pure Python serialization such as list/tuple conversion is not a Target/Format write backend.

## 4. Read versus write versus action

The semantic boundary is:

```text
read
    observe/acquire from a readable Target and interpret with Format

write
    reconcile/mutate records at a writable Target

action
    invoke a provider command whose semantics are not naturally record write
```

Examples:

```text
read FILE/HTTP/S3/Postgres rows          -> ReadNode
write records to FILE/AIRTABLE/Postgres  -> WriteNode
sync Intune device / reset endpoint      -> ActionNode
```

Do not force provider commands into fake write modes merely to reuse destination vocabulary.

## 5. WriteNode semantics

Conceptually:

```text
input record
    -> write operation
    -> same logical record downstream
```

A write may buffer internally when the destination format requires framing/atomic publication, but
that buffering must not change the Pipeline-level pass-through contract.

Successful completion aggregates per write node and emits a `WriteResult` through `EventSink`.
`WriteResult` is out-of-band execution information, not a replacement stream value.

A provider/file adapter may report useful counts/metadata such as created/updated/deleted/bytes or
artifact identity where its contract can do so truthfully. Core does not require every backend to
invent unsupported counts.

## 6. ActionNode semantics

`ActionNode` is a first-class node family with provider-owned stable `name` and schema-validated
`params`:

```json
{
  "id": "sync-device",
  "type": "action",
  "name": "sync_device",
  "target": "intune_devices",
  "resources": {"client": "intune"},
  "params": {"device_id": {"input": "device_id"}}
}
```

`params` are named action parameters validated by the registered action contract. They are distinct
from module `conf`; `conf` is reserved for `ModuleNode` parser/module configuration.

Like write, an action passes its input record through unchanged on success and emits `ActionResult`
out-of-band through `EventSink`.

Actions are not part of `Modules`; they have their own registered provider/action vocabulary.

## 7. EventSink boundary

The execution layer owns one event transport:

```python
flow = flow.with_execution(event_sink=events)
```

This gameplan defines effect-specific event/result values; it does not create effect-specific
callbacks or a parallel observer lifecycle.

Typical flow:

```text
WriteNode succeeds
    -> WriteResult -> EventSink
    -> original records continue

ActionNode succeeds
    -> ActionResult -> EventSink
    -> original records continue
```

Optional OpenTelemetry/CLI/UI consumers subscribe to the same execution event model through their
own adapters.

## 8. Sync/async adaptation

Targets/actions may provide sync, async, or both implementations. The private execution layer adapts
once at preparation/execution boundaries using its shared worker/portal machinery.

Adapters must not create private event loops, portals, executors, or task groups.

## 9. Idempotency and retry

Execution derives the common idempotency key from:

```text
(node_id, fingerprint, item_key, generation, iteration)
```

An effect contract declares whether/how the backend can honor that key. A retryable/resumable effect
that cannot honor idempotency fails validation unless the operation explicitly opts out according to
the common execution policy.

Retries reuse the same idempotency key; retries never create a new generation merely because an
attempt failed.

Provider-native version/ETag/request-id mechanisms should be used where they provide the same safety
more directly than re-hashing content.

## 10. Completion and failure

A successful write/action result is emitted only after the operation has met that adapter's success
contract. For asynchronous provider jobs, the provider layer may return/track an `OperationHandle`;
provider waiting remains owned by `provider-integrations.md`.

Failure rules:

- failed required write/action fails according to common error/retry policy;
- no successful `WriteResult`/`ActionResult` is emitted for a failed operation;
- partial downstream side effects cannot be rolled back by Riko merely because later execution fails;
- checkpoint advancement must not cross a failed required effect;
- cancellation/cleanup uses execution-owned lifetime primitives.

## 11. Write modes and reconciliation

Append/merge/replace/delete/upsert-style vocabulary may be normalized as write-operation semantics
when the Target supports them. Capability validation happens before source consumption where
possible.

Key rules:

- keyed/destructive modes declare their required keys/identity explicitly;
- unsupported modes fail preparation rather than silently degrading;
- destructive provider operations may additionally require plan/approval policy from higher-level
  provider/Operations-as-Code owners;
- a Target's supported capabilities do not make every operation safe by default.

Do not create a second public `sink()` API to distinguish these modes.

## 12. File/serialized writes

Streaming formats such as CSV/JSONL may encode incrementally. Document formats may use framing or a
bounded/temp artifact before atomic publication.

The generic rule is semantic rather than format-specific:

```text
write may stage internally
successful publication -> WriteResult
failed/cancelled publication -> no successful result; clean partial artifact best-effort
```

Detailed codecs remain owned by `artifact-conversion.md`; concrete FILE adapter mechanics belong to
`connectors.md`.

## 13. Testing

Required contracts:

1. sync and async write both pass original records downstream unchanged;
2. graph-leaf write and mid-pipeline write share the same semantics;
3. successful write emits one node-level completion result with truthful backend metadata;
4. failed write emits no success result;
5. ActionNode behaves analogously while remaining a distinct node family;
6. idempotency key remains stable across retries;
7. unsupported target mode/resource/action fails before source consumption when knowable;
8. sync-only and async-only target/action implementations adapt through the common execution bridge;
9. cancellation tears down resources without detached tasks;
10. Workflow v2 contains serializable Target/Format/resource references, never live handles;
11. the unreleased `sink()` surface has no compatibility alias or serialized loader form;
12. the legacy Python `write` module is absent after R5C while v1 serialized `write` migrates through
    the bounded v1 loader;
13. provider waiting remains provider-owned rather than becoming a generic ActionNode polling loop.

## 14. Definition of done

Riko has one provider-neutral effect model: `write` for record mutation/reconciliation and `action`
for provider commands, both pass logical records through, both report outcomes through the common
EventSink, and concrete providers can implement them without redefining execution, identity, or
lifecycle semantics.
