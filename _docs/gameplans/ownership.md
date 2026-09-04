# Gameplan ownership

## 1. Purpose

Gameplans should describe one architectural contract in one place. Other plans may explain how they
consume that contract, but should not restate its API, lifecycle, or invariants.

Implementation dependency order is owned separately by
[implementation-sequence.md](implementation-sequence.md); it may order contracts but does not
redefine them. Commercial strategy is owned by `commercialization.md`; it owns no runtime contract.

## 2. Ownership rule

When two plans need the same concept:

1. choose one authoritative owner;
2. keep the complete contract, API shape, lifecycle, and tests in that owner;
3. replace copies in dependent plans with a short specialization note and link;
4. only repeat details when the dependent plan materially specializes semantics;
5. update this table if ownership changes.

Cross-plan examples are acceptable. Parallel specifications are not.

## 3. Authoritative contracts

| Contract | Authoritative gameplan | Other plans should contain only |
|---|---|---|
| immutable `Pipeline`, private sync/async execution, immutable `Context` | `execution-semantics.md` | domain-specific construction/execution examples |
| resource ownership/lifecycle/dependencies/bindings | `execution-semantics.md` | resource implementations and required local names |
| execution modes, boundedness, cancellation, ordering | `execution-semantics.md` | domain-specific constraints |
| generic `RetryPolicy`, timeout, error/disposition policy | `execution-semantics.md` | retryable-error classification/provider delay hints |
| `FeedResult`, `Metadata`, private per-item provenance/identity | `execution-semantics.md` | source/operator-specific metadata meaning |
| canonical identity/fingerprints/generation/idempotency | `execution-semantics.md` | domain-specific semantic identity hints |
| `FeedState`, `StateKey`, `StateRecord`, `StateStore`, CAS, `.checkpoint()` | `execution-semantics.md` | typed payload meaning for one source/operator |
| configured `StateStoreCapabilities`, serialization IDs, `validate_state()` | `execution-semantics.md` | backend-specific codec details |
| execution `Event`/`EventSink` transport/lifetime | `events.md` | feature-specific event payloads; optional consumer adapters |
| `Pipeline.cache()`, `CacheNode`, replay/fill/invalidate/Mezmoize integration | `cache.md` | backend Resource configuration; transport-specific caches remain separate |
| `WriteNode`, `ActionNode`, `write`, `WriteResult`/`ActionResult`, provider-neutral effect semantics | `effects.md` | concrete Target/action implementations and domain policy |
| canonical Workflow v2, normalization, node/edge families, ports, Inputs/Targets/Formats serialization | `extensibility.md` | semantic behavior remains with runtime owners |
| module/plugin/operation-pack registration mechanics | `extensibility.md` | package-specific registrations |
| fan-out, routing, `SubscribeNode`/`PublishEdge`, split/union/join topology | `fanout-topology.md` | domain-specific branch examples |
| Feed-native parser migration/streaming memory/streaming write implementation | `feed-native-streaming.md` | parser inference from callable owner; effect semantics from `effects.md` |
| connector sessions, transport lifecycle, credential references/resolution, concrete Target adapters | `connectors.md` | provider/protocol credential implementations |
| REST pagination, endpoint dependencies, cursor extraction/encoding, source-filter pushdown | `rest-incremental.md` | provider-specific REST vocabulary |
| recurring source observation/bootstrap/dedupe/change/anomaly policy | `feed-monitoring.md` | source-specific observation/cursor payload meaning |
| generic `Change`, `ChangeFeedSemantics`, tombstones, replay/history/order guarantees | `feed-monitoring.md` | source-specific mapping into shared change envelope |
| Pipeline batch semantics/backend negotiation | `execution-semantics.md` | representation-specific conversion details |
| Pandas, Arrow, Polars/frame boundaries | `tabular-interop.md` | where a frame boundary is used |
| file/artifact codecs, report contexts, rendering, artifact lineage | `artifact-conversion.md` | domain-specific artifact consumers |
| provider resources/actions, auth lifecycle projection, webhooks | `provider-integrations.md` | provider-specific capability implementations |
| provider-specific operation-asset discovery/export/deployment/inspection + target compatibility facts | `provider-integrations.md` | common normalization/compatibility/drift remains Operations as Code |
| `OperationHandle` and operation waiting | `provider-integrations.md` | provider status normalization/terminal mapping |
| `CapabilityInfo`, `CapabilityCatalog`, `CapabilityPlan`, discovery/effects/policy/security/approval | `mcp.md` | domain-specific metadata attached to capability IDs |
| Git-first `OperationSpec`/`OperationPlan`, validate/plan/apply/verify, import/compatibility/deployment drift | `operations-as-code.md` | provider/domain/orchestrator specializations |
| iterative loop runtime semantics | `execution-semantics.md` | agent/domain specialization; graph structure remains Workflow v2 ModuleNode |
| serialized agent scenarios/model/retrieval/evaluation policy | `agent-scenarios.md` | underlying Pipeline/loop/model/tool contracts |
| Microsoft Graph/ARM/PowerShell adapters/resources | `azure-automation.md` | administrative policy specialization |
| Microsoft desired-state `ChangePlan`, approval, verify/handoff | `microsoft-administration.md` | adapter mechanics from Azure plan |
| orchestration, scheduling, `PipelineRunRequest`/`PipelineRef`, durable run boundaries | `orchestration.md` | in-process finite primitive semantics |
| callable Pipeline node contract | `callable-pipes.md` | domain examples only |
| Click-native CLI/plugin contract | `cli.md` | package-owned Click commands calling services |
| currency/location reference tables | `reference-data.md` | consumers of tables |
| test-layer ownership + suite consolidation | `testing.md` | phase/domain-specific semantic tests remain with owner |
| `bado` <-> AnyIO helper/version audit + benchmarking | `bado-anyio-alignment.md` | async runtime semantics from execution owner |
| Windows Autopilot provisioning scenario | `autopilot-provisioning.md` | generic Microsoft/admin/wait contracts |
| pre-1.0 DX/release/package fidelity gate | `release-readiness.md` | API semantics remain with owners |
| implementation dependency graph / keep-refactor-supersede classification | `implementation-sequence.md` | no duplicate semantic contract |
| runtime defect taxonomy/open defect register | `correctness-audit.md` | row reference plus owning design/fix |
| commercial product/service packaging | `commercialization.md` | strategy only; no runtime/API ownership |

## 4. Important boundaries

### Definition versus execution

```text
extensibility.md / Workflow v2
    serializable graph definition
    nodes / edges / ports / Inputs / Targets / Formats
    normalization + strict structural validation

execution-semantics.md
    private execution of the normalized definition
    resource/task/portal lifetime
    provenance/state/retry/batch runtime
```

Authoring sugar is normalized once before execution. Runtime features must not reinterpret old port
names, omitted outputs, inline targets, or other authoring variants independently.

### Workflow structure versus feature runtime

Workflow v2 defines a complete structural vocabulary before every runtime feature is implemented:

```text
ModuleNode / ReadNode / WriteNode / CacheNode / ActionNode / SubscribeNode
StreamEdge / PublishEdge
```

Structural ownership in `extensibility.md` does not steal semantic ownership. Cache behavior belongs
to `cache.md`; effects to `effects.md`; subscription/split behavior to `fanout-topology.md`; state and
loop execution to `execution-semantics.md`.

### Event transport versus semantic events

`events.md` owns one execution-owned transport. Feature plans own payload meaning. CLI, GUI,
OpenTelemetry, and logging are consumers. No feature may invent a second callback/task lifecycle.

### Cache versus state versus transport caching

```text
cache.md
    explicit Pipeline.cache() replay boundary

execution-semantics.md
    StateStore/checkpoint recovery correctness

connectors/provider plans
    optional HTTP/provider-native response caches
```

These are not interchangeable. Seekability/materialization also does not imply cross-execution
cache replay.

### Read/write/action versus adapters

```text
extensibility.md
    serializable Target / Format + ReadNode/WriteNode/ActionNode structure

effects.md
    provider-neutral write/action dataflow + result/idempotency participation

connectors.md / provider-integrations.md
    concrete FILE/HTTP/S3/Postgres/Airtable/Intune/etc implementations
```

`write()` is the target public effect operation. It passes records through and reports completion via
`EventSink`; graph position determines terminality. Do not retain a second public `sink()` terminal to
encode keyed/destructive reconciliation. Those are write-operation/Target capabilities.

### Core state versus domain state

`execution-semantics.md` owns:

```text
FeedState[T]
StateKey[T]
StateRecord[T]
StateStore / AsyncStateStore
CAS
checkpoint owner/boundary/restore rules
```

`feed-monitoring.md` owns monitoring semantics; `rest-incremental.md` owns REST cursor extraction and
pushdown. Neither defines a parallel checkpoint/store protocol.

For opaque cursors, generic code persists/round-trips source JSON values without incrementing,
parsing, comparing, or inferring order.

### Transport versus collection semantics

`connectors.md` owns sessions, credentials, response envelopes, acknowledgements, and concrete
adapter behavior. `rest-incremental.md` owns REST collection traversal. `effects.md` owns generic
write/action dataflow semantics.

### Retry versus recurrence versus orchestration rerun

`execution-semantics.md` owns retrying one operation inside an execution. `feed-monitoring.md` owns
delays between independent finite observations. `orchestration.md` may rerun a whole bounded request.
Only one layer retries one failure domain.

### Batch semantics versus frame conversion

`execution-semantics.md` owns:

```python
Pipeline(batch=True, batch_size=...)
batch_backend = ...
```

Negotiation is capability/conversion-cost based:

```text
current representation
-> zero-copy/interchange-backed candidate
-> cheapest supported conversion
-> Python objects fallback
```

There is **no** global Arrow > Polars > Pandas preference. `tabular-interop.md` owns concrete frame
conversion details.

### Frames versus artifacts

`tabular-interop.md` owns in-memory representations. `artifact-conversion.md` owns serialized
formats/rendered artifacts. A connector may transport records or artifacts but does not own frame
APIs.

### Context/resources versus resolved resource values

`Context` contains immutable definitions. Resolved resource values belong to the private execution;
use concrete nouns such as client, session, connection, pool, or stream when the resource type is
known. Domain plans may define resource implementations or aliases but must not introduce public
`ExecutionContext` or mutable runtime-resource bags.

Generic resource terminology follows `execution-semantics.md`: say **resource value** for the value a
resource definition resolves to. Reserve **handle** for a genuine reference/control object whose
purpose is to identify or control something else, such as `OperationHandle`.

### Provider authentication versus credential storage

`connectors.md` owns credential reference/resolution/redaction rules. `provider-integrations.md` owns
provider-facing setup/status/refresh/revoke projections.

### Provider semantics versus common capability metadata

`provider-integrations.md` owns provider-specific resource/action meaning, environments, batching,
upsert, webhook, identity maps, operation behavior, and provider-native operation hooks. `mcp.md` owns
common capability identity/catalog/discovery/execution/security/approval.

### Provider import/export hooks versus operation normalization

```text
provider-integrations.md
    acquire/export/deploy/inspect provider-native assets
    provider compatibility facts

operations-as-code.md
    preserve import provenance
    normalize OperationSpec
    classify lossiness/confidence
    CompatibilityReport
    source/deployment identity + drift
```

### OperationPlan versus provider OperationHandle

`OperationPlan` is a resolved plan for one operation definition. `OperationHandle` represents one
already-started asynchronous provider job. Provider waiting remains provider-owned.

### OperationPlan versus CapabilityPlan versus ChangePlan

These remain distinct:

```text
OperationPlan      operations-as-code.md
CapabilityPlan     mcp.md
ChangePlan         microsoft-administration.md
```

An OperationPlan may aggregate/reference domain plans; it does not replace them.

### Apply versus execute

Operations as Code uses:

```text
validate -> plan -> apply -> verify
```

Core/MCP may use `execute` for Pipeline/capability execution. Do not add `execute` as a second name
for operation `apply`.

### Operations as Code versus orchestration

Operations as Code owns source definition/planning/reproducibility/compatibility/drift. Orchestration
owns when/where bounded phases run and durable handoff. An orchestrator must carry the exact approved
plan identity and may not silently re-plan before apply.

### Fan-out versus shared ancestry

`fanout-topology.md` owns explicit branch semantics. Shared DAG ancestry does not imply broadcast.
Canonical publication is `PublishEdge -> SubscribeNode`; split is a multi-output ModuleNode.

A source port may fan out to many edges; a target stream port has at most one incoming StreamEdge.
Fan-in operands use distinct indexed ports so traversal/JSON order is never semantic.

### Agent iteration versus DAG structure

There is no second AgentGraph. Agent workflows are ordinary Pipeline DAGs. Loop remains a ModuleNode;
its execution may be iterative internally while the graph stays acyclic.

### CLI adapter versus domain services

`cli.md` owns Click command/plugin registration, terminal configuration assembly, rendering, prompts,
and exit codes. CLI constructs immutable Context and passes event sinks through supported execution
configuration; it does not construct public executions.

### Testing layer versus semantic contract owner

`testing.md` owns where test layers live. Semantic gameplans own what must be tested. Cross-package
scenarios compose owner contracts instead of copying them into Core.

### Contract ownership versus implementation ordering

`implementation-sequence.md` states dependency order only. If its API text disagrees with a semantic
owner, fix the sequence document rather than creating a second contract.

## 5. Review checklist

Before merging a new gameplan or substantial update:

- Does it introduce a contract already owned above?
- Does it copy a dataclass/protocol/API from another plan?
- Does it create `ExecutionContext`, `BatchPipe`, `CheckpointStore`, `AgentGraph`, a public `sink()`
  terminal, or another competing generic runtime abstraction?
- Does it create another cache-store hierarchy instead of using the cache owner/Mezmoize boundary?
- Does it create a feature-specific event callback/task lifecycle instead of `EventSink`?
- Does it add graph fields/ports/edges outside canonical Workflow v2 without a format-version change?
- Does it infer fan-in order from traversal or edge-list order?
- Does it introduce a second `OperationSpec`, `OperationPlan`, `CapabilityCatalog`, `CapabilityPlan`,
  `ChangePlan`, `OperationHandle`, or `CompatibilityReport`?
- Does it use `execute` and `apply` interchangeably for Operations as Code?
- Does provider code create a second common capability catalog or compatibility report?
- Does orchestration silently re-plan an approved operation?
- Does commercial strategy move a product/control-plane concern into Core without semantic reason?
- Does it introduce an exhaustive state-store type registry instead of coarse capabilities + concrete
  preflight?
- Does it repeat lifecycle, retry, credential, state, identity, capability, change-feed, or
  boundedness rules?
- Does a new source invent another change/event envelope instead of mapping into `Change`?
- Is an opaque source cursor being parsed/incremented/compared by generic code?
- Is entity identity being incorrectly used as change identity for dedupe?
- Is a deletion being turned into absence despite a source tombstone?
- Is a source filter being confused with downstream Riko `filter`?
- Is `poll` being used for source recurrence or provider-operation waiting?
- Does batch guidance reintroduce a global dataframe library ranking?
- Could a repeated section become one paragraph linking to its owner?
- Are tests for the shared contract located only in the owner?
- Does the dependent plan test only its specialization/integration?

If the answer reveals two competing owners, resolve ownership before adding more detail.
