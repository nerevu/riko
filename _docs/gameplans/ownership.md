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
| generic `RetryPolicy`, timeout, error/disposition policy | `execution-semantics.md` | retryable-error classification and provider delay hints |
| connector sessions, transport lifecycle, credential references/resolution | `connectors.md` | provider/protocol credential implementations |
| REST pagination, endpoint dependencies, REST cursor extraction | `rest-incremental.md` | provider-specific REST vocabulary |
| source checkpoints, checkpoint stores, dedupe/change/anomaly monitoring state | `feed-monitoring.md` | source-specific cursor encoding |
| recurring source polling/bootstrap semantics | `feed-monitoring.md` | deployment cadence or source specialization |
| Pandas, Arrow, Polars, frame/batch conversion | `tabular-interop.md` | where a frame boundary is used |
| file/artifact codecs, report contexts, rendering, artifact lineage | `artifact-conversion.md` | domain-specific artifact consumers |
| provider resources/actions, auth lifecycle projection, webhooks | `provider-integrations.md` | provider-specific capability implementations |
| `OperationHandle` and interval/event/hybrid operation waiting | `provider-integrations.md` | provider status normalization and terminal-state mapping |
| common `CapabilityInfo`, effects, catalog, discovery/execution policy | `mcp.md` | domain-specific metadata attached to shared capability IDs |
| fan-out, routing, subscriber lifecycle, `union`/`join` topology | `fanout-topology.md` | domain-specific branch examples |
| shared DAG structure/query/visualization for agents and pipelines | `agents.md` | scenario-specific topology policy |
| serialized agent scenarios, model policy, retrieval, evaluation | `agent-scenarios.md` | underlying DAG/model/tool contracts |
| Microsoft Graph/ARM/PowerShell adapters and `MicrosoftContext` | `azure-automation.md` | administrative policy specialization |
| desired-state Microsoft administration, ChangePlan, approval, verify/handoff | `microsoft-administration.md` | adapter mechanics from Azure plan |
| orchestration, external scheduling, durable run boundaries | `orchestration.md` | in-process finite primitive semantics |
| callable pipe contract | `callable-pipes.md` | domain examples only |
| extension/plugin registration | `extensibility.md` | package-specific registrations |
| test-layer ownership (doctest/public/internal/functional) + suite consolidation | `testing.md` | phase-specific typing-split mechanics (`tests/typing/`) in MILESTONES P13 |
| `bado` ↔ AnyIO version-alignment audit (remove/replace/keep helpers) + async benchmarking/profiling | `bado-anyio-alignment.md` | the async-primitive *runtime semantics* (owned by `execution-semantics.md` Appendix A) |
| Feed-native pipe migration, streaming-memory model, streaming `write`/`STREAM_ENCODERS`, bounded `split`, sync/async streaming parity | `feed-native-streaming.md` | the `parser_mode` mechanism (`callable-pipes.md`), `BatchPolicy` (`execution-semantics.md` §16), serialized codecs (`artifact-conversion.md`), AnyIO floor (`bado-anyio-alignment.md`) |
| Windows Autopilot new-device provisioning scenario (input model, canonical tags, state machine, workflow) | `autopilot-provisioning.md` | generic Microsoft adapters (`azure-automation.md`), desired-state/ChangePlan/verify (`microsoft-administration.md`), `OperationHandle` waiting (`provider-integrations.md`), module-enum codegen (`module-enums.md`) |
| Pre-1.0 DX/API-shape polish + release/package fidelity gate (config strictness, Pipeline/Execution split, Collection→`from_sources`, `executor=`, optional-dep UX, wheel/PyPI CI, release triage) | `release-readiness.md` | *ecosystem* 1.0 conformance/deprecation windows (`extensibility.md` E7), pub/sub phases (`fanout-topology.md` F1/F4/F5), errors (P12), discoverability (`module-enums.md`), unified CLI (`cli.md`) |

## 4. Important boundaries

### Transport versus collection semantics

`connectors.md` owns HTTP sessions, credentials, response envelopes, and lifecycle.
`rest-incremental.md` owns how a REST collection is traversed: record selection, pagination,
dependent endpoints, and extraction cursors.

### Source state versus REST cursors

`feed-monitoring.md` owns `SourceCheckpoint`, checkpoint stores, commit ordering, observation
state, dedupe, and change detection. `rest-incremental.md` only defines how REST requests and
responses encode/decode a cursor.

### Source polling versus operation waiting

These are intentionally different contracts:

```text
feed-monitoring.md
    periodically observe a finite data source for new/changed records

provider-integrations.md
    wait for one already-started provider operation to reach terminal state
```

A source poll may create many independent records across repeated observations. An operation
wait tracks one operation identity and repeatedly re-reads its authoritative status.

Do not expose both as competing generic `.poll()` APIs.

### Retry versus recurrence versus orchestration rerun

`execution-semantics.md` owns retrying an operation **inside a Riko run**.

`feed-monitoring.md` may define delay/backoff between independent source observations after
a failed finite poll, but it should use the shared retry contract for retries within one
attempt.

`orchestration.md` may rerun the entire `PipelineRunRequest`. That is a run-level retry, not
another `RetryPolicy` implementation.

Only one layer should retry a given failure domain.

### Frames versus artifacts

`tabular-interop.md` owns in-memory Pandas/Arrow/Polars boundaries. `artifact-conversion.md`
owns serialized formats and rendered artifacts such as CSV/XLSX/Parquet/vCard/HTML/PDF.
A connector may transport either records or an artifact, but it does not own frame APIs.

### Provider authentication versus credential storage

`connectors.md` owns the rule that serialized workflows contain credential references and
the execution context resolves/redacts secret material.

`provider-integrations.md` may define provider-facing lifecycle capabilities such as setup,
status, refresh, or revoke, but must not redefine secret storage/resolution.

Provider packages such as `riko-microsoft` implement the shared credential-provider
contract rather than introducing their own generic token-provider protocol.

### Provider semantics versus common capability metadata

`provider-integrations.md` owns provider-specific resource/action meaning, identity,
environments, batching, upsert, and operation behavior.

`mcp.md` owns common capability identity, schemas, data shapes, effects, cataloging,
discovery, and execution/approval policy.

Provider, Microsoft, or agent plans should project into the common capability catalog rather
than maintain parallel `ToolSpec`/catalog definitions.

### Microsoft adapter versus administration policy

`azure-automation.md` owns Microsoft execution mechanics: `MicrosoftContext`, credential
implementations, Graph/ARM/PowerShell clients, throttle/error classification, and mapping
provider responses to `OperationHandle`.

`microsoft-administration.md` owns desired-state planning, Microsoft administrative
risk/scope metadata, ChangePlan, plan-bound approval, dry-run, verification, audit evidence,
and human handoffs.

Generic retry comes from `execution-semantics.md`; generic capability policy from `mcp.md`;
operation waiting from `provider-integrations.md`.

### Agent graph versus scenario configuration

`agents.md` owns shared graph structure and pipeline-versus-agent execution separation.
`agent-scenarios.md` owns serialized rosters, model policies, tool grants, retrieval, and
evaluation. It should reference graph behavior rather than specifying a second DAG model.

## 5. Review checklist

Before merging a new gameplan or substantial update:

- Does it introduce a contract already owned above?
- Does it copy a dataclass/protocol/API from another plan?
- Does it repeat generic lifecycle, retry, credential, checkpoint, capability, or boundedness
  rules?
- Is it using `poll` to mean source recurrence, operation waiting, or both?
- Could the repeated section become one paragraph linking to the owner?
- Are tests for the shared contract located only in the owner?
- Does the dependent plan test only its specialization/integration?

If the answer reveals two competing owners, resolve ownership before adding more detail.
