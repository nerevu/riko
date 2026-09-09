# Gameplan ownership

## 1. Purpose

Gameplans should describe one architectural contract in one place. Other plans may explain
how they consume that contract, but should not restate its API, lifecycle, or invariants.

Use this file as the ownership map when adding or reviewing gameplans. It exists to keep the
roadmap a routing map and prevent ecosystem work such as Operations as Code from creating parallel
versions of Core, provider, capability, security, or orchestration contracts.

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

Use one canonical term per concept. In particular, do not use a convenient synonym when the synonym
would blur ownership between `OperationPlan`, `CapabilityPlan`, `ChangePlan`, and `OperationHandle`,
or between operation `apply` and capability/Pipeline `execute`.

## 3. Authoritative contracts

| Contract | Authoritative gameplan | Other plans should contain only |
|---|---|---|
| immutable `Pipeline`, private sync/async execution, immutable `Context` | `execution-semantics.md` | domain-specific construction/execution examples |
| resource ownership/lifecycle/dependencies/bindings | `execution-semantics.md` | resource implementations and required local names |
| execution modes, boundedness, cancellation, ordering | `execution-semantics.md` | domain-specific constraints |
| generic `RetryPolicy`, timeout, error/disposition policy | `execution-semantics.md` | retryable-error classification and provider delay hints |
| `FeedResult`, `Metadata`, private per-item provenance/identity | `execution-semantics.md` | source/operator-specific metadata meaning |
| canonical identity/fingerprints/generation/idempotency | `execution-semantics.md` | domain-specific semantic identity hints |
| `FeedState`, `StateKey`, `StateRecord`, `StateStore`, CAS, `.checkpoint()` | `execution-semantics.md` | typed payload meaning for a particular source/operator |
| configured `StateStoreCapabilities`, standardized serialization IDs, and `validate_state()` preflight | `execution-semantics.md` | backend-specific codec support/documentation; no exhaustive generic `supported_types` registry |
| connector sessions, transport lifecycle, credential references/resolution | `connectors.md` | provider/protocol credential implementations |
| REST pagination, endpoint dependencies, REST cursor extraction/encoding, source-filter pushdown | `rest-incremental.md` | provider-specific REST vocabulary |
| recurring source observation/bootstrap/dedupe/change/anomaly policy | `feed-monitoring.md` | source-specific observation/cursor payload meaning |
| generic `Change`, `ChangeFeedSemantics`, tombstones, replay/history/order guarantees | `feed-monitoring.md` | source-specific mapping into the shared change envelope |
| Pipeline batch semantics/backend negotiation | `execution-semantics.md` | representation-specific conversion details |
| Pandas, Arrow, Polars/frame boundaries | `tabular-interop.md` | where a frame boundary is used |
| file/artifact codecs, report contexts, rendering, artifact lineage | `artifact-conversion.md` | domain-specific artifact consumers |
| provider resources/actions, auth lifecycle projection, webhooks | `provider-integrations.md` | provider-specific capability implementations |
| provider-specific operation-asset discovery/acquisition/export/deployment/inspection and target compatibility facts | `provider-integrations.md` | common normalization/compatibility/drift semantics remain in Operations as Code |
| `OperationHandle` and interval/event/hybrid **operation waiting** | `provider-integrations.md` | provider status normalization and terminal-state mapping |
| common `CapabilityInfo`, `CapabilityCatalog`, `CapabilityPlan`, discovery, effects, execution policy/security/approval | `mcp.md` | domain-specific metadata attached to shared capability IDs; callers may be more restrictive |
| Git-first operation source-of-truth semantics, `OperationSpec`, `OperationPlan`, operation reproducibility, validate/plan/apply/verify, normalized import provenance/lossiness, `CompatibilityReport`, deployment identity/drift, automation migration | `operations-as-code.md` | provider/domain/orchestrator specializations and examples only |
| fan-out, routing, subscriber lifecycle, `union`/`join` topology | `fanout-topology.md` | domain-specific branch examples |
| iterative agent workflow semantics | `agents.md` | scenario-specific model/tool policy; agents reuse Pipeline/loop |
| serialized agent scenarios, model policy, retrieval, evaluation | `agent-scenarios.md` | underlying Pipeline/loop/model/tool contracts |
| Microsoft Graph/ARM/PowerShell adapters and Microsoft resource implementations | `azure-automation.md` | administrative policy specialization |
| desired-state Microsoft administration, `ChangePlan`, approval, verify/handoff | `microsoft-administration.md` | adapter mechanics from Azure plan; OperationPlan may reference ChangePlan |
| orchestration, external scheduling, `PipelineRunRequest`/`PipelineRef`, durable run boundaries | `orchestration.md` | in-process finite primitive semantics; Operations as Code phase scheduling only |
| callable Pipeline node contract | `callable-pipes.md` | domain examples only |
| Click-native CLI/plugin contract | `cli.md` | package-owned Click commands calling reusable services |
| currency/location reference tables (`_reference.py`) + facades | `reference-data.md` | consumers of the tables |
| extension/plugin/operation-pack registration mechanics | `extensibility.md` | package-specific registrations; semantic models remain with their owners |
| test-layer ownership + suite consolidation | `testing.md` | phase/domain-specific tests remain with semantic owner |
| `bado` <-> AnyIO helper/version audit + benchmarking | `bado-anyio-alignment.md` | async primitive runtime semantics from `execution-semantics.md` |
| Feed-native parser migration/streaming-memory/streaming `write` | `feed-native-streaming.md` | `parser_mode` mechanism from `callable-pipes.md`; batch contract from `execution-semantics.md` |
| Windows Autopilot provisioning scenario | `autopilot-provisioning.md` | generic Microsoft adapters/admin/wait/module-enum contracts |
| Pre-1.0 DX/release/package fidelity gate | `release-readiness.md` | target API semantics remain owned by execution/fanout/callable/CLI gameplans |
| implementation dependency graph / keep-refactor-supersede classification | `implementation-sequence.md` | semantic contracts remain in their owning gameplans |
| runtime defect taxonomy/open defect register | `correctness-audit.md` | row reference plus owning design/fix |
| commercial product families, service packaging hypotheses, MissionOps tiers, commercialization sequencing | `commercialization.md` | **strategy only; no runtime/API ownership** |

## 4. Important boundaries

### Core versus ecosystem versus commercialization

```text
Riko Core
    Pipeline + execution/resource/state/identity primitives

ecosystem packages
    provider / MCP / Microsoft / Site / Operations as Code / orchestration adapters

commercial products/services
    managed services / hosted tooling / vertical packs / control planes
```

The roadmap maps these layers. Technical gameplans own ecosystem contracts. `commercialization.md`
may describe how those contracts create value, but commercial attractiveness never moves a contract
into Core or makes a roadmap idea a shipped promise.

### Core state versus domain state

`execution-semantics.md` owns the persistence primitives and lifecycle:

```text
FeedState[T]
StateKey[T]
StateRecord[T]
StateStore / AsyncStateStore
CAS
checkpoint owner/boundary/restore rules
```

`feed-monitoring.md` owns monitoring semantics such as bootstrap, dedupe, changed/anomaly,
alert-history payload meaning, and the generic `Change` / `ChangeFeedSemantics` change-feed
envelope. `rest-incremental.md` owns REST cursor extraction/encoding and source-filter
pushdown. Neither defines a parallel `SourceCheckpoint`, `CheckpointStore`, or generic state
store.

For an opaque cursor, generic code must persist and round-trip the source-level JSON value
through `FeedState` / `StateStore` without incrementing, parsing, comparing, or inferring
order from its representation.

State-store codec visibility is deliberately **coarse plus concrete** rather than exhaustive:

```text
store.capabilities
    configured-instance serialization / persistent / portable metadata

store.validate_state(state)
    authoritative concrete preflight for one FeedState value
```

Built-in serialization identifiers are standardized, extension formats use `<provider>:<name>`,
and there is no generic `supported_types` registry.

### Transport versus collection semantics

`connectors.md` owns sessions, credentials, response envelopes, acknowledgements, and
transport lifecycle. `rest-incremental.md` owns how a REST collection is traversed: record
selection, pagination, dependent endpoints, cursor extraction, and source-supported filter
pushdown.

### Change feed versus business change detection

These are intentionally separate contracts:

```text
Change / ChangeFeedSemantics
    what the upstream source says happened
    entity identity, source version/change identity, cursor, deletion, replay/order/history

changed(...)
    whether selected business fields differ from previously observed state
```

A source may emit a new version that `changed(...)` suppresses because selected business
fields are identical. A snapshot source may derive a business change without any
source-native change event. `feed-monitoring.md` owns both contracts and the distinction
between them.

### Entity identity versus change identity

Change-feed dedupe should normally use a stable change identity such as:

```text
(entity_id, version)
source-native event/change ID
```

rather than entity identity alone. `entity_id` identifies the logical thing over time;
change identity identifies one source-observed version/event of that thing.

Deletion tombstones retain entity/change identity and remain routable events rather than
being silently converted into absence.

### Source-filter pushdown versus pipeline filtering

`rest-incremental.md` owns declarative source-filter pushdown for APIs that support it.
Source filters execute upstream before transfer and may affect checkpoint validity.

Ordinary Riko `filter` pipes execute after acquisition and remain runtime transformation
semantics. A gameplan must not silently treat an arbitrary pipeline predicate as safe or
equivalent to an upstream filter.

### Source polling versus provider operation waiting

These are intentionally different contracts:

```text
Pipeline.poll / feed-monitoring.md
    repeat independent finite source observations or resume a data change feed

provider-integrations.md wait_operation
    track one already-started provider operation to terminal state
```

Do not expose interval/event/hybrid provider-operation waiting as a competing generic
`.poll()` API. `Pipeline.poll(source, interval=...)` is source recurrence; `Subscription.poll`
uses the same recurrence vocabulary for a subscription source.

### Retry versus recurrence versus orchestration rerun

`execution-semantics.md` owns retrying one operation inside a Riko execution.
`feed-monitoring.md` may define the delay/policy between independent finite observations.
`orchestration.md` may rerun the whole `PipelineRunRequest` or one owning service phase. Only one
layer retries a given failure domain. `CheckpointConflictError` is not automatically reloaded/rerun
by StateStore.

### Batch semantics versus frame conversion

`execution-semantics.md` owns:

```python
Pipeline(batch=True, batch_size=...)
batch_backend = ...
```

and the native -> Arrow -> Polars -> Pandas -> Python-list negotiation order.
`tabular-interop.md` owns concrete Pandas/Arrow/Polars boundaries and scalar/index/null
conversion. There is no public `BatchPipe` or `BatchPolicy` owner.

### Frames versus artifacts

`tabular-interop.md` owns in-memory representations. `artifact-conversion.md` owns serialized
formats/rendered artifacts such as CSV/XLSX/Parquet/vCard/HTML/PDF. A connector may transport
either records or artifacts but does not own frame APIs.

### Context/resources versus live runtime handles

`Context` is immutable configuration/resource definition. Live clients/sessions/handles are
execution-owned resolved resources. Domain plans may define resource implementations or
required aliases, but must not introduce a public `ExecutionContext` or treat
`Context.resources` as a mutable handle bag.

### Provider authentication versus credential storage

`connectors.md` owns credential reference/resolution/redaction rules.
`provider-integrations.md` owns provider-facing setup/status/refresh/revoke projections.
Provider packages implement shared credential/resource contracts rather than a new generic
token store.

### Provider semantics versus common capability metadata/discovery

`provider-integrations.md` owns provider-specific resource/action meaning, environments,
batching, upsert, webhook, identity-map, operation behavior, and provider-native operation-asset/
deployment hooks. `mcp.md` owns common capability identity/schemas/effects/catalog/discovery/
execution/security/approval policy.

A provider may discover its native resources/actions, but they project into `CapabilityCatalog`.
Operations as Code resolves against that catalog; it does not define another capability catalog.

### Provider import/export hooks versus operation normalization/compatibility

```text
provider-integrations.md
    discover/acquire native automation assets
    target-native import/export/deploy/inspect mechanics
    provider compatibility facts

operations-as-code.md
    preserve common import provenance
    normalize into OperationSpec
    classify lossiness/confidence
    produce CompatibilityReport
    compare source/deployment identity for automation drift
```

Do not create a provider-local `OperationSpec` or `CompatibilityReport`. Conversely, the operations
package must not embed SuperOps/Ninja/GitHub-specific API mechanics.

### Operation plans versus provider operation handles

```text
OperationPlan
    operations-as-code.md
    resolved plan for one OperationSpec invocation

OperationHandle
    provider-integrations.md
    one already-started asynchronous provider job
```

An `OperationPlan` may contain a planned `wait` step. Once apply starts an asynchronous provider
job, the returned `OperationHandle` and `wait_operation` semantics remain provider-owned.

### OperationPlan versus CapabilityPlan versus ChangePlan

```text
OperationPlan      operations-as-code.md
CapabilityPlan     mcp.md
ChangePlan         microsoft-administration.md
```

An `OperationPlan` aggregates/references domain plans; it does not replace them. Its fingerprint
must incorporate referenced plan identities so approval becomes stale when a nested plan changes.
Do not use an unqualified generic `Plan` type to collapse these contracts.

### Apply versus execute

Canonical Operations as Code phases are:

```text
validate → plan → apply → verify
```

Policy/approval is the gate between `plan` and `apply`. `execute` remains the term used by Core/MCP
where their contracts execute a Pipeline/capability. Do not add `execute` as a second name for
operation `apply`.

### Operations as Code versus orchestration

```text
operations-as-code.md
    canonical source definition
    OperationSpec / OperationPlan
    validate / plan / apply / verify coordination
    reproducibility / compatibility / deployment drift

orchestration.md
    when and where a bounded phase/run occurs
    durable handoff between phases
    scheduler/runner adapters
```

An orchestrator may split plan/apply/verify across durable tasks, but must carry the exact approved
plan identity and may not silently re-plan before apply. A vendor runner can host a derived copy; Git
remains canonical while Operations as Code is in use.

### Fan-out versus shared ancestry

`fanout-topology.md` owns explicit branch semantics. Shared DAG ancestry does not imply
broadcast. Branching is represented explicitly by `split()` or `publish()`. Public Python
vocabulary is `publish`/`subscribe`/`Publisher`/`Subscription`; low-level compatibility
`send`/`receive` names do not redefine the public target contract.

### Agent iteration versus DAG structure

`agents.md` does **not** own a second `AgentGraph`. Agent workflows are ordinary Pipeline
DAGs; the DAG remains acyclic and existing `loop` owns iterative state/termination. Agent
scenario plans configure model/tool/retrieval/evaluation policy over those primitives.

### Microsoft adapter versus administration policy

`azure-automation.md` owns Microsoft execution adapters/resource implementations and maps
provider responses to shared provider-operation contracts. `microsoft-administration.md`
owns desired-state/risk/`ChangePlan`/approval/verification/audit/handoff policy.

Generic retry/state/idempotency comes from `execution-semantics.md`; common capability policy
from `mcp.md`; operation waiting from `provider-integrations.md`; Operations as Code may reference
`ChangePlan` but does not redefine it.

### CLI adapter versus domain services

`cli.md` owns native Click command/plugin registration, terminal configuration assembly,
rendering, prompts, and exit codes. Plugins return/register Click commands; they do not
receive argparse parser objects. CLI constructs immutable `Context`; domain services create
private executions when needed.

`riko operation ...` commands are therefore CLI adapters over `riko-ops`; the CLI does not own
`OperationSpec`, plan/apply/verify, import, compatibility, deployment, or drift.

### Testing layer versus semantic contract owner

`testing.md` owns where doctest/public/internal/functional tests belong and suite consolidation.
The semantic gameplan owns what must be tested. Cross-package Operations as Code scenarios compose
provider/MCP/Microsoft/orchestration contracts without copying each owner's unit assertions into
Core.

### Contract ownership versus implementation ordering

`implementation-sequence.md` may state that identity must land before StateStore, or Context/Resource
before private execution resource opening. It may likewise sequence provider hooks before
Operations as Code scaffolding. That establishes dependency order only. If its API text disagrees
with a semantic owner, fix the sequence document rather than creating a second contract.

## 5. Review checklist

Before merging a new gameplan or substantial update:

- Does it introduce a contract already owned above?
- Does it copy a dataclass/protocol/API from another plan?
- Does it create `ExecutionContext`, `BatchPipe`, `CheckpointStore`, `AgentGraph`, or another
  competing generic runtime abstraction?
- Does it introduce a second `OperationSpec`, `OperationPlan`, `CapabilityCatalog`, `CapabilityPlan`,
  `ChangePlan`, `OperationHandle`, or `CompatibilityReport`?
- Does it use `execute` and `apply` interchangeably for Operations as Code?
- Does provider code create a second common capability catalog or compatibility report?
- Does orchestration silently re-plan an approved operation?
- Does commercial strategy move a product/control-plane concern into Riko Core without a core
  semantic reason?
- Does it introduce an exhaustive state-store type registry instead of the agreed coarse
  capabilities + concrete preflight contract?
- Does it repeat lifecycle, retry, credential, state, identity, capability, change-feed, or
  boundedness rules?
- Does a new source invent another change/event envelope instead of mapping into `Change`?
- Is an opaque source cursor being parsed, incremented, or compared by generic code?
- Is entity identity being incorrectly used as change identity for dedupe?
- Is a deletion being turned into absence even though the source provided a tombstone?
- Is a source filter being confused with a downstream Riko `filter` pipe?
- Is `poll` being used for source recurrence or provider operation waiting?
- Could the repeated section become one paragraph linking to its owner?
- Are tests for the shared contract located only in the owner?
- Does the dependent plan test only its specialization/integration?

If the answer reveals two competing owners, resolve ownership before adding more detail.
