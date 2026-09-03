# Finalized architecture implementation sequence

## 1. Purpose

Translate the reconciled target contracts into an implementation dependency graph for the
`features` branch.

This plan owns **implementation sequencing only**. Semantic ownership remains in the individual
gameplans, especially:

- `execution-semantics.md` — Pipeline/execution, Context/Resource, identity, state, batching;
- `fanout-topology.md` — publish/subscribe/split topology;
- `callable-pipes.md` — callable/decorator specialization;
- `feed-native-streaming.md` — per-module Feed-native migration;
- `provider-integrations.md` — provider semantics, operation waiting, provider-native operation
  import/export/deployment/inspection hooks;
- `mcp.md` — capability discovery/catalog/policy/approval;
- `operations-as-code.md` — `OperationSpec`, `OperationPlan`, Git source-of-truth,
  validate/plan/apply/verify, compatibility, migration, deployment drift;
- `orchestration.md` — external scheduling and durable run boundaries;
- `cli.md` — terminal adapters;
- `release-readiness.md` — public-release gate;
- `module-enums.md` — generated discoverability;
- `testing.md` — test-layer ownership.

The P-track remains useful as history/status, but its older P11/P12 sketches are not an API contract.
Where this dependency graph conflicts with a pending-phase sketch, the reconciled gameplan owner and
this graph win.

Operations as Code is deliberately sequenced **after** the shared Core/provider/capability seams it
consumes. This document may say when its scaffolding lands; it must not restate its types or
lifecycle contracts.

## 2. Existing work classification

### Keep as foundations

**P8 registry/resolver separation** is structurally correct:

- `ModuleRegistry` resolves module implementations;
- `PipelineResolver` resolves composed pipelines;
- `PipeResolver` is the compiler-free facade;
- entry-point registration remains the external-extension seam.

Do **not** redo that separation. Refactor its types and resolution API when the public `Pipeline`
class lands.

**P9A module-name/taxonomy work** is also retained. Generated module identifiers remain a discovery
layer over canonical string IDs. The remaining installed-environment aggregate and `.pyi` work can
proceed when it does not encode removed `SyncPipe`/`AsyncPipe` classes.

**P10 bounded execution algorithms** are retained conceptually:

- bounded async mapping;
- ordered/unordered delivery;
- worker pools/executors;
- shared concurrency-budget primitives.

Their current home in `collections.py` is temporary. Move reusable mechanics into private execution
modules rather than preserving `collections.py` as architecture.

### Retain but reshape

**Current module decorators/preparation** remain the parser invocation seam. Extend existing
preparation to inject declared execution-bound `resources`; do not add a second signature-based DI
system.

**Current `_serialize.py` canonicalization/cache work** is the starting point for one shared freezing
system, but its current representation is process-local and unsuitable for durable identity. Refactor
rather than layering a second serializer beside it.

**Current sync/async pub/sub hubs** are useful behavioral fixtures and migration inputs. Their
process/contextvar ownership and hidden sentinel/id bookkeeping are superseded by execution-owned
`Publisher`/`Subscription` runtime state.

### Superseded target designs

Do not implement these pending-plan shapes:

- public `ExecutionContext`;
- `BatchPipe` or a separate public `BatchPolicy` execution model;
- `SourceCheckpoint` / `CheckpointStore` parallel to `StateStore`;
- generic state-store leases;
- `state_checkpoint="replay"|"persist"`;
- separate `AgentGraph` / `AgentNetwork` execution system;
- argparse-shaped CLI plugin contracts;
- public `collect()` / `first()` execution terminals;
- execution knobs on `with_config()`;
- RDP-owned generic `Checkpoint` or sequence/expansion-path identity;
- a Core-owned `OperationSpec`/`OperationPlan` or second operation runtime;
- provider-local `CompatibilityReport` or capability catalog;
- orchestration-owned operation source-of-truth/planning semantics.

## 3. Dependency graph

```text
R0  characterization + type-name cleanup
 |
 +--> R1  stable error foundations
 |
 +--> R2  canonical identity/freezing --------------------+
 |                                                        |
 +--> R3  immutable Context + Resource ----------------+   |
 |                                                     |   |
 +---------------------> R4  Pipeline + private executions|
                              |                         |   |
                              +--> R5 FeedResult/_FeedItem--+
                              |          |
                              |          +--> R6 StateStore/checkpoint
                              |                    |
                              +--> R7 pub/sub/split+-----+
                              |                    |
                              +--> R8 batch execution    |
                              |                    |
                              +--> R9 loop/agent state <-+
                              |
                              +--> R10 Feed-native module migration

R1..R10 --> R11 CLI/orchestration/provider/MCP integration
                |
                +--> R11A Operations as Code scaffolding
                |
                +--> R12 external extension proof + release gate
```

`R11A` is a dependency-order label, not a new semantic owner or public phase family. The detailed
Operations as Code semantics remain in `operations-as-code.md`.

The graph is intentionally not identical to P8–P14 numbering. The reconciled architecture introduced
foundational identity/resource/state work that cuts across those phases.

## 4. PR sequence

### R0 — Characterization and internal naming

**Goal:** create a safe seam before public runtime replacement.

Changes:

- rename the internal parser callable alias `Pipeline` → `PipeCallable` everywhere;
- characterize the current resolver native-interface behavior;
- characterize source normalization (`Mapping`, iterable, `str`/`bytes`, generator, Feed,
  Awaitable);
- pin the current one-shot execution/lifecycle behavior that should move into private executions;
- add failing R2 regression coverage for omitted-vs-explicit-`None` reconfiguration;
- characterize current sync/async pub/sub semantics before deleting hub internals.

Keep P8 behavior unchanged except for type-name cleanup.

**Exit:** no public API change; tests prove the seams the following PRs will replace.

### R1 — Stable errors first

**Goal:** avoid landing new foundations with temporary builtin exceptions.

Add/normalize the Riko-owned families needed by later PRs:

```text
RikoError
├── ConfigurationError
├── ModuleDefinitionError / ModuleResolutionError / ModuleRegistrationError
├── PipelineStateError
├── ResourceError
├── IdentityError
│   ├── InvalidIdentityError
│   ├── StateKeyError
│   ├── IdentityEncodingError
│   └── CyclicIdentityError
├── StateStoreError
│   ├── StateCodecError
│   │   ├── StateSerializationError
│   │   └── StateDeserializationError
│   └── CheckpointConflictError
├── PublishError
└── SubscriptionError
```

Do not force every current legacy call site through the new hierarchy in this PR. Establish the
public types and use them in new code; migrate old call sites when touched.

### R2 — Canonical identity/freezing foundation

**Goal:** one deterministic identity system before checkpoints/idempotency/fingerprints depend on it.

Refactor/generalize `_serialize._to_hashable()` into the shared private freezing layer.

Deliver:

- aligned `NonNullHashable` / `Hashable` static and runtime contracts;
- bool/int, int/float/Decimal distinctions;
- datetime/date/struct_time canonical temporal handling via existing timezone utilities;
- PurePath, bytes, UUID, Enum/StrEnum support;
- recursive tuple logical keys;
- tagged mapping/list/tuple/set/frozenset/dataclass freezing;
- cycle detection;
- deterministic heterogeneous mapping-key sorting;
- stable callable fingerprint helper using AST/config/version rules;
- canonical UTF-8 JSON encoding v1;
- fixed domain-separated BLAKE2b-128 durable digest helper;
- `Context(identity_encoder="auto")` backend contract may be typed here but backend resolution can
  land with R3.

`repr_cache` reuses the same freezing primitives but may bypass caching on unsupported values;
durable consumers raise.

**Exit:** golden canonical bytes/digests, cross-process deterministic fixtures, and no use of Python's
randomized `hash()` for durable identity.

### R3 — Immutable Context and Resource definitions

**Goal:** establish the public environment model before Pipeline executions own live state.

Replace today's mutable execution-oriented `Context` with the target immutable definition:

- immutable `inputs`/configuration;
- Context-local module definitions/shadowing;
- `Resource` definitions and `Resource.from_factory()`;
- owned vs `Resource.from_external(...)` lifecycle contract;
- eager/lazy validation rules;
- declared dependency bindings and aliases;
- optional first-class `state_store` capability;
- identity-encoder selection;
- `with_module()` / `with_resource()` derivation;
- no catch-all ignored kwargs.

Do **not** open resources in `Context`. Opening/resolution belongs to R4 private executions.

P8's global built-in/entry-point registry remains the default. Context-local module definitions form
an execution-time overlay; they do not require replacing entry-point discovery.

### R4 — Public Pipeline and private SyncExecution/AsyncExecution

**Goal:** discharge R2 and create the architecture every later runtime feature attaches to.

Deliver:

- public immutable `Pipeline[T]` definition/DAG;
- private `_execution/` package;
- fresh `SyncExecution` from `iter(flow)`;
- fresh `AsyncExecution` from `aiter(flow)`;
- native-wins module resolution over P8 definitions;
- one execution-local bridge/portal where adaptation is needed;
- source normalization at one boundary;
- immutable fluent chaining;
- `with_execution(...)` for executor/concurrency/order settings;
- no executing `collect()`/`first()` terminals;
- `take()` remains a transform;
- execution-local resource resolution/open/rollback/cleanup from R3;
- remove `SyncPipe`/`AsyncPipe`/Collection classes from the target public surface;
- migrate P10 executor/bounded-stream mechanics out of `collections.py` rather than reimplementing
  them.

**R2 exit condition:** omitted configuration is distinct from explicit `None`; a Pipeline definition
and the options actually executed have one source of truth.

### R5 — FeedResult, Metadata, and private per-item provenance

**Goal:** create the internal value envelope required by state, idempotency, generation, and
cross-branch semantics without exposing wrapper objects to ordinary parsers.

Deliver:

- immutable `FeedResult[ItemsT]`;
- typed mapping/attribute `Metadata`;
- generic `FeedState[T]` shell;
- private `_FeedItem[T]` carrying value/item_key/generation/observation;
- automatic provenance propagation through ordinary 1→1 transforms;
- explicit derive/combine handling for 1→N/N→1/N→N;
- source-node namespace in root identity;
- node semantic fingerprints using R2;
- custom-node `identity="preserve"|"derive"|"combine"` only where inference is ambiguous;
- node `version=` override plumbing;
- declared resource bindings included in semantic fingerprints by resolved definition, not Context
  lookup name.

Normal parser APIs still receive values and their prepared arguments, not `_FeedItem`.

### R6 — StateStore, checkpoint, CAS, and idempotency

**Goal:** add durability only after canonical identity and provenance exist.

Deliver public semantic types/protocols:

- phantom-generic `StateKey[T]`;
- generic `FeedState[T]` / `StateRecord[T]`;
- sync `StateStore` and async `AsyncStateStore` protocols with identical method names;
- opaque `StateVersion`;
- private execution-local store adapters;
- CAS-only save/delete (`MISSING` means create-only expectation);
- `CheckpointConflictError` with expected/actual versions;
- generic `.checkpoint()` identity/durability boundary;
- compile-time nearest-owner resolution and multi-frontier rejection;
- owner-level keys (`item_key=None`, therefore `generation=None`);
- recovery checkpoint deletion on successful owner completion;
- durable intrinsic source/poll state retained after success;
- backend-owned physical key/state serialization;
- standardized configured-instance capability visibility through `StateStoreCapabilities`,
  `StateStoreCapabilitiesLike`, `StateSerializationId`, and `StateSerializationLike`;
- coarse `persistent` / `portable` / `serialization` metadata, not an exhaustive supported-type list;
- concrete `validate_state(state) -> None` preflight with `StateSerializationError` on failure;
- `save()` repeats authoritative serialization validation and remains non-mutating on codec failure;
- no generic leases.

Third-party serialization IDs use the standardized `<provider>:<name>` namespace. Capability values
describe the configured store instance, so the same backend may report different persistence or
portability depending on its actual configuration/codec.

Central execution also derives idempotency keys from
`(node_id, fingerprint, item_key, generation, iteration)` and injects them into side-effecting nodes
that declare support.

### R7 — Execution-owned pub/sub and split

**Goal:** replace hidden global hub lifecycle with the finalized object-first fan-out contract.

Deliver:

- `Publisher[T]`, `Subscription[T]`, `Channel[T]` protocols;
- `Pipeline.subscribe(name)` local declaration;
- `flow.publish(subscription_or_publisher, isolate=True)`;
- external `Subscription` accepted as `Pipeline(source=...)`;
- execution-owned local branches and cleanup;
- multiple same-name local subscriptions distinguished by object identity;
- multiple publishers complete a subscription only after all attached publishers finish;
- per-subscription order guarantees;
- buffer default `0`, overflow `block`, optional drop-oldest where permitted;
- `on_receive=` semantics in sync and async together;
- `split()` upstream-once, active-branches-only, bounded, never lossy;
- no cleanup dependency on draining branch output.

The existing `send`/`receive` modules may remain as low-level compatibility modules while the target
Pipeline API is object-first.

### R8 — Single-Pipeline batch execution

**Goal:** add batching without a parallel BatchPipe hierarchy.

Deliver:

```python
Pipeline(source=source, batch=False)
Pipeline(source=source, batch=True, batch_size=...)
```

with graph/capability-aware backend negotiation:

```text
native safe representation
→ Arrow
→ Polars
→ Pandas
→ Python list
```

Forced unavailable backend raises. `batch_size` is invalid when `batch=False`. Batches are ordinary
logical values, so `.map(func)` receives the current batch in batch mode.

Refactor Feed-native batching helpers to implement this contract rather than exposing a separate
`BatchPolicy` user model.

### R9 — Loop/agent state

**Goal:** extend the existing `loop` construct rather than add an agent execution engine.

Deliver iterative mode:

- each iteration output becomes next state;
- exactly one embedded result per iterative iteration;
- zero/multiple result → `LoopStateError`;
- `until(state, iteration)` checked before first iteration;
- `max_iterations=None` default;
- explicit false-at-limit → `LoopIterationError`;
- checkpoint payload `LoopState[T](value, iteration)` through R6;
- explicit stable loop `id=`;
- resume counts total iterations across executions;
- Pipeline DAG remains acyclic.

Agent packages then compose Pipeline + loop + Publisher/Subscription + StateStore rather than
creating `AgentGraph`/`AgentNetwork` runtime primitives.

### R10 — Feed-native migration

**Goal:** move the legacy materialization seam down to genuinely blocking operators after the new
execution envelope exists.

Recommended order remains:

```text
truncate
union
filter
uniq
tail
count
sum
timeout
write
remaining source/composer modules
```

Pub/sub/split use R7 rather than separate ports. Batching uses R8. `sort`/`reverse` may remain eager
where their semantics require whole-input knowledge.

### R11 — adapters: CLI, orchestration, providers, MCP

Only after the core contracts above are stable:

- CLI plugins expose native Click command/group objects;
- CLI assembles immutable `Context`, never a public execution object;
- orchestration uses `PipelineRunRequest(pipeline=PipelineRef(...))`;
- REST/monitoring persist source state through R6 rather than SourceCheckpoint/CheckpointStore;
- provider/MCP sessions are declared `Resource`s resolved once per execution;
- provider side effects consume centrally derived idempotency keys;
- provider resources/actions project into the shared `CapabilityCatalog` rather than a second
  provider catalog;
- provider integrations establish the `OperationHandle` waiter contract before Operations as Code
  needs long-running provider steps;
- RDP projects R5/R6 identity/state rather than owning parallel checkpoint semantics.

### R11A — Operations as Code implementation scaffolding

**Goal:** introduce the minimum external/package scaffolding needed to prove the Operations as Code
architecture without changing Core runtime contracts.

This slice starts only after the relevant R11 service seams exist. It consumes, rather than
redefines, the contracts in `operations-as-code.md`, `provider-integrations.md`, `mcp.md`,
`orchestration.md`, `extensibility.md`, and `cli.md`.

Recommended PR order:

```text
R11A.1  riko-ops package skeleton + repository loader/OperationSpec serialization boundary
R11A.2  validate + OperationPlan aggregation over shared CapabilityCatalog/domain plans
R11A.3  provider operation-asset discovery/acquisition hook + preserved-source fixture
R11A.4  provider target compatibility-facts + export/deploy/inspect hook
R11A.5  apply + verify service using existing Pipeline/capability/provider contracts
R11A.6  source/deployment identity + automation-drift service
R11A.7  common import provenance/lossiness + CompatibilityReport
R11A.8  orchestration adapter for one-run and split plan/apply/verify flows
R11A.9  Click command-provider stub for `riko operation ...`
R11A.10 external operation-pack registration proof
R11A.11 cross-package scenario fixtures
```

Implementation guardrails:

- `nerevu/riko` receives no Operations as Code runtime classes merely for convenience;
- repository/config loaders store credential references, never resolved secrets;
- capability discovery/policy/approval comes from MCP;
- provider-specific import/export/deploy/inspect code lives with provider integrations;
- orchestration carries exact plan identity across durable boundaries and never silently re-plans;
- the CLI stays a thin service adapter;
- operation-pack discovery lands through extensibility after one external-pack proof;
- common migration/compatibility logic does not embed any one RMM's API model.

Two implementation-readiness fixtures close the slice:

1. **SuperOps-like script → Git-backed OperationSpec → GitHub-Actions-like target**: preserve the
   source artifact, normalize known semantics, report at least one lossy/unsupported target fact,
   deploy a derived artifact through a fake provider target, and detect target drift.
2. **Autopilot operation**: aggregate a Microsoft `ChangePlan` into `OperationPlan`, bind human
   approval to the nested plan identity, apply, receive `OperationHandle`, exercise bounded waiting
   (including a durable orchestration handoff), and verify authoritative final state.

Use fakes/golden fixtures first. Live provider implementations are later external-package work and do
not block proving ownership boundaries.

**Exit:** both fixtures compose existing owners without introducing a second capability catalog,
state store, scheduler, provider waiter, Microsoft plan, or runtime execution model.

### R12 — external proof and release gate

Prove the architecture with at least one external extension package before freezing 1.0:

- entry-point module registration through retained P8 seam;
- declared Resource dependency;
- sync-only or async-only implementation adapted in the opposite execution mode;
- external Publisher/Subscription or StateStore implementation;
- generated P9 discoverability includes the extension;
- no core edit required.

Operations as Code scaffolding may provide an additional ecosystem proof, but it does not replace the
Core external-extension proof above; Core 1.0 must remain independently extensible without requiring
`riko-ops`.

Then run the release-readiness wheel, typing, docs, optional-dependency, and public-surface gates.

## 5. Parallelizable work

After R0/R1:

- R2 identity work and most R3 Context/Resource definition work may proceed in parallel if their
  shared `identity_encoder` interface is kept narrow;
- remaining P9 generated discoverability work can proceed independently of R2/R3/R4, provided stubs
  target final `Pipeline` names only when R4 is available;
- P12 event rendering can proceed beside R2/R3, but runtime emission hooks should land with R4+;
- CLI command registry/Click plugin mechanics can proceed independently, but execution commands must
  wait for R4.

After R11 service seams stabilize, provider import/export scaffolding, operation repository/model
work, and CLI command-provider stubs may proceed in parallel only where their interfaces are already
owned. The first cross-provider compatibility and orchestration scenarios wait for those seams.

Do **not** parallelize competing implementations of identity, resource lifecycle, state, pub/sub,
capability discovery/policy, operation planning, provider waiting, or compatibility ownership. Each
has one authoritative implementation.

## 6. First implementation slice

The recommended next coding PR remains **R0**, not an Operations as Code, state-store, or pub/sub PR,
unless the branch has already completed the prerequisite sequence by the time implementation starts.

R0 is deliberately small and low-risk:

1. rename the internal `Pipeline` callable alias to `PipeCallable`;
2. add characterization tests for resolver native selection and source normalization;
3. add the failing desired-behavior test for R2 omitted-vs-`None` semantics;
4. add characterization tests around current pub/sub lifecycle;
5. make no public runtime change yet.

After R0, R1/R2/R3 can proceed without fighting the public `Pipeline` class name or relying on
unrecorded legacy behavior. R11A is **not** permission to jump around those prerequisites; it is the
first Operations as Code slice once the owning lower-level seams exist.

## 7. Completion criteria

The implementation reconciliation is complete when:

1. `Pipeline` is the only target public pipeline definition;
2. each iteration creates independent private execution state;
3. Context contains immutable definitions, never live runtime handles;
4. all durable identity/fingerprints/idempotency/checkpoints share one canonical encoder;
5. StateStore is the one persistence protocol and all writes are CAS-protected;
6. pub/sub/split lifecycle is execution-owned and bounded;
7. batch mode does not create a second pipeline hierarchy;
8. agent iteration reuses `loop` and the existing Pipeline DAG;
9. external packages can use resources/state/pubsub without core changes;
10. Operations as Code scaffolding lives outside Core and composes provider/capability/orchestration
    owners without duplicate contracts;
11. the SuperOps→GitHub Actions and Autopilot fixtures prove import/deploy and
    plan/approval/wait/verify composition respectively;
12. the release docs and generated public surface contain none of the superseded abstractions listed
    in §2.
