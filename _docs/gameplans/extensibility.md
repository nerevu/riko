# Extensibility & ecosystem gameplan

> **Scope.** This plan owns the contracts/ecosystem plane: module contracts, plugins, workflow
> serialization, observability, adapter packages, optional execution drivers, and GUI integration.
> Runtime semantics are consumed from their owning gameplans rather than redefined here.

Related authoritative plans:

- [execution-semantics.md](execution-semantics.md) — immutable `Pipeline`, Context/Resource,
  execution, identity/idempotency, `FeedState`/`StateStore`, checkpoints, batch semantics;
- [fanout-topology.md](fanout-topology.md) — publish/subscribe/split topology;
- [connectors.md](connectors.md) — connector/session/credential contracts;
- [cli.md](cli.md) — Click-native CLI extension layer;
- [mcp.md](mcp.md) — capability catalog/execution policy;
- [operations-as-code.md](operations-as-code.md) — operation source-of-truth, OperationSpec/Plan,
  import/compatibility/deployment semantics consumed by operation-pack extensions;
- [implementation-sequence.md](implementation-sequence.md) — forward dependency order.

This gameplan also retains the useful conclusions from prior-art research on issue #10: Pypes,
Mario, RssPercolator, Plagger, Turtle, node-machine, and the later comparison with Bonobo, petl,
Singer, Streamz, Bytewax, and FastPipe.

The organizing rule is **contracts before interfaces**: CLI, GUI, plugins, connectors, operation
packs, and optional drivers consume authoritative Pipeline/module/resource/state/operation contracts
rather than inventing parallel models.

## E0. Roadmap principles

1. **Contracts before interfaces.** Every extension surface consumes the same semantic contracts.
2. **Local semantics are authoritative.** Generated code and optional drivers must preserve the
   in-process Pipeline semantics.
3. **Explicit resources, identity, side effects, and boundedness.** A module declares what it needs
   and what semantic guarantees it provides.
4. **Optional integrations stay optional.** Plugin loading, OpenTelemetry, cloud SDKs, databases,
   and protocol clients do not inflate the minimal install.
5. **Version data, not runtime objects.** Workflow files store serializable definitions/references,
   never live clients, portals, channels, or private execution objects.
6. **Secure by default.** Loading a workflow or operation pack never installs or downloads
   executable code.
7. **Evidence before optimization.** Optional execution drivers/per-node optimizations require
   measurable benefit without semantic drift.
8. **Extensions specialize owners.** Operation packs, provider packages, and CLIs register
   implementations/references; they do not redefine `OperationSpec`, capability policy, provider
   waiting, or Core execution.

## E1. Module contract v1

Extend the existing `ModuleMetadata` / decorator metadata into one self-describing module contract
sufficient for validation, generated documentation, CLI/GUI inspection, plugin discovery, and
execution planning.

A module definition should expose, where applicable:

```text
stable name / contract version
type + subtype/role
sync/async implementation availability
input/output cardinality
configuration schema/defaults/required values
boundedness / ordering / stable-order guarantees
side-effect classification + idempotency support
identity mode when not inferable
Feed-native vs compatibility parser behavior
resource declarations
process/thread/inline adaptation safety
short description/examples/docs/distribution metadata
```

Do not add a second traits/runtime framework when existing decorator/module metadata can express the
same information.

State/checkpoint declarations are references to the common core model, not a module-specific store:

```text
stateless
stateful owner
checkpoint boundary support
source/observation FeedState production
```

A module does not declare a custom checkpoint protocol or lease mechanism.

Resource requirements use the common `resources=` declaration and execution wrapper preparation.
Live resource handles never become durable module-definition data.

Deliverables:

- extend/normalize module metadata contracts;
- generate configuration JSON Schema from typed configs;
- catalog/describe/schema inspection;
- deterministic built-in/plugin catalog export for docs/GUI;
- conformance helpers for extension authors.

Acceptance: built-ins and plugins validate through the same definition contract; invalid config or
resource/topology requirements fail before source consumption; catalog generation does not import
uninstalled optional dependencies unnecessarily.

## E2. Plugin ecosystem v1

Use Python package metadata entry points:

```toml
[project.entry-points."riko.modules"]
example = "riko_example:modules"
```

The shipped P8 architecture already separates:

```text
ModuleRegistry
    module implementations

PipelineResolver
    named composed pipelines

PipeResolver
    compiler-free resolution facade
```

Preserve that separation. Plugin work extends it rather than merging module and composed-Pipeline
resolution again.

Requirements:

- deterministic name conflicts/override policy;
- distribution/version provenance;
- isolated/reportable load failures;
- compatibility checks;
- application allow/deny policy;
- no remote-code installation during workflow load;
- no core edit per healthy external integration.

An installed Python plugin has host-process privileges; package installation is a trust decision.

## E3. Workflow specification v1

Give existing serialized pipeline/DAG forms a versioned interoperable storage contract.

Requirements:

```text
format_version
stable node IDs when durable identity requires them
explicit source/target ports
linear/fan-out/fan-in/split/publish-subscribe topology
loop/stateful-owner/checkpoint declarations
resource references
parameters/declared outputs
canonical JSON-compatible normalized representation
optional YAML authoring -> canonical representation
deterministic serialization
forward migration / explicit unsupported-version rejection
```

Serialized configuration references credentials/resources/callables symbolically. It does not embed
secret material or arbitrary Python objects.

Same-name serialized subscription targeting follows the fan-out owner contract; explicit IDs can
select one declaration when required.

Acceptance: every supported Pipeline topology round-trips without losing ports, stateful-owner
identity, checkpoint placement, resource references, or fan-out edges; GUI/CLI validation uses the
same normalized model as execution preparation.

An `OperationSpec` may reference/reuse a serialized workflow/Pipeline definition, but this gameplan
does not extend the workflow format with Operations as Code source-of-truth, plan/apply/verify,
import, compatibility, deployment, or drift semantics. Those stay in `operations-as-code.md`.

## E4. Observability hooks

Observability extends, rather than replaces, execution semantics.

Useful lifecycle events include:

```text
execution start/finish
node start/finish
item/batch counters
retry/disposition
resource open/close
publish/subscription lifecycle
checkpoint/state CAS outcome
cancellation/deadline
artifact publication
```

Optional OpenTelemetry integration consumes those events and does not become a required runtime.
Payload logging is opt-in and bounded; secrets and sensitive values are redacted.

### Core state versus optional distributed state

Earlier drafts deferred all durable checkpointing/recovery to an optional driver. That is
superseded.

Core owns the local semantic durability contract:

```text
FeedState
StateKey / StateRecord
StateStore / AsyncStateStore
CAS-only mutation
checkpoint boundaries
stateful-owner restore/cleanup
identity/generation/idempotency
```

Optional execution drivers may add **distributed coordination mechanics** such as worker ownership,
partition assignment, or remote state-store implementations, but they must project the same core
state semantics. They do not introduce a parallel checkpoint type or change recovery meaning.

Backpressure/buffering boundaries and bounded concurrency should be inspectable in execution plans.
Finite windows may be ordinary operators where useful; distributed stream processing is not implied.

## E5. Adapter and connector packages

Connector/package design follows [connectors.md](connectors.md): protocols and dependencies live in
optional packages unless they are broadly useful, small, and deterministic enough for core.

Useful adapter categories:

```text
file-like / iterable / async iterable
stdin/stdout
subprocess streams
HTTP / object storage / transfer protocols
mail / brokers
provider-specific sessions
Singer/RDP bridges
```

Source/sink interoperability includes:

- standardized discovery/config;
- schema/metadata when available;
- declared `Context` resource requirements;
- execution-owned session lifecycle;
- source/sink provenance;
- explicit acknowledgement/delivery semantics;
- incremental source state represented through common `FeedState` / `StateStore`.

Singer compatibility maps Singer STATE to the common core state model; RDP may project it for wire
interchange but does not become a second checkpoint owner.

Multi-sink broadcast uses the shared Publisher/Subscription/fan-out contract. Multi-source fan-in
uses `union`/`merge` semantics from execution/fan-out owners.

Provider-native operation import/export/deployment adapters are specialized provider extensions and
follow `provider-integrations.md`; their common normalized operation/compatibility model remains
owned by `operations-as-code.md`.

## E6. Experimental execution drivers

Optional drivers are allowed only after the local semantic contracts are stable.

A driver accepts a validated/prepared Pipeline definition or execution plan and reports normalized
outcomes. It must not reinterpret:

```text
graph topology
module semantics
resource ownership
identity/generation
checkpoint restore position
StateStore CAS
idempotency keys
retry/disposition semantics
fan-out ordering/lifecycle
```

Possible experiments:

- reference local driver over private SyncExecution/AsyncExecution;
- process-pool execution for explicitly process-safe nodes;
- remote worker/scatter-gather for eligible stateless or checkpoint-safe scopes;
- artifact transfer across explicit durable boundaries.

Per-node execution/adaptation hints may optimize particular callables, but ordinary users should not
need to hand-annotate every node. Pipeline-wide execution settings remain expressed through the
common `with_execution(...)` contract.

Non-goals for initial drivers:

```text
hosted scheduler service
workflow database as a core requirement
automatic cloud deployment
transparent execution of arbitrary installed modules on untrusted workers
generic distributed locks/leases in core
exactly-once claims
```

An Operations as Code external deployment target is not automatically an E6 execution driver. If a
GitHub Action, RMM, or Azure Automation job runs a generated artifact out of process, deployment and
run-boundary semantics come from `operations-as-code.md`, `provider-integrations.md`, and
`orchestration.md` respectively.

## E7. Visual tooling and 1.0 ecosystem readiness

A GUI is a separate consumer of exported module/workflow contracts. It should generate palette,
forms, validation, graph views, and help from static catalog/schema data and execute only through the
same service/API paths as Python/CLI.

The GUI must understand:

```text
ordinary data edges
publish/subscription edges
split/route branches
loop scopes
checkpoint boundaries
resource references
side-effect/provider nodes
materialization boundaries
```

It does not need private execution objects to render or validate a workflow.

An Operations as Code/control-plane UI may additionally render `OperationSpec`, `OperationPlan`,
compatibility, approvals, deployments, and drift by consuming `riko-ops` service contracts. Those
are not added to Core's workflow/GUI contract here.

The ecosystem side of 1.0 readiness includes:

- documented module/workflow/plugin contracts;
- compatibility/conformance tests;
- external plugin proof;
- external workflow consumer proof;
- recipe fixtures;
- migration/deprecation policy;
- benchmark/regression evidence.

Internal API/DX/release-package gating remains owned by
[release-readiness.md](release-readiness.md). In particular, target execution configuration is
`with_execution(...)`, not `with_config(executor=...)`.

Do not use this ecosystem plan to settle public/private import-tier cleanup; that work is maintained
separately in the API-surface/release documents.

## E8. Prior-art conclusions

The useful ideas survive, but they map onto the reconciled architecture:

| Project | Borrowed idea | Riko destination | Not copied |
|---|---|---|---|
| Pypes | graph of black-box components / named ports | module/workflow contracts | Stackless/Python-2 runtime assumptions |
| Mario | explicit stream/resource lifecycle | Resource/execution/connector lifecycle | byte-pump as primary data model |
| RssPercolator | async multi-source/multi-destination feeds | connectors + fan-out | feed-specific core runtime |
| Plagger | plugins + declarative recipes | E2/E3 | implicit global hooks |
| Turtle | composition/execution boundary + scatter/gather | optional E6 drivers | cloud-first runtime / downloaded-code execution |
| node-machine | machine-readable definitions | E1/E7 | overlapping invocation/control APIs |
| Bonobo | explicit injectable services/resources | Context/Resource declarations | service-container-centric architecture |
| petl | targeted table/data-quality primitives | selective high-value modules | full table algebra/dataframe engine |
| Singer | source/target/schema/state interoperability | connectors + core FeedState/StateStore + RDP projection | replication protocol as Riko's primary model |
| Streamz | backpressure/live branching/windows | execution/fan-out metadata/operators | reactive push framework replacing iterator core |
| Bytewax | durable keyed state/recovery + distributed workers | core state semantics + optional distributed driver mechanics | distributed engine/worker coordination in core |
| FastPipe | explicit concurrency/adaptation choices | execution planning / optional node hints | low-level concurrency as primary user API |

### Non-goals

Unless product direction changes materially, prefer adapters/drivers rather than absorbing:

- distributed worker coordination/partition ownership;
- cluster deployment/hosted workflow management;
- Streamz-style complete reactive dataframe semantics;
- petl-style comprehensive relational/table algebra;
- Singer's complete connector/replication ecosystem;
- Bonobo-style service-container-centric application architecture;
- concurrency primitives as the primary user-facing abstraction.

Durable local checkpoint/recovery is **not** on this non-goal list; its semantic contract is core.

### Product test

> Does this make Riko better at expressing, inspecting, or executing configuration-driven
> record-stream transformations, or mainly reproduce infrastructure another project specializes in?

If the latter, prefer an adapter/driver or higher ecosystem package.

### Dependency ordering

```text
core Pipeline / identity / Context / StateStore foundations
    ↓
E1 module contract
    ├── E2 plugins
    └── E3 workflow spec
           ↓
        E4 observability
           ↓
        E5 adapters
           ↓
        E6 optional drivers
           ↓
        E7 GUI/ecosystem readiness
```

Forward runtime dependency order is owned by `implementation-sequence.md`; E1–E7 specialize that
foundation rather than form a competing core sequence.

---

## 24. Module registry and plugins

The P8 registry/resolver seam is shipped and retained. Current work should build on:

```text
ModuleRegistry
PipelineResolver
PipeResolver
entry-point registration
```

Unqualified/built-in namespace reservations and `pipe_` / `pipe:` pipeline-name reservations must be
validated deterministically rather than accepted into a registry slot that can never resolve.

One-sided module implementations remain valid because execution adapts the missing mode:

```python
@processor
def pipe(item, **kwargs): ...


register(ModuleDefinition(name="example.normalize", sync_pipe=pipe))
```

or:

```python
@processor
async def pipe(item, **kwargs): ...


register(ModuleDefinition(name="example.lookup", async_pipe=pipe))
```

Supplying both sync and async implementations is an optimization when they genuinely differ, not a
parity requirement.

## 25. Operation packs and extension registration

Operations as Code creates an additional ecosystem consumer without moving operation semantics into
Core. `operations-as-code.md` remains authoritative for `OperationSpec`, `OperationPlan`,
validate/plan/apply/verify, import/compatibility/deployment, and drift.

A provisional installed-package seam may expose version-controlled operation definitions:

```toml
[project.entry-points."riko.operations"]
example = "riko_example.operations:definitions"
```

This gameplan owns the **registration mechanics** only. The provider returns references/serialized
operation definitions accepted by `riko-ops`; it does not define another operation model.

Requirements:

* deterministic operation ID collisions and package/version provenance;
* lazy discovery without opening provider sessions;
* no credential material in package definitions;
* loading a pack never executes an operation or installs remote code;
* compatibility/API-version mismatch is reported before planning;
* operation-pack dependencies may reference provider/capability IDs but do not bypass capability
  discovery/policy;
* external operation packs require no edit to `nerevu/riko` Core.

Provider importer/deployer implementations register through their provider package's extension
mechanism; `provider-integrations.md` owns those provider-specific contracts. CLI operation commands
register through `riko.commands`; `cli.md` owns that adapter surface.

Before freezing `riko.operations` as public, prove it with at least one external pack and one
cross-provider scenario. If the proof shows ordinary package/resource registries are sufficient,
reuse them rather than adding a redundant registry.

## Prior-art sources

Research sources retained by this plan:

- Pypes, Mario, RssPercolator, Plagger, Turtle, node-machine;
- Bonobo, petl, Singer, Streamz, Bytewax, FastPipe;
- Python packaging plugin/entry-point specifications;
- JSON Schema;
- OpenTelemetry Python.

Related issues include plugin discovery, benchmarks, pipeline format, GUI, protocol adapters, and
operation-pack distribution.
