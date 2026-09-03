# Riko Roadmap

This is riko's **map**: the index of gameplans that hold detailed plans plus pointers to the
authoritative specs. The shipped runtime contract lives in
[RUNTIME_CONTRACT.md](RUNTIME_CONTRACT.md); as-built detail lives in
[IMPLEMENTED.md](IMPLEMENTED.md); live P-track status lives in
[PHASE_CHECKLISTS.md](PHASE_CHECKLISTS.md). Historical/pending P-track file maps and exit tests live
in [MILESTONES.md](MILESTONES.md), while forward implementation dependency order lives in
[implementation-sequence.md](gameplans/implementation-sequence.md).

Planned/end-state architecture is owned by the matching gameplan, not by the shipped runtime
contract. In particular, the reconciled Pipeline/Context/resource/pubsub/state/identity/batch
architecture is authoritative in
[execution-semantics.md](gameplans/execution-semantics.md).

## Core and ecosystem boundary

**Riko Core is the configurable Python pipeline engine.** Its job is to define, compose, inspect,
and execute reusable Pipelines with the common runtime contracts for Context/resources,
sync/async execution, identity/idempotency, state/checkpoints, fan-out, batching, retry, and
artifacts.

The broader **Riko ecosystem is built on Core**. Connect/RDP, provider integrations, MCP/AI,
Microsoft administration, site generation, orchestration adapters, and Operations as Code consume
Core contracts while owning their domain semantics in separate gameplans/packages.

That boundary matters for both architecture and product direction:

```text
Riko Core
    configurable Pipeline engine and runtime contracts
        ↓
ecosystem packages
    Connect / providers / MCP / AI / Microsoft / Site / Operations as Code
        ↓
applications and products
    managed services / hosted tooling / vertical solutions / control planes
```

The roadmap may point to strategic ecosystem opportunities, but they do not expand what the `riko`
package promises. Migration and automation portability are important Operations as Code adoption
levers; they are compatibility goals and reports, **not guarantees of lossless translation between
vendors**. Commercial packaging is documented separately in
[commercialization.md](gameplans/commercialization.md) and does not own runtime contracts.

## Which doc for which info

| I need… | Doc |
|---|---|
| What the engine **guarantees today** | [RUNTIME_CONTRACT.md](RUNTIME_CONTRACT.md) |
| What **actually ships / where it lives** | [IMPLEMENTED.md](IMPLEMENTED.md) |
| **Live phase status** | [PHASE_CHECKLISTS.md](PHASE_CHECKLISTS.md) |
| **P-track file maps / exit tests / phase history** | [MILESTONES.md](MILESTONES.md) |
| **Forward implementation dependency order** | [implementation-sequence.md](gameplans/implementation-sequence.md) |
| **Detailed target design** | matching [gameplan](#gameplans) |
| Git-first **Operations as Code** — reproducibility, validate/plan/apply/verify, deployment drift, import, and automation migration | [operations-as-code.md](gameplans/operations-as-code.md) |
| **Commercial ecosystem strategy** without changing Core contracts | [commercialization.md](gameplans/commercialization.md) |
| Public / EXT / private import surface | [API_SURFACE.md](API_SURFACE.md) |
| User migration / changelog | [MIGRATION.rst](MIGRATION.rst) · [CHANGES.rst](CHANGES.rst) |

Tie-breakers:

- shipped behavior -> RUNTIME_CONTRACT;
- as-built location -> IMPLEMENTED;
- live status -> PHASE_CHECKLISTS;
- P-track mechanics/history/file maps -> MILESTONES;
- forward implementation dependency order -> implementation-sequence;
- target/end-state API semantics -> owning gameplan;
- commercial packaging/market hypotheses -> commercialization, never a semantic owner.

`§N` contract topics and `PN` implementation phases are separate axes.

## Index

The complete `§0–27` routing map:

| § | Topic | Where it lives |
|---|---|---|
| 0 | Architectural direction | [contract](RUNTIME_CONTRACT.md#0-architectural-direction) · [execution-semantics](gameplans/execution-semantics.md) (target) |
| 1 | Product layers | [contract](RUNTIME_CONTRACT.md#1-product-layers) · [rdp-connect](gameplans/rdp-connect.md) |
| 2 | Core item & stream types | [contract](RUNTIME_CONTRACT.md#2-core-item-and-stream-types) |
| 3 | Pipe behavior | [contract](RUNTIME_CONTRACT.md#3-pipe-behavior) · [execution-semantics](gameplans/execution-semantics.md) (target Pipeline/execution split) |
| 4 | Callable pipes | [callable-pipes](gameplans/callable-pipes.md#4-callable-pipes) |
| 5 | Execution characteristics | [execution-semantics](gameplans/execution-semantics.md#5-execution-characteristics) |
| 6 | Async execution & backpressure | [contract](RUNTIME_CONTRACT.md#6-async-execution-and-backpressure) · [execution-semantics](gameplans/execution-semantics.md#6-async-execution-and-backpressure) |
| 7 | Timeout | [contract](RUNTIME_CONTRACT.md#7-timeout) · [execution-semantics](gameplans/execution-semantics.md#7-timeout) |
| 8 | Union & merge | [contract](RUNTIME_CONTRACT.md#8-union-and-merge) · [execution-semantics](gameplans/execution-semantics.md#8-union-and-merge) |
| 9 | Run status & exit codes | [contract](RUNTIME_CONTRACT.md#9-run-status-and-exit-codes) · [cli](gameplans/cli.md) (target CLI) |
| 10 | Delivery guarantee | [contract](RUNTIME_CONTRACT.md#10-delivery-guarantee) · [execution-semantics](gameplans/execution-semantics.md) (state/idempotency foundation) |
| 11 | Retry policy | [execution-semantics](gameplans/execution-semantics.md#11-retry-policy) |
| 12 | Errors & dispositions | [contract](RUNTIME_CONTRACT.md#12-errors-and-dispositions) · [execution-semantics](gameplans/execution-semantics.md#12-errors-and-dispositions) |
| 13 | Filter semantics | [contract](RUNTIME_CONTRACT.md#13-filter-semantics) · [execution-semantics](gameplans/execution-semantics.md#13-filter-semantics) |
| 14 | Lineage & acknowledgements | [rdp-connect](gameplans/rdp-connect.md#14-lineage-and-acknowledgements) · [execution-semantics](gameplans/execution-semantics.md) (item provenance/idempotency) |
| 15 | Stateful operators | [execution-semantics](gameplans/execution-semantics.md#15-stateful-operators) |
| 16 | Batch model | [execution-semantics](gameplans/execution-semantics.md#16-batch-model) · [tabular-interop](gameplans/tabular-interop.md) |
| 17 | Riko Data Protocol | [rdp-connect](gameplans/rdp-connect.md#17-riko-data-protocol) |
| 18 | State | [execution-semantics](gameplans/execution-semantics.md#stateful-execution-and-checkpoints) (core state/checkpoints) · [rdp-connect](gameplans/rdp-connect.md#18-state) (RDP projection) |
| 19 | Schema | [rdp-connect](gameplans/rdp-connect.md#19-schema) |
| 20 | Batch transports | [rdp-connect](gameplans/rdp-connect.md#20-batch-transports) · [tabular-interop](gameplans/tabular-interop.md) (in-memory representation) |
| 21 | Manifest durability | [rdp-connect](gameplans/rdp-connect.md#21-manifest-durability) |
| 22 | Memory limits | [execution-semantics](gameplans/execution-semantics.md#22-memory-limits) |
| 23 | AnyIO & Twisted | [contract](RUNTIME_CONTRACT.md#23-anyio-and-twisted) · [twisted-protocol-servers](gameplans/twisted-protocol-servers.md#23-anyio-and-twisted) |
| 24 | Module registry & plugins | [extensibility](gameplans/extensibility.md#24-module-registry-and-plugins) |
| 25 | Conversion & dataframe | [database-transforms](gameplans/database-transforms.md#25-conversion-and-dataframe-integration) · [tabular-interop](gameplans/tabular-interop.md) |
| 26 | Implementation roadmap | [implementation-sequence](gameplans/implementation-sequence.md) (forward dependency order) · [rdp-connect](gameplans/rdp-connect.md#26-implementation-roadmap) (RDP projection) · P-track docs (history/status) |
| 27 | Explicit non-goals | [rdp-connect](gameplans/rdp-connect.md#27-explicit-non-goals-for-the-initial-implementation) |

## Gameplans

### Core runtime & execution

| Gameplan | Covers |
|---|---|
| [execution-semantics.md](gameplans/execution-semantics.md) | Canonical target runtime: one immutable `Pipeline[T]`; private sync/async executions; immutable `Context`/resources; `FeedResult`/metadata/provenance; pub/sub/split lifecycle; canonical identity/fingerprints/idempotency; `FeedState`/`StateStore`/checkpoint/CAS; loop iteration; batch mode/backend negotiation; retry/backpressure/timeout/merge/memory semantics. |
| [callable-pipes.md](gameplans/callable-pipes.md) | §4 callable Pipeline nodes: `map`/`flat_map`, existing decorator/preparation model, Feed-native inference, declared resources, callable fingerprints/`version=`, identity modes, strictness, sync/async/process adaptation. |
| [fanout-topology.md](gameplans/fanout-topology.md) | Explicit fan-out/routing/fan-in: public `publish`/`subscribe`, `Publisher`/`Subscription`/`Channel`, `split`, buffering/isolation, branch lifecycle, union/join interaction. Low-level `send`/`receive` remain compatibility implementation vocabulary. |
| [feed-native-streaming.md](gameplans/feed-native-streaming.md) | Per-module Feed-native parser migration, streaming memory/encoder work, bounded source normalization. Batch details defer to the single-Pipeline batch contract rather than a public `BatchPipe`. |
| [feed-monitoring.md](gameplans/feed-monitoring.md) | Repeated finite observation, resumable change-feed semantics (`Change`/`ChangeFeedSemantics`, opaque cursors, entity-vs-change identity, tombstones, replay), bootstrap/backfill, dedupe/change/anomaly/alert policy using common `Pipeline.poll`, `FeedState`, `StateStore`, and publish/subscription contracts. |
| [bado-anyio-alignment.md](gameplans/bado-anyio-alignment.md) | `bado` <-> AnyIO helper audit, missing helpers, benchmarking/profiling; execution semantics remain owned by `execution-semantics.md`. |
| [twisted-protocol-servers.md](gameplans/twisted-protocol-servers.md) | Server-side protocol adapters; current §23 runtime remains in the contract. |
| [dotdict-parsing.md](gameplans/dotdict-parsing.md) | DotDict/business-data key handling. |
| [release-readiness.md](gameplans/release-readiness.md) | Pre-1.0 API/DX/release gate; Pipeline/execution split and pub/sub target must agree with the owning gameplans. |
| [correctness-audit.md](gameplans/correctness-audit.md) | Cross-repo correctness taxonomy/open defect register and merge-gate work. |

### Data, sources & connectors

| Gameplan | Covers |
|---|---|
| [connectors.md](gameplans/connectors.md) | Source/sink connector transports, credentials, sessions/resources, acknowledgements. |
| [rest-incremental.md](gameplans/rest-incremental.md) | First-class `rest` module, pagination, auth/resource references, dependent endpoints, cursor extraction (incl. opaque-cursor round-trip rule), source-side filter pushdown, and REST-backed change feeds using common `FeedState`/`StateStore`. |
| [highergov-feed.md](gameplans/highergov-feed.md) | HigherGov production path and current/transition integration examples. |
| [rdp-connect.md](gameplans/rdp-connect.md) | RDP/Connect projection: lineage/protocol/schema/transports/manifests/implementation milestones/non-goals; it no longer owns the generic core StateStore/checkpoint model. |
| [database-transforms.md](gameplans/database-transforms.md) | `riko-sql` / `riko-dbt`, declared database resources, streaming Pipeline batch mode, push-down/export/idempotency. |
| [tabular-interop.md](gameplans/tabular-interop.md) | Authoritative in-memory Pandas/Arrow/Polars boundary and batch representation negotiation for the single Pipeline. |
| [artifact-conversion.md](gameplans/artifact-conversion.md) | Serialized codecs/reports/rendered artifacts. |
| [enrichment-modules.md](gameplans/enrichment-modules.md) | Record/enrichment modules. |
| [reference-data.md](gameplans/reference-data.md) | Currency/location reference-data consolidation. |

### Extensibility & tooling

| Gameplan | Covers |
|---|---|
| [extensibility.md](gameplans/extensibility.md) | Module/plugin/workflow/observability/adapters/drivers ecosystem; §24 module registry; registration seams consumed by Operations as Code packs without owning operation semantics. |
| [module-registry.md](gameplans/module-registry.md) | P8 registry/resolution seam. |
| [module-enums.md](gameplans/module-enums.md) | Generated module enum/tree/discovery naming. |
| [cli.md](gameplans/cli.md) | Click-native CLI/plugin API, configuration, immutable Context assembly, output/events/approval/exit codes, PipelineRef run adapters, and thin Operations as Code command adapters. |
| [ownership.md](gameplans/ownership.md) | One-owner-per-contract map, canonical terminology, and boundary calls. |
| [implementation-sequence.md](gameplans/implementation-sequence.md) | Forward implementation dependency graph; classifies existing work as keep/refactor/supersede and sequences Operations as Code scaffolding without redefining semantic contracts. |

### AI & agents

| Gameplan | Covers |
|---|---|
| [ai-inference.md](gameplans/ai-inference.md) | Provider-neutral inference and embedding/retrieval adapters. |
| [ai-inference-research.md](gameplans/ai-inference-research.md) | Research/ADR rationale for AI inference. |
| [agents.md](gameplans/agents.md) | Agent-oriented workflows built from ordinary `Pipeline`, public pub/sub protocols, existing `loop` iterative state, common `StateStore`, and provider/tool side effects; no `AgentGraph`. |
| [agent-scenarios.md](gameplans/agent-scenarios.md) | Deterministic/policy-aware scenario/evaluation layer over the capability catalog. |
| [mcp.md](gameplans/mcp.md) | MCP **client-first** capability discovery/catalog/execution, OpenAPI/APIs.guru, execution-owned session resources, policy/artifacts/telemetry; Operations as Code consumes the same catalog/policy rather than defining another. |

### Providers, operations, Microsoft & orchestration

| Gameplan | Covers |
|---|---|
| [provider-integrations.md](gameplans/provider-integrations.md) | SaaS provider CRUD/search/webhooks/cache/batch/idempotent writes/identity mapping/browser fallback/async operations plus provider-specific operation-asset import/export/deployment/compatibility hooks using shared capability and Operations as Code models. |
| [operations-as-code.md](gameplans/operations-as-code.md) | **Operations as Code** — Git-first operation definitions, reproducibility, validate/plan/apply/verify, client/environment overlays, deployment targets and automation drift, import/normalization, compatibility analysis, and RMM/platform migration without redefining Core execution or orchestration. |
| [azure-automation.md](gameplans/azure-automation.md) | Azure ARM/PowerShell, Service Bus/Event Grid, desired-state adapters. |
| [microsoft-administration.md](gameplans/microsoft-administration.md) | Microsoft administrative desired-state/`ChangePlan`/approval/apply/verify semantics consumed by Operations as Code when Microsoft steps are present. |
| [autopilot-provisioning.md](gameplans/autopilot-provisioning.md) | Windows Autopilot provisioning scenario and long-running provider-operation proof. |
| [monthly-dashboard.md](gameplans/monthly-dashboard.md) | MSP monthly reconciliation/dashboard scenario: SuperOps/Graph/Action1/Huntress/Axcient providers → canonical device reconciler + license calc + QA invariants → Airtable sink; consumes the Microsoft/provider/sink/plan-apply contracts. |
| [orchestration.md](gameplans/orchestration.md) | Cron/webhook/Airflow/Prefect/Dagster/dbt run adapters; schedules bounded Pipeline/operation phases without owning Operations as Code source-of-truth or planning semantics. |

### Strategy, documentation & testing

| Gameplan | Covers |
|---|---|
| [commercialization.md](gameplans/commercialization.md) | Ecosystem commercialization strategy, Operations as Code adoption/managed-product paths, MSP client-facing products, and small-nonprofit MissionOps tiers; owns no runtime/API contract. |
| [module-documentation.md](gameplans/module-documentation.md) | Yahoo! Pipes module reference documentation. |
| [inspiration-coverage.md](gameplans/inspiration-coverage.md) | Traceability from preserved prior-art ideas to active gameplans. |
| [riko-site.md](gameplans/riko-site.md) | Framework-neutral site pipeline built on Core. |
| [testing.md](gameplans/testing.md) | Test-suite layering and file-by-file cleanup plan, including where Operations as Code cross-package scenario coverage belongs. |

### Retired redirects

| Gameplan | Covers |
|---|---|
| [productionizing.md](gameplans/productionizing.md) | Retired redirect into P-track/RDP/schema owners. |
| [repo-refinement.md](gameplans/repo-refinement.md) | Retired redirect into P-track and current extension gameplans. |

Implementation status remains authoritative only in
[PHASE_CHECKLISTS.md](PHASE_CHECKLISTS.md). P-track phase history/file maps/exit tests remain in
[MILESTONES.md](MILESTONES.md). Forward implementation dependency order is authoritative in
[implementation-sequence.md](gameplans/implementation-sequence.md). Historical phase language in
P-track documents must not override newer target API decisions in the owning gameplans.
