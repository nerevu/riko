# Riko Roadmap

This is riko's **map**: the index of gameplans that hold every detailed plan, plus pointers
to the authoritative specs. The **runtime contract** (§0–25) lives in
[RUNTIME_CONTRACT.md](RUNTIME_CONTRACT.md); what already ships is in
[IMPLEMENTED.md](IMPLEMENTED.md) (its as-built companion); implementation status and sequence
are the P-track ([PHASE_CHECKLISTS.md](PHASE_CHECKLISTS.md)
+ [MILESTONES.md](MILESTONES.md)). This document just routes you to them.

## Which doc for which info

One doc owns each kind of information — go straight there:

| I need… | Doc |
|---|---|
| What the engine **guarantees** — item/stream model, pipe behavior, execution semantics, delivery, RDP end-state (the `§N` spec) | [RUNTIME_CONTRACT.md](RUNTIME_CONTRACT.md) |
| What **actually ships today** / where a shipped piece lives | [IMPLEMENTED.md](IMPLEMENTED.md) |
| **Live phase status** — what's done / next / suite count, and the decisions that survived | [PHASE_CHECKLISTS.md](PHASE_CHECKLISTS.md) (the tracker) |
| **How to build a pending phase** — files to create/edit, exit tests, dependency order (`PN`) | [MILESTONES.md](MILESTONES.md) |
| The **detailed plan for a topic** — HigherGov/Feed, extensibility E0–E8, connectors, CLI, MCP, RDP/Connect, callable pipes, execution semantics, … | the matching [gameplan](#gameplans) below |
| The public / EXT / private **import surface** | [API_SURFACE.md](API_SURFACE.md) |
| **Why** a design choice was made (prior-art comparison) | [extensibility.md § E8 / Prior-art sources](gameplans/extensibility.md#e8-prior-art-research-conclusions) |
| User **migration** (legacy → current) · **changelog** | [MIGRATION.rst](MIGRATION.rst) · [CHANGES.rst](CHANGES.rst) |

**Tie-breakers** where a single `§`/phase spans docs:
- **Behavior vs. as-built vs. status** are three questions about the same section → RUNTIME_CONTRACT (`§N` spec) · IMPLEMENTED (ships) · PHASE_CHECKLISTS tracker (status). Live status lives **only** in the tracker.
- **`§N` (contract behavior) ≠ `PN` (work phase).** A phase *implements* a contract concern; they are separate axes.
- **Done-phase detail → PHASE_CHECKLISTS; pending-phase design → MILESTONES.** When a phase lands, its substance graduates from a MILESTONES plan to a PHASE_CHECKLISTS summary.

## Index

The complete `§0–27` map — every section number to its home (no gaps). Bare-bones core
guarantees live in the contract; feature/end-state topics live in gameplans. What *ships* for
any of them is in [IMPLEMENTED.md](IMPLEMENTED.md).

| § | Topic | Where it lives |
|---|---|---|
| 0 | Architectural direction | [contract](RUNTIME_CONTRACT.md#0-architectural-direction) |
| 1 | Product layers | [contract](RUNTIME_CONTRACT.md#1-product-layers) (Core) · [rdp-connect](gameplans/rdp-connect.md) (Connect) |
| 2 | Core item & stream types | [contract](RUNTIME_CONTRACT.md#2-core-item-and-stream-types) |
| 3 | Pipe behavior | [contract](RUNTIME_CONTRACT.md#3-pipe-behavior) |
| 4 | Callable pipes | [callable-pipes](gameplans/callable-pipes.md#4-callable-pipes) |
| 5 | Execution characteristics | [execution-semantics](gameplans/execution-semantics.md#5-execution-characteristics) |
| 6 | Async execution & backpressure | [contract](RUNTIME_CONTRACT.md#6-async-execution-and-backpressure) · [execution-semantics](gameplans/execution-semantics.md#6-async-execution-and-backpressure) |
| 7 | Timeout | [contract](RUNTIME_CONTRACT.md#7-timeout) · [execution-semantics](gameplans/execution-semantics.md#7-timeout) |
| 8 | Union & merge | [contract](RUNTIME_CONTRACT.md#8-union-and-merge) (union) · [execution-semantics](gameplans/execution-semantics.md#8-union-and-merge) (merge) |
| 9 | Run status & exit codes | [contract](RUNTIME_CONTRACT.md#9-run-status-and-exit-codes) |
| 10 | Delivery guarantee | [contract](RUNTIME_CONTRACT.md#10-delivery-guarantee) |
| 11 | Retry policy | [execution-semantics](gameplans/execution-semantics.md#11-retry-policy) |
| 12 | Errors & dispositions | [contract](RUNTIME_CONTRACT.md#12-errors-and-dispositions) · [execution-semantics](gameplans/execution-semantics.md#12-errors-and-dispositions) |
| 13 | Filter semantics | [contract](RUNTIME_CONTRACT.md#13-filter-semantics) · [execution-semantics](gameplans/execution-semantics.md#13-filter-semantics) |
| 14 | Lineage & acknowledgements | [rdp-connect](gameplans/rdp-connect.md#14-lineage-and-acknowledgements) |
| 15 | Stateful operators | [execution-semantics](gameplans/execution-semantics.md#15-stateful-operators) |
| 16 | Batch model | [execution-semantics](gameplans/execution-semantics.md#16-batch-model) |
| 17 | Riko Data Protocol | [rdp-connect](gameplans/rdp-connect.md#17-riko-data-protocol) |
| 18 | State | [rdp-connect](gameplans/rdp-connect.md#18-state) |
| 19 | Schema | [rdp-connect](gameplans/rdp-connect.md#19-schema) |
| 20 | Batch transports | [rdp-connect](gameplans/rdp-connect.md#20-batch-transports) |
| 21 | Manifest durability | [rdp-connect](gameplans/rdp-connect.md#21-manifest-durability) |
| 22 | Memory limits | [execution-semantics](gameplans/execution-semantics.md#22-memory-limits) |
| 23 | AnyIO & Twisted | [contract](RUNTIME_CONTRACT.md#23-anyio-and-twisted) · [twisted-protocol-servers](gameplans/twisted-protocol-servers.md#23-anyio-and-twisted) |
| 24 | Module registry & plugins | [extensibility](gameplans/extensibility.md#24-module-registry-and-plugins) |
| 25 | Conversion & dataframe | [database-transforms](gameplans/database-transforms.md#25-conversion-and-dataframe-integration) |
| 26 | Implementation roadmap | [rdp-connect](gameplans/rdp-connect.md#26-implementation-roadmap) |
| 27 | Explicit non-goals | [rdp-connect](gameplans/rdp-connect.md#27-explicit-non-goals-for-the-initial-implementation) |

## Gameplans

Every detailed plan lives under [gameplans/](gameplans/). The per-`§N` map is the
[Index](#index) above; this table lists each gameplan and what it owns. The feature/end-state
`§N` (dropped from the bare-bones contract) are **owned** by the gameplan that covers them.

| Gameplan | Covers |
|---|---|
| [agent-scenarios.md](gameplans/agent-scenarios.md) | Agent scenarios, tools, retrieval & evaluation — a deterministic, policy-aware scenario layer over the capability catalog; extends `agents.md` (topology), `ai-Inference.md` (model calls), `mcp.md` (tool policy). |
| [agents.md](gameplans/agents.md) | Agent workflows — agent loop, tools. |
| [ai-Inference.md](gameplans/ai-Inference.md) | AI inference — provider `infer` modules, embedding/retrieval adapters. |
| [artifact-conversion.md](gameplans/artifact-conversion.md) | Serialized codecs, contact/card serialization, template-driven reports & rendered artifacts — the boundary that keeps the record-stream core out of document rendering (in-memory frames → `tabular-interop.md`). |
| [autopilot-provisioning.md](gameplans/autopilot-provisioning.md) | **Windows Autopilot new-device provisioning** — the first `riko-microsoft` (P14) scenario: CSV→auth→discover→plan→import→sync→profile-fallback→verify; specializes the Microsoft adapter/admin/operation-wait plans. |
| [azure-automation.md](gameplans/azure-automation.md) | Azure automation — ARM/PowerShell, Service Bus / Event Grid, desired-state. |
| [bado-anyio-alignment.md](gameplans/bado-anyio-alignment.md) | **`bado` ↔ AnyIO 4.14 alignment** — remove/replace/keep audit of the async helpers, **missing async helpers** (`async_memoize`, `throttle`) + async benchmarking/profiling methodology (execution-semantics owns the primitive *semantics*). |
| [callable-pipes.md](gameplans/callable-pipes.md) | **§4 callable pipes** — `map`/`flat_map`, `Opts` fields, decorator model, strict mode, thread/process execution (+ impl plan). |
| [cli.md](gameplans/cli.md) | CLI architecture, command-plugin system, config precedence. |
| [connectors.md](gameplans/connectors.md) | Source/sink connectors (HTTP, files, mail, brokers, CKAN/Prometheus/tabular, Singer). |
| [correctness-audit.md](gameplans/correctness-audit.md) | **Correctness audit of the non-module repo** — the defect taxonomy **C1–C12** (import-time state, unreachable guards, unread config, silent fabrication, leaked dependency errors, weaker duplicates, doc drift, non-determinism, dataclass-vs-TypedDict removal, omitted-vs-`None`, eagerly consumed streams, sync/async divergence), the phased plan (A0–A5) to apply it to `cast`/`types`/parsing/core/async/CLI, and the **open defect register R1–R19** — the verified branch-audit work list, whose P0 rows gate the `features` → `main` merge. |
| [database-transforms.md](gameplans/database-transforms.md) | `riko-sql` / `riko-dbt` (Ibis-backed reads, dbt coordination); owns **§25** (conversion & dataframe). |
| [dotdict-parsing.md](gameplans/dotdict-parsing.md) | DotDict parsing — business-data key handling. |
| [enrichment-modules.md](gameplans/enrichment-modules.md) | Record/enrichment modules (coalesce, transforms, near-duplicate, contact extraction); **retiring `geolocate`'s stub lookups** (§6b). |
| [execution-semantics.md](gameplans/execution-semantics.md) | **§5, §11, §12, §15, §16, §22** and the *planned* parts of **§6–§8, §13** — execution characteristics, retry, dispositions, stateful operators, batch model, memory limits, backpressure/timeout/merge/filter internals (incl. `receive`'s unbounded async wait, §7.1); + the async primitive reference (§ Appendix A). |
| [extensibility.md](gameplans/extensibility.md) | **Extensibility & ecosystem (E0–E8)** — module contract, plugins, workflow spec, observability, adapters, drivers, GUI + 1.0 readiness; owns **§24** (module registry). Prior-art sources. |
| [fanout-topology.md](gameplans/fanout-topology.md) | **Fan-out, routing & fan-in (F0–F7)** — branching topology as a first-class, inspectable concern: `split`, `send`/`receive`, `union`/`join`, conditional/named routing, buffering & slow-subscriber policy, subscriber lifecycle; owns the pub/sub phase mechanics **F1/F4/F5** that `release-readiness.md` rides on. **F5a** (`SyncPipe.subscribe`/`publish`, non-blocking marker-free drain) landed — see [IMPLEMENTED.md](IMPLEMENTED.md); **F5c** (`receive`'s `func` becomes a tap) is next; **F5b** (subscription handles + teardown ownership) lands with P11. |
| [feed-monitoring.md](gameplans/feed-monitoring.md) | Persistent feed monitoring & change detection — repeatedly observing finite sources and emitting new/changed/threshold/anomaly events without becoming a scheduler, daemon, or orchestrator. |
| [feed-native-streaming.md](gameplans/feed-native-streaming.md) | **Feed-native pipe migration & streaming memory model** — per-pipe audit, `batch_feed`/`BatchPolicy` batching, streaming `write` (`StreamEncoder`), bounded `split`, sync/async parity, unified stream-boundary source normalization (§7.1); discharges the P7 streaming-export carryover. |
| [highergov-feed.md](gameplans/highergov-feed.md) | **HigherGov-first critical path** (HG-0…HG-9) + **async `Feed` integration** — riko's first production use: schema contracts, `SyncPipe`/`AsyncPipe` callable pipes, bounded async I/O. |
| [inspiration-coverage.md](gameplans/inspiration-coverage.md) | Coverage index for `_docs/inspiration/` — which preserved Nerevu/external ideas carry forward into which gameplan, and which patterns are intentionally **not** revived (traceability, not a reimplementation commitment). |
| [mcp.md](gameplans/mcp.md) | MCP server implementation. |
| [microsoft-administration.md](gameplans/microsoft-administration.md) | Microsoft 365 / Entra / Azure administrative workflow semantics — desired state, preflight, dry-run, approval, verification, audit evidence, certificate lifecycle, manual handoffs; consumes the `azure-automation.md` adapters. |
| [module-documentation.md](gameplans/module-documentation.md) | Yahoo! Pipes module reference documentation. |
| [module-enums.md](gameplans/module-enums.md) | **P8 registry + P9A enum discoverability** — generated `Modules` tree, `derive_category` taxonomy, `codegen`/`gen-names` (P9A done; installed-env aggregate + `.pyi` stubs remain). |
| [module-registry.md](gameplans/module-registry.md) | **P8 module registry + resolution seam** — splitting `resolve_module`'s four conflated concerns so an external package can add modules without editing core and runtime pipe resolution stops importing the compiler. |
| [orchestration.md](gameplans/orchestration.md) | Orchestrator adapters (cron, webhook, Airflow/Prefect/Dagster, dbt). |
| [ownership.md](gameplans/ownership.md) | **The gameplan ownership map** — the one-owner-per-contract rule, the authoritative-contract table, and the boundary calls between overlapping plans. Read it before adding or reviewing a gameplan. |
| [productionizing.md](gameplans/productionizing.md) | *Retired → redirect.* Superseded by the P-track (its content maps onto P7–P12); RDP-spec draft → `rdp-connect.md`, schema-drift impl → `highergov-feed.md`. |
| [provider-integrations.md](gameplans/provider-integrations.md) | Provider semantics for authenticated SaaS APIs — resource CRUD/search, webhooks, caching, idempotent writes, identity mapping, browser fallback, async provider operations (**not** transport, secrets, REST pagination, retry, or monitoring checkpoints). |
| [rdp-connect.md](gameplans/rdp-connect.md) | **§14, §17–§21, §26, §27** + **Riko Connect** (§1) — RDP/Connect end-state: lineage, Riko Data Protocol, state, schema, batch transports, manifests, implementation milestones, non-goals. |
| [release-readiness.md](gameplans/release-readiness.md) | **Pre-1.0 DX polish & release gate** — pub/sub 1.0 contract, config-validation strictness, API-shape compression (Pipeline/Execution split, `Pipeline(source=…)`, `with_config`/`executor=`), optional-dep UX, wheel/PyPI release fidelity, the Must-land/Preferred/Can-wait triage. |
| [repo-refinement.md](gameplans/repo-refinement.md) | *Retired → redirect.* Its 18-item order maps 1:1 to P1–P14; extension families 15–18 → `connectors.md`, `database-transforms.md`, `orchestration.md`, `enrichment-modules.md`. |
| [rest-incremental.md](gameplans/rest-incremental.md) | Declarative REST-source layer — first-class pagination, auth references, dependent endpoints, incremental cursors, explicit source state (informed by dlt's `rest_api` and Singer tap/state conventions). |
| [riko-site.md](gameplans/riko-site.md) | riko site pipeline. |
| [tabular-interop.md](gameplans/tabular-interop.md) | **The authoritative in-memory tabular boundary** — moving finite record streams to/from Pandas, Arrow, and optionally Polars (serialized codecs and rendering → `artifact-conversion.md`). |
| [testing.md](gameplans/testing.md) | **P13 test-suite layering** — doctest/public/internal/functional ownership rule, the high-priority test-bug fixes, and the file-by-file fix/remove/consolidate plan. |
| [twisted-protocol-servers.md](gameplans/twisted-protocol-servers.md) | Server-side Twisted protocols via `asyncioreactor` + the **§23** protocol-adapter design (the §23 *current runtime* is in the contract). |

**Implementation status & sequence** for the runtime contract live in the authoritative
**P-track**: [PHASE_CHECKLISTS.md](PHASE_CHECKLISTS.md) (P1–P14 tracker + per-phase detail) +
[MILESTONES.md](MILESTONES.md) (file maps / exit tests). *(The former `productionizing.md`
and `repo-refinement.md` narrative plans were retired into that P-track; their stubs remain
as redirects.)*
