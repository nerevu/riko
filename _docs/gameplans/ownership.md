# Gameplan ownership

## 1. Purpose

Gameplans should describe one architectural contract in one place. Other plans may explain
how they consume that contract, but should not restate its API, lifecycle, or invariants.

Use this file as the ownership map when adding or reviewing gameplans.

Implementation dependency order is owned separately by
[implementation-sequence.md](implementation-sequence.md); it may order contracts but does not
redefine them.

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
| generic `RetryPolicy`, timeout, error/disposition policy | `execution-semantics.md` | retryable-error classification and provider delay hints |
| `FeedResult`, `Metadata`, private per-item provenance/identity | `execution-semantics.md` | source/operator-specific metadata meaning |
| canonical identity/fingerprints/generation/idempotency | `execution-semantics.md` | domain-specific semantic identity hints |
| `FeedState`, `StateKey`, `StateRecord`, `StateStore`, CAS, `.checkpoint()` | `execution-semantics.md` | typed payload meaning for a particular source/operator |
| configured `StateStoreCapabilities`, standardized serialization IDs, and `validate_state()` preflight | `execution-semantics.md` | backend-specific codec support/documentation; no exhaustive generic `supported_types` registry |
| connector sessions, transport lifecycle, credential references/resolution | `connectors.md` | provider/protocol credential implementations |
| REST pagination, endpoint dependencies, REST cursor extraction | `rest-incremental.md` | provider-specific REST vocabulary |
| recurring source observation/bootstrap/dedupe/change/anomaly policy | `feed-monitoring.md` | source-specific observation/cursor payload meaning |
| Pipeline batch semantics/backend negotiation | `execution-semantics.md` | representation-specific conversion details |
| Pandas, Arrow, Polars/frame boundaries | `tabular-interop.md` | where a frame boundary is used |
| file/artifact codecs, report contexts, rendering, artifact lineage | `artifact-conversion.md` | domain-specific artifact consumers |
| provider resources/actions, auth lifecycle projection, webhooks | `provider-integrations.md` | provider-specific capability implementations |
| `OperationHandle` and interval/event/hybrid **operation waiting** | `provider-integrations.md` | provider status normalization and terminal-state mapping |
| common `CapabilityInfo`, effects, catalog, discovery/execution policy | `mcp.md` | domain-specific metadata attached to shared capability IDs |
| fan-out, routing, subscriber lifecycle, `union`/`join` topology | `fanout-topology.md` | domain-specific branch examples |
| iterative agent workflow semantics | `agents.md` | scenario-specific model/tool policy; agents reuse Pipeline/loop |
| serialized agent scenarios, model policy, retrieval, evaluation | `agent-scenarios.md` | underlying Pipeline/loop/model/tool contracts |
| Microsoft Graph/ARM/PowerShell adapters and Microsoft resource implementations | `azure-automation.md` | administrative policy specialization |
| desired-state Microsoft administration, ChangePlan, approval, verify/handoff | `microsoft-administration.md` | adapter mechanics from Azure plan |
| orchestration, external scheduling, `PipelineRunRequest`/`PipelineRef`, durable run boundaries | `orchestration.md` | in-process finite primitive semantics |
| callable Pipeline node contract | `callable-pipes.md` | domain examples only |
| Click-native CLI/plugin contract | `cli.md` | package-owned Click commands calling reusable services |
| currency/location reference tables (`_reference.py`) + facades | `reference-data.md` | consumers of the tables |
| extension/plugin registration | `extensibility.md` | package-specific registrations |
| test-layer ownership + suite consolidation | `testing.md` | phase-specific typing/file-map mechanics |
| `bado` <-> AnyIO helper/version audit + benchmarking | `bado-anyio-alignment.md` | async primitive runtime semantics from `execution-semantics.md` |
| Feed-native parser migration/streaming-memory/streaming `write` | `feed-native-streaming.md` | `parser_mode` mechanism from `callable-pipes.md`; batch contract from `execution-semantics.md` |
| Windows Autopilot provisioning scenario | `autopilot-provisioning.md` | generic Microsoft adapters/admin/wait/module-enum contracts |
| Pre-1.0 DX/release/package fidelity gate | `release-readiness.md` | target API semantics remain owned by execution/fanout/callable/CLI gameplans |
| implementation dependency graph / keep-refactor-supersede classification | `implementation-sequence.md` | semantic contracts remain in their owning gameplans |
| runtime defect taxonomy/open defect register | `correctness-audit.md` | row reference plus owning design/fix |

## 4. Important boundaries

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
and alert-history payload meaning. `rest-incremental.md` owns REST cursor extraction/encoding.
Neither defines a parallel `SourceCheckpoint`, `CheckpointStore`, or generic state store.

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
selection, pagination, dependent endpoints, and cursor extraction.

### Source polling versus operation waiting

These are intentionally different contracts:

```text
Pipeline.poll / feed-monitoring.md
    repeat independent finite source observations

provider-integrations.md wait_operation
    track one already-started provider operation to terminal state
```

Do not expose interval/event/hybrid provider-operation waiting as a competing generic
`.poll()` API. `Pipeline.poll(source, interval=...)` is source recurrence; `Subscription.poll`
uses the same recurrence vocabulary for a subscription source.

### Retry versus recurrence versus orchestration rerun

`execution-semantics.md` owns retrying one operation inside a Riko execution.
`feed-monitoring.md` may define the delay/policy between independent finite observations.
`orchestration.md` may rerun the whole `PipelineRunRequest`. Only one layer retries a given
failure domain. `CheckpointConflictError` is not automatically reloaded/rerun by StateStore.

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

### Provider semantics versus common capability metadata

`provider-integrations.md` owns provider-specific resource/action meaning, environments,
batching, upsert, webhook, identity-map and operation behavior. `mcp.md` owns common capability
identity/schemas/effects/catalog/discovery/execution/approval policy.

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
owns desired-state/risk/ChangePlan/approval/verification/audit/handoff policy.

Generic retry/state/idempotency comes from `execution-semantics.md`; common capability policy
from `mcp.md`; operation waiting from `provider-integrations.md`.

### CLI adapter versus domain services

`cli.md` owns native Click command/plugin registration, terminal configuration assembly,
rendering, prompts, and exit codes. Plugins return/register Click commands; they do not
receive argparse parser objects. CLI constructs immutable `Context`; domain services create
private executions when needed.

### Contract ownership versus implementation ordering

`implementation-sequence.md` may state that identity must land before StateStore, or Context/Resource
before private execution resource opening. That establishes dependency order only. If its API text
disagrees with a semantic owner, fix the sequence document rather than creating a second contract.

## 5. Review checklist

Before merging a new gameplan or substantial update:

- Does it introduce a contract already owned above?
- Does it copy a dataclass/protocol/API from another plan?
- Does it create `ExecutionContext`, `BatchPipe`, `CheckpointStore`, `AgentGraph`, or another
  competing generic runtime abstraction?
- Does it introduce an exhaustive state-store type registry instead of the agreed coarse
  capabilities + concrete preflight contract?
- Does it repeat lifecycle, retry, credential, state, identity, capability, or boundedness
  rules?
- Is `poll` being used for source recurrence or provider operation waiting?
- Could the repeated section become one paragraph linking to its owner?
- Are tests for the shared contract located only in the owner?
- Does the dependent plan test only its specialization/integration?

If the answer reveals two competing owners, resolve ownership before adding more detail.
