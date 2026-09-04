# Extensibility & ecosystem gameplan

> **Scope.** This plan owns the contracts/ecosystem plane: module contracts, plugins, canonical
> workflow serialization, observability integrations, adapter packages, optional execution drivers,
> and GUI integration. Runtime semantics are consumed from their owning gameplans rather than
> redefined here.

Related authoritative plans:

- [execution-semantics.md](execution-semantics.md) — immutable `Pipeline`, Context/Resource,
  execution, identity/idempotency, `FeedState`/`StateStore`, checkpoints, batch semantics;
- [fanout-topology.md](fanout-topology.md) — publish/subscribe/split/routing/fan-in topology;
- [cache.md](cache.md) — `Pipeline.cache()` / CacheNode replay semantics;
- [effects.md](effects.md) — `write` / action effect semantics and result reporting;
- [connectors.md](connectors.md) — connector/session/credential contracts and concrete adapters;
- [cli.md](cli.md) — Click-native CLI extension layer;
- [mcp.md](mcp.md) — capability catalog/execution policy;
- [operations-as-code.md](operations-as-code.md) — operation source-of-truth, OperationSpec/Plan,
  import/compatibility/deployment semantics consumed by operation-pack extensions;
- [implementation-sequence.md](implementation-sequence.md) — forward dependency order;
- [release-readiness.md](release-readiness.md) — pre-1.0 Python API compatibility/removal policy.

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
   never live clients, portals, channels, cache contents, or private execution objects.
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
input/output cardinality + declared port contract
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
Resolved resource values never become durable module-definition data.

Port declarations follow the Workflow v2 grammar. Fixed-output modules declare their ports directly;
configurable modules such as split/route derive the declared port set deterministically from
normalized node configuration. Edges connect declared ports; edges never create ports.

Deliverables:

- extend/normalize module metadata contracts;
- generate configuration JSON Schema from typed configs;
- expose declared input/output port metadata where applicable;
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

The evidence for all of this is one real external package, not another hundred internal tests. Keep
the `implementation-sequence.md` R12 proof as a hard pre-1.0 release criterion: entry-point
registration, a declared `Resource` dependency, a sync-only or async-only implementation adapted in
the opposite execution mode, an external `Publisher`/`Subscription` or `StateStore`, generated
discoverability that includes the extension, and no core edit.

Note the division of labor with R4B: R4B proves the **runtime architecture** can hold real external
resources early. R12 proves the **external package API**.

## E3. Canonical Workflow v2 specification

Workflow v2 is the single normalized graph/storage contract consumed by validation, compilation,
serialization, CLI/GUI tooling, and private execution preparation.

### E3.1 One normalization boundary

Flexible authoring and migration stop at one boundary:

```text
legacy v1
    -> migrate_v1_to_v2()

v2 authoring sugar
    -> normalize_workflow()

both
    -> strict canonical WorkflowSpec v2
    -> validate
    -> compile / serialize / execute
```

No compiler/runtime subsystem independently reinterprets authoring shorthand, old port names, inline
targets, omitted outputs, or legacy v1 shapes.

During the remaining 0.x line, Riko accepts **released** v1 documents only at the loader/migration
boundary, warns when migration occurs, normalizes immediately to v2, and serializes v2 only.
`migrate_v1_to_v2()` is pure and testable. A released v1 module node named `write` migrates
deterministically to canonical `WriteNode` plus its Target/Format representation; execution never
keeps a parallel v1 `write` runtime.

Released v1 terminal `_OUTPUT` pseudo-nodes are loader syntax only. `migrate_v1_to_v2()` consumes the
pseudo-node and its terminal wire, translates the producer endpoint to top-level canonical
`outputs`, and drops the pseudo-node before canonical validation. No canonical node/edge or v2
serializer recreates it.

The v1 loader is intentionally temporary. At **1.0**, normal workflow loading is v2-only and rejects
v1 input. The offline `migrate_v1_to_v2()` utility may remain as a rescue/conversion tool without
making v1 executable. Unreleased branch-only experiments, including the discarded public `sink()`
surface, receive no loader compatibility and are not accepted as legacy grammar merely because a
prototype once existed.

### E3.2 Canonical graph envelope

Canonical v2 uses top-level `nodes` and `edges` with explicit named outputs and typed inputs.

Every edge endpoint has the full form:

```json
{"node": "normalize-1", "port": "out"}
```

Canonical edge keys are only:

```text
source
target
```

Reject shorthand structural aliases such as `src`/`tgt` and `from`/`to` in canonical v2.

Top-level outputs are explicit references:

```json
"outputs": {
  "default": {"node": "normalize-1", "port": "out"},
  "errors": {"node": "route-1", "port": "out:invalid"}
}
```

There is no fake `type:"output"` module. Authoring may omit `outputs` only when exactly one
unambiguous leaf exists; normalization materializes `outputs.default`.

A canonical workflow must contain at least one executable node. Top-level `outputs` describe how a
non-empty graph is exposed; they do not make an empty graph meaningful. Legacy
`convert_dag({"modules": []})` therefore becomes a definition error when it is routed through this
normalization boundary rather than producing an output-only pseudo-graph.

### E3.3 Node families

Canonical node families are a closed discriminated union:

```text
ModuleNode
ReadNode
WriteNode
CacheNode
ActionNode
SubscribeNode
```

`ModuleNode` covers registered transforms/operators including split, branch, route, union, merge,
join, and loop. Loop remains a specialized registered module, not a separate LoopNode.

`ReadNode` and `WriteNode` reference serializable Target/Format definitions. `ActionNode` references
a registered provider/action identity. `CacheNode` carries cache semantic policy but never cache
contents. `SubscribeNode` owns subscription policy.

Node field meanings are consistent:

```text
id      graph-instance identity
name    stable registered implementation identity
label   optional human-readable text
conf    registered module configuration; ModuleNode only
params  registered action parameters; ActionNode only
```

Other node families use their own typed structural fields rather than `conf`.

Resource slots are declared by the owning contract; canonical nodes use a normalized `resources`
mapping. Authoring singular `resource` sugar is allowed only where the owning contract has exactly
one resource slot.

### E3.4 Edge families and topology

Canonical edges are:

```text
StreamEdge
PublishEdge
```

`PublishEdge` connects a producer output to a `SubscribeNode`; publication is relationship/delivery
semantics, not a PublishNode.

Port grammar:

```text
in / out             default port
in:N / out:N         positional port
out:<name>            semantic named output port
```

Legacy stable ports normalize as:

```text
_INPUT   -> in
_OTHER   -> in:1
_OTHER2  -> in:2
_OUTPUT  -> out
_OUTPUT2 -> out:1
_OUTPUT3 -> out:2
```

A source stream port may have many outgoing edges. A target stream port has at most one incoming
StreamEdge. Fan-in operands use distinct `in`, `in:1`, `in:2`, ... ports so ordering never depends on
edge-list/traversal order.

Split uses positional output ports (`out`, `out:1`, ...). Branch/route use semantic output ports such
as `out:matched`, `out:unmatched`, `out:a`. The node/module contract declares valid ports; edge
presence does not define the operator's port set.

Same-name serialized subscription targeting follows the fanout contract; explicit node ids can
select one declaration when necessary.

### E3.5 Node identity

Authoring node `id` is optional; canonical node `id` is required.

Omitted ids normalize deterministically to a readable registered-name/occurrence form:

```text
fetch-1
filter-1
filter-2
write-1
```

Generated ids identify this normalized graph definition. They are not promised stable across
structural edits. Authors provide explicit ids when a logical node/boundary must survive revisions,
for example durable state/checkpoint ownership or external references.

Graph `id` remains distinct from semantic fingerprint/version identity.

### E3.6 Inputs

Workflow inputs are top-level typed declarations and execution values arrive through
`Context.inputs`.

Structural references use:

```json
{"input": "customer_id"}
```

Canonical input declarations use full JSON Schema. Authoring shorthands normalize to that form.
Requiredness is inferred from absence of a default; `default:null` means the input has a default of
null and therefore must also be nullable. Canonical object schemas use
`additionalProperties:false` where the contract is closed.

### E3.7 Targets and Formats

`Target` is an immutable serializable endpoint/provider spec. `Format` is an immutable serializable
interpretation/serialization spec. Resource bindings to live clients are separate.

Canonical endpoint/provider vocabulary belongs under `Targets`, for example:

```text
FILE
HTTP
S3
POSTGRES
AIRTABLE
INTUNE
```

Canonical data formats belong under `Formats`, for example:

```text
CSV
JSON
JSONL
GEOJSON
RSS
XML
TEXT
```

Targets use concrete backend granularity and are behaviorally inert definitions; adapters own
behavior. A dedicated `TargetRegistry` parallels `ModuleRegistry`. Optional sync/async target
protocols allow execution to adapt an implementation through its normal bridge.

Read owns acquisition + interpretation. Write owns mutation/reconciliation. Format resolution order
is:

```text
explicit Format
-> Target default
-> path/URL extension
-> target media type
-> error
```

No generic content sniffing is part of canonical resolution. HTTP Content-Type is secondary to an
explicit/path-derived format rather than silently overriding it.

Formats are inline/self-contained in canonical nodes; inferred formats are made explicit by
normalization. Reusable Targets may be top-level declarations referenced by nodes; inline authoring
Targets normalize deterministically.

### E3.8 Loop, checkpoint, cache, and effects structure

Workflow v2 defines the **structure** needed for later runtime phases even when those phases have not
landed yet.

- loop remains a `ModuleNode` with structural `embed` and existing loop-owned options;
- absence of `until`/`max_iterations` means current one-run-per-parent loop semantics;
- presence of either iterative control opts into iterative semantics;
- checkpoint declarations may exist before a resumable owner is bound; compilation later resolves
  every reachable checkpoint to exactly one owner;
- CacheNode contains cache semantic identity/policy, not contents/live backends;
- WriteNode contains serializable target/resource/write-operation fields, not resolved resource values;
- ActionNode contains serializable target/resource/`params` fields, not module `conf` or resolved resource values;
- SubscribeNode contains subscription policy; PublishEdge structurally defines publishers.

### E3.9 Strict canonical validation

Canonical v2 is a closed contract. Unknown structural fields are errors rather than ignored
forward-compatibility bags.

Validation rejects, before source consumption where applicable:

```text
unsupported format_version
empty node set / no executable node
unknown node/edge family
unknown structural field
unknown/undeclared port
duplicate node id
missing referenced node
more than one StreamEdge into one target stream port
invalid/missing required fan-in positions
undeclared resource slot
unresolved Target/Resource/Input reference
invalid registered module conf when the module contract is available
invalid registered action params when the action contract is available
invalid registered target configuration when the target contract is available
```

Invalid graph/workflow structure raises `InvalidPipelineError`, a `PipelineError` subtype, rather
than leaking traversal accidents such as `IndexError`/`KeyError`. At the legacy DAG adapter boundary,
`convert_dag({"modules": []})` must fail immediately with this domain-error family (the message must
state that at least one module/node is required) once R4A owns conversion.

Forward compatibility comes from explicit `format_version`, not from an older runtime silently
executing a workflow whose new semantics it does not understand.

Extensions add registered vocabulary — modules, targets, actions, their schemas — rather than
arbitrary graph grammar fields.

### E3.10 Serialization and acceptance

Canonical serialization is deterministic. Array/map ordering is stable for byte-comparison/golden
fixtures, but semantic operator order comes from ids/ports/contracts rather than incidental JSON
array order.

Acceptance:

- every supported Pipeline topology round-trips without losing ports, stateful-owner identity,
  checkpoint placement, Target/Format/resource/input references, named outputs, cache/effect nodes,
  or publish edges;
- normalize(normalize(x)) is stable;
- v1 migration followed by v2 serialization never emits v1-only structure;
- a released v1 `_OUTPUT` pseudo-node migrates to top-level canonical `outputs` and is never emitted
  by v2 normalization/serialization;
- empty v1 DAGs and empty v2 workflows fail with `InvalidPipelineError` before graph traversal or
  source consumption;
- released v1 `write` normalizes to canonical `WriteNode` rather than executing a legacy module;
- normal v1 loading warns/migrates during 0.x and is rejected at the 1.0 runtime boundary, while an
  offline migration utility may remain;
- GUI/CLI validation consumes the same normalized model as execution preparation;
- a structurally valid node whose runtime capability is not implemented may round-trip, while
  execution fails with a clear unsupported-capability error.

An `OperationSpec` may reference/reuse a serialized Workflow v2 definition, but this gameplan does
not extend the workflow format with Operations as Code source-of-truth, plan/apply/verify, import,
compatibility, deployment, or drift semantics. Those stay in `operations-as-code.md`.

## E4. Observability hooks

Observability extends, rather than replaces, execution semantics.

R4B establishes the minimal execution-owned `EventSink` transport. Feature owners define their
semantic event/result payloads; this section owns ecosystem consumers/integration rather than a
second callback lifecycle.

Useful lifecycle events include:

```text
execution start/finish
node start/finish
item/batch counters
retry/disposition
resource open/close
cache hit/miss/bypass/invalidate
write/action result
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

Source/target interoperability includes:

- standardized discovery/config;
- schema/metadata when available;
- declared `Context` resource requirements;
- execution-owned session lifecycle;
- source/target provenance;
- explicit acknowledgement/delivery semantics;
- incremental source state represented through common `FeedState` / `StateStore`.

Singer compatibility maps Singer STATE to the common core state model; RDP may project it for wire
interchange but does not become a second checkpoint owner.

Multi-destination broadcast uses the shared Publisher/Subscription/fanout contract when the graph
actually broadcasts. Multiple independent WriteNodes are ordinary explicit graph effects. Multi-source
fan-in uses `union`/`merge` semantics from execution/fanout owners.

Provider-native operation import/export/deployment adapters are specialized provider extensions and
follow `provider-integrations.md`; their common normalized operation/compatibility model remains
owned by `operations-as-code.md`.

## E6. Experimental execution drivers

Optional drivers are allowed only after the local semantic contracts are stable.

A driver accepts a validated/prepared Pipeline definition or execution plan and reports normalized
outcomes. It must not reinterpret:

```text
graph topology
module/effect semantics
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
StreamEdge / PublishEdge
positional + semantic ports
split/route branches
SubscribeNode
read/write/action/cache nodes
loop scopes
checkpoint boundaries
resource/Target/Format/input references
named workflow outputs
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
- persisted-workflow migration/cutoff policy;
- benchmark/regression evidence.

Internal Python API compatibility/removal policy and release-package gating remain owned by
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
core identity / Context / Resource foundations
    ↓
canonical Pipeline + Workflow v2 definition
    ↓
private execution
    ↓
module/plugin contracts + runtime feature implementations
    ↓
observability/adapters/drivers/GUI consumers
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

- deterministic operation ID collisions and package/version provenance;
- lazy discovery without opening provider sessions;
- no credential material in package definitions;
- loading a pack never executes an operation or installs remote code;
- compatibility/API-version mismatch is reported before planning;
- operation-pack dependencies may reference provider/capability IDs but do not bypass capability
  discovery/policy;
- external operation packs require no edit to `nerevu/riko` Core.

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