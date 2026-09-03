# Riko Roadmap

This is riko's **map**: the index of gameplans that hold detailed plans plus pointers to the
authoritative specs. The shipped runtime contract lives in
[RUNTIME_CONTRACT.md](RUNTIME_CONTRACT.md); as-built detail lives in
[IMPLEMENTED.md](IMPLEMENTED.md); live P-track status lives in
[PHASE_CHECKLISTS.md](PHASE_CHECKLISTS.md). Historical/pending P-track file maps and exit tests live
in [MILESTONES.md](MILESTONES.md), while forward implementation dependency order lives in
[implementation-sequence.md](gameplans/implementation-sequence.md).

Planned/end-state architecture is owned by matching gameplans, not by the shipped runtime contract.
The core target is deliberately split by responsibility:

- [execution-semantics.md](gameplans/execution-semantics.md) — Pipeline execution, resources,
  identity/provenance/state/batching/retry;
- [extensibility.md](gameplans/extensibility.md) — canonical Workflow v2 graph/serialization contract;
- [events.md](gameplans/events.md) — one execution-owned EventSink transport;
- [cache.md](gameplans/cache.md) — explicit Pipeline cache/replay semantics;
- [effects.md](gameplans/effects.md) — provider-neutral write/action side effects;
- [fanout-topology.md](gameplans/fanout-topology.md) — split/routing/pub-sub/fan-in topology.

## Core and ecosystem boundary

**Riko Core is the configurable Python pipeline engine.** Its job is to define, compose, inspect,
and execute reusable Pipelines with common contracts for Workflow v2 definitions, Context/resources,
sync/async execution, events, identity/idempotency, cache/replay, state/checkpoints, effects,
fan-out, batching, retry, and artifacts.

The broader **Riko ecosystem is built on Core**. Connect/RDP, provider integrations, MCP/AI,
Microsoft administration, site generation, orchestration adapters, and Operations as Code consume
Core contracts while owning their domain semantics in separate gameplans/packages.

```text
Riko Core
    configurable Pipeline definition + execution contracts
        ↓
ecosystem packages
    Connect / providers / MCP / AI / Microsoft / Site / Operations as Code
        ↓
applications and products
    managed services / hosted tooling / vertical solutions / control planes
```

The roadmap may point to strategic ecosystem opportunities, but they do not expand what the `riko`
package promises. Migration and automation portability are compatibility goals/reports, not
guarantees of lossless translation between vendors. Commercial packaging is documented separately
in [commercialization.md](gameplans/commercialization.md) and owns no runtime contract.

## Which doc for which info

| I need… | Doc |
|---|---|
| What the engine **guarantees today** | [RUNTIME_CONTRACT.md](RUNTIME_CONTRACT.md) |
| What **actually ships / where it lives** | [IMPLEMENTED.md](IMPLEMENTED.md) |
| **Live phase status** | [PHASE_CHECKLISTS.md](PHASE_CHECKLISTS.md) |
| **P-track file maps / exit tests / phase history** | [MILESTONES.md](MILESTONES.md) |
| **Forward implementation dependency order** | [implementation-sequence.md](gameplans/implementation-sequence.md) |
| Canonical **Workflow v2** graph/serialization contract | [extensibility.md](gameplans/extensibility.md#e3-canonical-workflow-v2-specification) |
| `Pipeline.cache()` replay behavior | [cache.md](gameplans/cache.md) |
| `write` / action side-effect semantics | [effects.md](gameplans/effects.md) |
| Execution event transport | [events.md](gameplans/events.md) |
| Explicit split/pub-sub/routing/fan-in topology | [fanout-topology.md](gameplans/fanout-topology.md) |
| Git-first **Operations as Code** | [operations-as-code.md](gameplans/operations-as-code.md) |
| **Commercial ecosystem strategy** | [commercialization.md](gameplans/commercialization.md) |
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
| 0 | Architectural direction | [contract](RUNTIME_CONTRACT.md#0-architectural-direction) · [execution-semantics](gameplans/execution-semantics.md) · [workflow-v2](gameplans/extensibility.md#e3-canonical-workflow-v2-specification) |
| 1 | Product layers | [contract](RUNTIME_CONTRACT.md#1-product-layers) · [rdp-connect](gameplans/rdp-connect.md) |
| 2 | Core item & stream types | [contract](RUNTIME_CONTRACT.md#2-core-item-and-stream-types) |
| 3 | Pipe behavior | [contract](RUNTIME_CONTRACT.md#3-pipe-behavior) · [execution-semantics](gameplans/execution-semantics.md) |
| 4 | Callable pipes | [callable-pipes](gameplans/callable-pipes.md#4-callable-pipes) |
| 5 | Execution characteristics | [execution-semantics](gameplans/execution-semantics.md#5-execution-characteristics) |
| 6 | Async execution & backpressure | [contract](RUNTIME_CONTRACT.md#6-async-execution-and-backpressure) · [execution-semantics](gameplans/execution-semantics.md#6-async-execution-and-backpressure) |
| 7 | Timeout | [contract](RUNTIME_CONTRACT.md#7-timeout) · [execution-semantics](gameplans/execution-semantics.md#7-timeout) |
| 8 | Union & merge | [contract](RUNTIME_CONTRACT.md#8-union-and-merge) · [execution-semantics](gameplans/execution-semantics.md#8-union-and-merge) · [fanout-topology](gameplans/fanout-topology.md) |
| 9 | Run status & exit codes | [contract](RUNTIME_CONTRACT.md#9-run-status-and-exit-codes) · [cli](gameplans/cli.md) |
| 10 | Delivery guarantee | [contract](RUNTIME_CONTRACT.md#10-delivery-guarantee) · [execution-semantics](gameplans/execution-semantics.md) · [effects](gameplans/effects.md) |
| 11 | Retry policy | [execution-semantics](gameplans/execution-semantics.md#11-retry-policy) |
| 12 | Errors & dispositions | [contract](RUNTIME_CONTRACT.md#12-errors-and-dispositions) · [execution-semantics](gameplans/execution-semantics.md#12-errors-and-dispositions) |
| 13 | Filter semantics | [contract](RUNTIME_CONTRACT.md#13-filter-semantics) · [execution-semantics](gameplans/execution-semantics.md#13-filter-semantics) |
| 14 | Lineage & acknowledgements | [rdp-connect](gameplans/rdp-connect.md#14-lineage-and-acknowledgements) · [execution-semantics](gameplans/execution-semantics.md) |
| 15 | Stateful operators | [execution-semantics](gameplans/execution-semantics.md#15-stateful-operators) |
| 16 | Batch model | [execution-semantics](gameplans/execution-semantics.md#16-batch-model) · [tabular-interop](gameplans/tabular-interop.md) |
| 17 | Riko Data Protocol | [rdp-connect](gameplans/rdp-connect.md#17-riko-data-protocol) |
| 18 | State | [execution-semantics](gameplans/execution-semantics.md#stateful-execution-and-checkpoints) · [rdp-connect](gameplans/rdp-connect.md#18-state) |
| 19 | Schema | [rdp-connect](gameplans/rdp-connect.md#19-schema) |
| 20 | Batch transports | [rdp-connect](gameplans/rdp-connect.md#20-batch-transports) · [tabular-interop](gameplans/tabular-interop.md) |
| 21 | Manifest durability | [rdp-connect](gameplans/rdp-connect.md#21-manifest-durability) |
| 22 | Memory limits | [execution-semantics](gameplans/execution-semantics.md#22-memory-limits) · [cache](gameplans/cache.md) |
| 23 | AnyIO & Twisted | [contract](RUNTIME_CONTRACT.md#23-anyio-and-twisted) · [twisted-protocol-servers](gameplans/twisted-protocol-servers.md#23-anyio-and-twisted) |
| 24 | Module registry & plugins | [extensibility](gameplans/extensibility.md#24-module-registry-and-plugins) |
| 25 | Conversion & dataframe | [database-transforms](gameplans/database-transforms.md#25-conversion-and-dataframe-integration) · [tabular-interop](gameplans/tabular-interop.md) |
| 26 | Implementation roadmap | [implementation-sequence](gameplans/implementation-sequence.md) · [rdp-connect](gameplans/rdp-connect.md#26-implementation-roadmap) · P-track docs |
| 27 | Explicit non-goals | [rdp-connect](gameplans/rdp-connect.md#27-explicit-non-goals-for-the-initial-implementation) |

## Gameplans

### Core runtime & definition

| Gameplan | Covers |
|---|---|
| [execution-semantics.md](gameplans/execution-semantics.md) | Immutable `Pipeline[T]` execution semantics; private sync/async executions and lifetime primitives; immutable Context/resources; FeedResult/provenance; identity/idempotency; StateStore/checkpoint/CAS; loop runtime; batch/retry/backpressure/timeout/merge/memory semantics. |
| [extensibility.md](gameplans/extensibility.md) | Canonical Workflow v2 normalization/serialization, node/edge/port grammar, Inputs/Targets/Formats structure, module/plugin contracts, ecosystem observability/adapters/drivers/GUI contracts. |
| [events.md](gameplans/events.md) | Minimal execution-owned `Event`/`EventSink` transport and optional-consumer boundary. |
| [cache.md](gameplans/cache.md) | `Pipeline.cache()` / `CacheNode` explicit replay semantics, Mezmoize integration, fill/manifest/invalidation/backend-failure behavior. |
| [effects.md](gameplans/effects.md) | Provider-neutral `write` / `ActionNode` semantics, Target/Format/Resource separation, pass-through behavior, WriteResult/ActionResult, idempotency participation. |
| [callable-pipes.md](gameplans/callable-pipes.md) | Callable Pipeline nodes: map/flat_map, decorator/preparation model, Feed-native inference, resources, callable fingerprints/version, identity modes, adaptation. |
| [fanout-topology.md](gameplans/fanout-topology.md) | Explicit StreamEdge/PublishEdge topology, SubscribeNode, publish/subscribe, split, branch/route ports, fan-in indexed inputs, buffering/isolation/lifecycle. |
| [feed-native-streaming.md](gameplans/feed-native-streaming.md) | Per-module Feed-native migration and streaming-memory/encoder work, staged with owning runtime phases; R10 is final cleanup rather than bulk migration start. |
| [feed-monitoring.md](gameplans/feed-monitoring.md) | Repeated finite observation, resumable change-feed semantics, bootstrap/backfill, dedupe/change/anomaly/alert policy using common state/pub-sub contracts. |
| [bado-anyio-alignment.md](gameplans/bado-anyio-alignment.md) | `bado` <-> AnyIO helper audit/benchmarking; runtime semantics stay with execution owner. |
| [twisted-protocol-servers.md](gameplans/twisted-protocol-servers.md) | Server-side protocol adapters; current §23 runtime remains in contract. |
| [dotdict-parsing.md](gameplans/dotdict-parsing.md) | DotDict/business-data key handling. |
| [release-readiness.md](gameplans/release-readiness.md) | Pre-1.0 API/DX/release gate. |
| [correctness-audit.md](gameplans/correctness-audit.md) | Cross-repo correctness taxonomy/open defect register and merge-gate work. |

### Data, sources & connectors

| Gameplan | Covers |
|---|---|
| [connectors.md](gameplans/connectors.md) | Concrete source/Target connector transports, credentials, sessions/resources, acknowledgements, and provider-neutral adapter mechanics; generic write semantics remain in `effects.md`. |
| [rest-incremental.md](gameplans/rest-incremental.md) | REST pagination/auth/resource references/dependent endpoints/cursor extraction/source-filter pushdown/change feeds. |
| [highergov-feed.md](gameplans/highergov-feed.md) | HigherGov production path and current/transition integration examples. |
| [rdp-connect.md](gameplans/rdp-connect.md) | RDP/Connect projection: lineage/protocol/schema/transports/manifests/non-goals; no parallel StateStore model. |
| [database-transforms.md](gameplans/database-transforms.md) | `riko-sql` / `riko-dbt`, declared DB resources, streaming batch mode, push-down/export/idempotency. |
| [tabular-interop.md](gameplans/tabular-interop.md) | Authoritative in-memory Pandas/Arrow/Polars boundary and representation conversion details. |
| [artifact-conversion.md](gameplans/artifact-conversion.md) | Serialized codecs/reports/rendered artifacts. |
| [enrichment-modules.md](gameplans/enrichment-modules.md) | Record/enrichment modules. |
| [reference-data.md](gameplans/reference-data.md) | Currency/location reference-data consolidation. |

### Extensibility & tooling

| Gameplan | Covers |
|---|---|
| [module-registry.md](gameplans/module-registry.md) | P8 registry/resolution seam. |
| [module-enums.md](gameplans/module-enums.md) | Generated module enum/tree/discovery naming. |
| [cli.md](gameplans/cli.md) | Click-native CLI/plugin API, Context assembly, EventSink/output/approval/exit codes, PipelineRef run adapters, Operations-as-Code adapters. |
| [ownership.md](gameplans/ownership.md) | One-owner-per-contract map and canonical boundary calls. |
| [implementation-sequence.md](gameplans/implementation-sequence.md) | Authoritative forward dependency graph; orders owner contracts without replacing them. |

### AI & agents

| Gameplan | Covers |
|---|---|
| [ai-inference.md](gameplans/ai-inference.md) | Provider-neutral inference and embedding/retrieval adapters. |
| [ai-inference-research.md](gameplans/ai-inference-research.md) | Research/ADR rationale for AI inference. |
| [agents.md](gameplans/agents.md) | Agent-oriented workflows built from ordinary Pipeline, loop, pub/sub, StateStore, and provider/tool effects; no AgentGraph. |
| [agent-scenarios.md](gameplans/agent-scenarios.md) | Deterministic/policy-aware scenario/evaluation layer. |
| [mcp.md](gameplans/mcp.md) | Client-first capability discovery/catalog/execution, OpenAPI/APIs.guru, resources, policy/artifacts/telemetry. |

### Providers, operations, Microsoft & orchestration

| Gameplan | Covers |
|---|---|
| [provider-integrations.md](gameplans/provider-integrations.md) | SaaS CRUD/search/webhooks/cache/batch/idempotent provider operations/identity mapping/browser fallback/async operations and provider-native operation-asset hooks. |
| [operations-as-code.md](gameplans/operations-as-code.md) | Git-first operations, reproducibility, validate/plan/apply/verify, overlays, deployment drift, import/normalization/compatibility/migration. |
| [azure-automation.md](gameplans/azure-automation.md) | Azure ARM/PowerShell, Service Bus/Event Grid, desired-state adapters. |
| [microsoft-administration.md](gameplans/microsoft-administration.md) | Microsoft ChangePlan/approval/apply/verify policy. |
| [autopilot-provisioning.md](gameplans/autopilot-provisioning.md) | Windows Autopilot provisioning scenario and long-running provider-operation proof. |
| [monthly-dashboard.md](gameplans/monthly-dashboard.md) | MSP monthly reconciliation/dashboard scenario: provider reads -> device/license/QA domain logic -> Airtable write Target; consumes common effects/provider/plan-apply contracts. |
| [orchestration.md](gameplans/orchestration.md) | Cron/webhook/Airflow/Prefect/Dagster/dbt run adapters and durable run boundaries. |

### Strategy, documentation & testing

| Gameplan | Covers |
|---|---|
| [commercialization.md](gameplans/commercialization.md) | Ecosystem commercialization strategy; no runtime/API ownership. |
| [module-documentation.md](gameplans/module-documentation.md) | Yahoo! Pipes module reference documentation. |
| [inspiration-coverage.md](gameplans/inspiration-coverage.md) | Traceability from prior-art ideas to active gameplans. |
| [riko-site.md](gameplans/riko-site.md) | Framework-neutral site pipeline built on Core. |
| [testing.md](gameplans/testing.md) | Test-suite layering/consolidation and cross-package scenario placement. |

### Retired redirects

| Gameplan | Covers |
|---|---|
| [productionizing.md](gameplans/productionizing.md) | Retired redirect into active owners. |
| [repo-refinement.md](gameplans/repo-refinement.md) | Retired redirect into active owners. |

Implementation status remains authoritative only in
[PHASE_CHECKLISTS.md](PHASE_CHECKLISTS.md). P-track phase history/file maps/exit tests remain in
[MILESTONES.md](MILESTONES.md). Forward implementation dependency order is authoritative in
[implementation-sequence.md](gameplans/implementation-sequence.md). Historical phase language in
P-track documents must not override newer target API decisions in the owning gameplans.
