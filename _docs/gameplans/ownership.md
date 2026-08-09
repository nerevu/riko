# Riko Gameplan Ownership

## 1. Purpose

Gameplans should describe one architectural contract in one place. Other plans may explain
how they consume that contract, but should not restate its API, lifecycle, or invariants.

Use this file as the ownership map when adding or reviewing gameplans.

## 2. Ownership rule

When two plans need the same concept:

1. choose one authoritative owner;
2. keep the complete contract, API shape, lifecycle, and tests in that owner;
3. replace copies in dependent plans with a short specialization note and link;
4. only repeat details when the dependent plan changes the semantics materially;
5. update this table if ownership changes.

Cross-plan examples are acceptable. Parallel specifications are not.

## 3. Authoritative contracts

| Contract | Authoritative gameplan | Other plans should contain only |
| --- | --- | --- |
| execution modes, boundedness, cancellation, ordering | `execution-semantics.md` | domain-specific constraints |
| connector sessions, transport lifecycle, credential references | `connectors.md` | provider/protocol specialization |
| REST pagination, endpoint dependencies, REST cursor extraction | `rest-incremental.md` | provider-specific REST vocabulary |
| source checkpoints, checkpoint stores, dedupe/change/anomaly monitoring state | `feed-monitoring.md` | source-specific cursor encoding |
| Pandas, Arrow, Polars, frame/batch conversion | `tabular-interop.md` | where a frame boundary is used |
| file/artifact codecs, report contexts, rendering, artifact lineage | `artifact-conversion.md` | domain-specific artifact consumers |
| provider resources/actions, auth lifecycle projection, webhooks, provider jobs | `provider-integrations.md` | provider-specific capabilities |
| fan-out, routing, subscriber lifecycle, `union`/`join` topology | `fanout-topology.md` | domain-specific branch examples |
| shared DAG structure/query/visualization for agents and pipelines | `agents.md` | scenario-specific topology policy |
| serialized agent scenarios, model policy, retrieval, evaluation | `agent-scenarios.md` | underlying DAG/model/tool contracts |
| Microsoft Graph/ARM/PowerShell adapters and Microsoft execution context | `azure-automation.md` | administrative policy specialization |
| desired-state Microsoft administration, ChangePlan, approval, verify/handoff | `microsoft-administration.md` | adapter mechanics from Azure plan |
| orchestration, external scheduling, durable run boundaries | `orchestration.md` | in-process finite primitive semantics |
| callable stage contract | `callable-stages.md` | domain examples only |
| extension/plugin registration | `extensibility.md` | package-specific registrations |

## 4. Important boundaries

### Transport versus collection semantics

`connectors.md` owns HTTP sessions, credentials, response envelopes, and lifecycle.
`rest-incremental.md` owns how a REST collection is traversed: record selection, pagination,
dependent endpoints, and extraction cursors.

### Source state versus REST cursors

`feed-monitoring.md` owns `SourceCheckpoint`, checkpoint stores, commit ordering, observation
state, dedupe, and change detection. `rest-incremental.md` only defines how REST requests and
responses encode/decode a cursor.

### Frames versus artifacts

`tabular-interop.md` owns in-memory Pandas/Arrow/Polars boundaries. `artifact-conversion.md`
owns serialized formats and rendered artifacts such as CSV/XLSX/Parquet/vCard/HTML/PDF.
A connector may transport either records or an artifact, but it does not own frame APIs.

### Provider authentication versus credential storage

`connectors.md` owns the rule that serialized workflows contain credential references and
the execution context resolves secret material. `provider-integrations.md` may define
provider-facing lifecycle capabilities such as status, refresh, revoke, or interactive
setup, but must not redefine secret storage/resolution.

### Microsoft adapter versus administration policy

`azure-automation.md` owns Microsoft execution mechanics: tenant/cloud context, auth adapter,
Graph/ARM/PowerShell clients, retry/throttling, and operation-status integration.
`microsoft-administration.md` owns desired-state planning, risk, approval, dry-run, verify,
audit evidence, and human handoffs.

### Agent graph versus scenario configuration

`agents.md` owns shared graph structure and pipeline-versus-agent execution separation.
`agent-scenarios.md` owns serialized rosters, model policies, tool grants, retrieval, and
evaluation. It should reference graph behavior rather than specifying a second DAG model.

## 5. Review checklist

Before merging a new gameplan or substantial update:

- Does it introduce a contract already owned above?
- Does it copy a dataclass/protocol/API from another plan?
- Does it repeat generic lifecycle, retry, credential, checkpoint, or boundedness rules?
- Could the repeated section become one paragraph linking to the owner?
- Are tests for the shared contract located only in the owner?
- Does the dependent plan test only its specialization/integration?

If the answer reveals two competing owners, resolve ownership before adding more detail.
