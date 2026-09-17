# Finalized architecture implementation sequence

## 1. Purpose

Translate the reconciled target contracts into an implementation dependency graph for the
`features` branch.

This plan owns **implementation sequencing only**. Semantic ownership remains in the individual
gameplans, especially:

- `execution-semantics.md` — Pipeline execution, Context/Resource, identity, state, batching;
- `extensibility.md` — canonical workflow specification and ecosystem contracts;
- `fanout-topology.md` — publish/subscribe/split/routing/fan-in topology;
- `feed-native-streaming.md` — per-module Feed-native migration;
- `connectors.md` — connector/session/credential and concrete adapter contracts;
- `callable-pipes.md` — callable/decorator specialization;
- `provider-integrations.md` — provider semantics, operation waiting, provider-native operation
  import/export/deployment/inspection hooks;
- `mcp.md` — capability discovery/catalog/policy/approval;
- `operations-as-code.md` — `OperationSpec`, `OperationPlan`, Git source-of-truth,
  validate/plan/apply/verify, compatibility, migration, deployment drift;
- `orchestration.md` — external scheduling and durable run boundaries;
- `cli.md` — terminal adapters;
- `release-readiness.md` — public-release gate and pre-1.0 Python API removal policy;
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

**P9A module-name/taxonomy mechanics** are also retained. Generated module identifiers remain a
discovery layer over canonical string IDs. The shipped `Sinks` bucket is historical, not part of the
final taxonomy: remaining installed-environment aggregate and `.pyi` work must target module
`Sources` / `Transforms` plus the separate `Targets` / `Formats` discovery surfaces and must not
encode removed `SyncPipe`/`AsyncPipe`, `write`, `output`, or `Sinks` APIs.

**P10 bounded execution algorithms** are retained conceptually:

- bounded async mapping;
- ordered/unordered delivery;
- worker pools/executors;
- shared concurrency-budget primitives.

Their current home in `collections.py` is temporary. Move reusable mechanics into private execution
modules rather than preserving `collections.py` as architecture.

**Compiler graph index** is a retained foundation. `parse_pipe_def` builds one immutable
`_GraphIndex` (`riko/types/compile.py`) that interprets a pipe's wiring exactly once — wire-level
`edges`/`incoming`/`outgoing` (ports kept verbatim) plus node-level
`order`/`dependencies`/`dependents`/`roots`/`leaves`/`outputs`. It replaces the old `ParsedPipeDef`
`graph`+`wires` fields; R4A's `migrate_v1_to_v2()`/`normalize_workflow()`/`validate` build on it and
R4B's `_ExecutionPlan` reuses its structural facts. The v1-behavior-preserving deltas it still
carries (`_OUTPUT` as a node, verbatim ports, dropped orphans) are resolved at the R4A boundary, not
in the index — see [extensibility § E3.11](extensibility.md#e311-reuse-of-the-shipped-graph-index).
Keep execution concepts (resolved callables, portals, resource values, task groups) off it.

The reuse seam runs *through* the compiler, not around it. Graph parsing/validation/ordering/resolution
is kept and adapted; the legacy generator-construction tail is replaced. Concretely: `topological_sort`
(strict for canonical workflows), `ModuleRegistry`/`PipeResolver`/`PipelineResolver`, the `_GraphIndex`,
and the argument-binding *concepts* in `_get_input_module`/`_gen_pykwargs` all survive into R4B
preparation. What is replaced is `_gen_steps`/`_build_pipeline`/`build_pipeline`, which today resolve,
wire, invoke, and construct a running generator in one pass keyed off "the last topologically-sorted
module." R4B splits that boundary one step later — preparation produces an immutable `_ExecutionPlan`
of prepared nodes (no invocation), and a separate run step executes it against explicit `outputs`
rather than a terminal-module assumption. `convert_dag` and `gen_parented_graph`'s orphan-dropping stay
on the v1 authoring/migration side and do not feed canonical v2 preparation.

### Retain but reshape

**Current module decorators/preparation** remain the parser invocation seam. Extend existing
preparation to inject declared execution-bound `resources`; do not add a second signature-based DI
system.

**Current `_serialize.py` canonicalization/cache work** is the starting point for one shared freezing
system, but its current representation is process-local and unsuitable for durable identity. Refactor
rather than layering a second serializer beside it.

**Current sync/async pub/sub hubs** are useful behavioral fixtures and migration inputs. Their
process/contextvar ownership and hidden sentinel/id bookkeeping are superseded by execution-owned
subscription runtime state and canonical publish edges.

**Current writer/adapter mechanics** behind the `write`/sink-target experiments are useful migration
inputs. Reuse streaming writer, codec, and adapter mechanics where they fit `WriteNode`; retaining
those mechanics does not retain either old public abstraction.

### Remove at the R5C clean-break

Two shipped-but-interim surfaces exist only until the write effect can take their place, then are
removed under the pre-1.0 clean-break policy with no deprecated wrapper, alias, compatibility
enum/category, or legacy loader form:

- the fluent **`sink()`** terminal verb. It shipped alongside the R3 write-session seam to give
  terminal consumption — drain the stream, return a `WriteResult` — before `Pipeline.write()` /
  `WriteNode` existed. It shares `write()`'s session mechanism and carries identical write semantics
  (both default to `replace`); its only difference is terminality. There is no *permanent* public
  `sink()` — terminality is a graph-position/consumption property, not a second verb — so R5C removes
  the interim verb once a `write()` at a graph leaf provides the same terminal consumption. It keeps
  no persisted-workflow compatibility obligation because no serialized `SinkNode` ever existed;
- the shipped Python **`riko.modules.write`** module, removed when `Pipeline.write()` / `WriteNode`
  lands. Released persisted v1 workflows containing `write` are handled only by the bounded v1
  migration boundary in R4A/extensibility.

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
- a *permanent* public `sink()` terminal parallel to `write()` (the interim fluent `sink()` shipped
  with the R3 write-session seam and is removed at the R5C clean-break, see above);
- execution knobs on `with_config()`;
- RDP-owned generic `Checkpoint` or sequence/expansion-path identity;
- duck-typed lifecycle discovery on arbitrary resolved resource values (`open`/`aopen`/`close`/
  `aclose` introspection) as the conceptual resource model;
- a global batch backend preference ladder (`Arrow → Polars → Pandas → list`);
- automatic callable fingerprinting treated as sufficient for durable semantic identity;
- a Core-owned `OperationSpec`/`OperationPlan` or second operation runtime;
- provider-local `CompatibilityReport` or capability catalog;
- orchestration-owned operation source-of-truth/planning semantics.

## 3. Dependency graph

```text
R0   characterization + internal naming
 |
R1   stable minimum error foundations
 |
 +---- R2A canonical value encoding
 |
 +---- R2B semantic identity/version contract
 |
 +---- R3  Context + Resource definitions
              |
              v
R4A  Pipeline definition + canonical Workflow v2 IR
              |
              v
R4B  private executions + lifetime + EventSink transport
              |
              v
R5A  FeedResult / _FeedItem / provenance
       |                         |
       |                         +---------------------> R7 fanout topology
       v
R5B  CacheNode runtime / Mezmoize replay
       |
       v
R5C  WriteNode + ActionNode effect runtime
       |
       v
R6   StateStore / checkpoint / CAS / idempotency
       |                         |
       +------------+------------+
                    |
              +-----+-----+
              |           |
              v           v
             R8          R9
          batching      loop
              |           |
              +-----+-----+
                    |
                    v
R10  final Feed-native legacy-seam cleanup
                    |
                    v
R11  adapters/providers/orchestration
                    |
                    v
R12  external extension + 1.0 gate
```

Feed-native migration is **incremental across this graph**, not deferred wholesale to R10. Ordinary
streaming transforms may migrate once R5A supplies the final value/provenance envelope; streaming
write migrates with R5C; send/receive/split migrate with R7; batch representation optimization lands
with R8. R10 is the final legacy-seam elimination and parity proof.

The two R4 slices deliberately separate definition from execution. R4A freezes the graph language and
normalization boundary before R4B executes it. That is the same definition/IR-before-runtime split
used by mature workflow/compiler systems and keeps authoring sugar, migration, and graph validation
out of execution code.

R7 depends on R5A because branch delivery must carry the final `_FeedItem` identity/provenance
envelope. It does **not** depend on cache, effects, or durable state.

The graph is intentionally not identical to P8–P14 numbering. The reconciled architecture introduced
foundational identity/resource/state work that cuts across those phases.

### Phase closure rule

Every R-phase closes against three questions:

- **ADD** — what canonical capability or contract now exists?
- **MIGRATE** — which existing consumers, representations, or mechanics now use it?
- **DELETE** — which superseded runtime, surface, shim, or representation is now gone?

A phase is not complete while both the canonical path and its superseded implementation remain,
unless the older form is an explicitly bounded compatibility boundary with a named owner and removal
point.

Compatibility must terminate at an ingress boundary; it must not preserve a parallel runtime path.

When a phase genuinely has nothing to migrate or delete, its exit criteria say `none` explicitly
rather than omitting the category.

## 4. PR sequence

### R0 — Characterization and internal naming

**Goal:** create a safe seam before public runtime replacement.

Changes:

- rename the internal parser callable alias `Pipeline` → `PipeCallable` everywhere;
- characterize the current resolver native-interface behavior;
- characterize source normalization (`Mapping`, iterable, `str`/`bytes`, generator, Feed,
  Awaitable);
- pin the current one-shot execution/lifecycle behavior that should move into private executions;
- add failing R2A regression coverage for omitted-vs-explicit-`None` reconfiguration;
- characterize current sync/async pub/sub semantics before deleting hub internals.

Keep P8 behavior unchanged except for type-name cleanup.

**Exit:**

- **ADD:** characterization tests pin the resolver, source-normalization, one-shot lifecycle, and
  pub/sub seams that later phases replace.
- **MIGRATE:** the internal parser callable alias is `PipeCallable`, leaving `Pipeline` available for
  the public definition type.
- **DELETE:** none; R0 intentionally makes no released runtime deletion.

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

**Exit:**

- **ADD:** the stable Riko-owned error families required by later R-phases exist.
- **MIGRATE:** new foundations use those errors, and legacy call sites migrate when touched rather
  than introducing new builtin-exception contracts.
- **DELETE:** none; untouched legacy call sites are intentionally not bulk-migrated in R1.

### R2A — Canonical value encoding

**Goal:** one deterministic *value* encoder before checkpoints/idempotency/fingerprints depend on it.

R2 is split because its two halves have very different confidence levels. R2A is mechanical,
fully testable, and safe to make load-bearing. R2B is inherently incomplete and must not be.

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
- canonical UTF-8 JSON encoding v1;
- fixed domain-separated BLAKE2b-128 durable digest helper;
- `Context(identity_encoder="auto")` backend contract may be typed here but backend resolution can
  land with R3.

`repr_cache` reuses the same freezing primitives but may bypass caching on unsupported values;
durable consumers raise.

**Exit:**

- **ADD:** golden canonical bytes/digests and cross-process deterministic fixtures prove the shared
  value encoder.
- **MIGRATE:** `repr_cache` and every durable identity consumer use the shared freezing primitives.
- **DELETE:** Python's randomized `hash()` and parallel ad hoc encoders are absent from durable
  identity paths. R5A/R5B/R6 may depend on R2A completely.

### R2B — Semantic identity and version contract

**Goal:** node/resource semantic identity, deliberately weaker than R2A and documented as such.

Deliver:

- explicit node/resource `id`;
- explicit `version=` as the **authoritative** durable semantic identity;
- stable definition metadata participating in identity;
- best-effort automatic callable fingerprint helper using AST/config/distribution rules.

The scope reduction is intentional. Automatic introspection of arbitrary Python callables — AST plus
closure plus globals plus decorators plus instance config plus distribution — can never be complete:
a changed third-party dependency called from the body, a runtime-derived global, a C extension
callable, generated code, and monkeypatching all defeat it. Making that the durability foundation
turns Riko into a Python-semantic hashing project before it finishes being an ETL engine.

So the priority is:

```text
automatic fingerprint = convenience/best-effort identity
explicit version=      = authoritative durable semantic identity
```

Automatic fingerprints stay useful for local caching, debugging, obvious structural-change
detection, and semantic fingerprints. Durable checkpoints and idempotent side effects should use an
explicit version when they must survive software/dependency changes.

`execution-semantics.md` owns the semantics; this split governs sequencing and scope only.

**Exit:**

- **ADD:** explicit node/resource identity and `version=` exist, with automatic fingerprinting kept
  best-effort.
- **MIGRATE:** node/resource semantic identity construction follows the version-first contract.
- **DELETE:** none; R2B removes no runtime surface, but no durable contract may depend on automatic
  callable introspection being complete.

### R3 — Immutable Context and Resource definitions

**Goal:** establish the public environment/resource-definition model before Pipeline definitions bind
resources and private executions acquire them.

Replace today's mutable execution-oriented `Context` with the target immutable definition and land
the type/normalization boundary, not the execution lifecycle:

- immutable `inputs`/configuration;
- Context-local module definitions and child-Context shadowing;
- public generic `Resource[T]` umbrella with unconstrained resolved value type `T`;
- public `ReusableResource[T]` category for wrappers safe in reusable Context definitions;
- private concrete external/factory/one-shot-owned resource variants;
- canonical `ResourceDefinition[T] = ReusableResource[T] | ResourceFactory[T]`;
- `Resource.from_external(value)` for caller-owned reusable resource values;
- explicit `Resource.from_factory(factory, *args, **kwargs)` for arbitrary constructors/provider
  callables, including sync/async callables and optional explicit cleanup;
- direct implicit ResourceFactory recognition only for unambiguous lifecycle-definition forms
  (sync/async generator or context-manager definitions), never arbitrary `callable(x)` or bare
  classes;
- bind `from_factory` args first, then validate the remaining invocation signature as exactly `()`,
  `(ctx)`, or `(ctx, resources)` with the reserved semantic names;
- return annotations remain optional and advisory for typing only;
- one-shot `Resource(value, cleanup=...)` remains a low-level compatibility/execution-local form
  outside `ResourceDefinition`, so reusable `Context.with_resource()` cannot accept it;
- eager validation of the complete declared resource graph, including symbolic dependency aliases,
  late binding through effective Context shadowing, missing dependencies, duplicate declarations,
  signatures, and cycles regardless of `lazy=True`;
- resource identity metadata includes stable factory/bound-argument/cleanup/dependency configuration,
  while live external resource values stay opaque and explicit `version=` remains authoritative;
- optional first-class `state_store` capability using the same reusable resource-definition contract;
- identity-encoder selection;
- `with_module()` / `with_resource()` immutable derivation;
- no catch-all ignored kwargs.

R3 classifies and normalizes what can be known from the definition. It must **not** inspect a
not-yet-created factory result to guess its runtime lifecycle. Context construction also does not open,
await, enter, close, or serialize execution-created resource values. Runtime factory-result
validation, single-flight lazy acquisition, sync/async adaptation, rollback, and teardown belong to
R4B.

Caller-owned `Resource.from_external(...)` values are the explicit exception to "no live values in a
Context": the wrapper may hold the supplied process-local resource value, but Riko never owns/closes
it and no durable serialization guarantee follows from doing so.

P8's global built-in/entry-point registry remains the default. Context-local module definitions form
an execution-time overlay; they do not require replacing entry-point discovery.

#### R3-adjacent — write-session seam

Landed beside R3, not a separate R-phase. Two foundational corrections that let later phases inherit
the right seams without pulling their runtimes forward:

- the async **operator** wrapper now returns an `AsyncIterator` directly rather than
  `Awaitable[AsyncIterator]`; async processors/splitters keep their awaitable contract for now;
- the fluent sync `write()`/`sink()` implementation is moved off the hidden `send`/`on_receive`
  pub/sub channel onto a private write-session mechanism (`prepare_write` → a `WriteSession`
  lifecycle) shared by both verbs.

This establishes the seam only. R4B moves ownership of the write-session lifecycle into the private
execution exit stack, and R5C makes `WriteNode` invoke the same preparation/session — reuse, not
replacement. Because `write()` no longer rides a hidden `send` channel, R7 can remove send/receive
without a write-specific compatibility path.

The fluent async `write()`/`sink()` surface also landed here (an async write session drives the
passthrough/terminal verbs), earlier than the sequence originally deferred it. R4B still owns the
final form: it re-hosts that same session lifetime on the execution `AsyncExitStack` rather than on
the current one-shot pipe host. The session contract does not change — only its owner.

**Exit:**

- **ADD:** immutable Context/Resource definitions and the private sync/async write-session seam exist.
- **MIGRATE:** reusable resource declarations use the immutable definition model, while fluent
  `write()`/`sink()` use `WriteSession` rather than hidden pub/sub callbacks.
- **DELETE:** mutable/catch-all Context definition behavior and the write path's hidden
  `send`/`on_receive` dependency are absent; the explicitly bounded one-shot Resource form remains.

### R4A — Public Pipeline definition and canonical Workflow v2 IR

**Goal:** freeze one complete definition/serialization language before the new execution runtime
consumes it.

Deliver the public immutable `Pipeline[T]` definition/DAG plus the canonical Workflow v2 model.
R4A owns definition structure, not runtime implementation of every node family.

Canonical node families:

```text
ModuleNode
ReadNode
WriteNode
CacheNode
ActionNode
SubscribeNode
```

Canonical edge families:

```text
StreamEdge
PublishEdge
```

`publish` is a relationship/delivery edge, not a pass-through `PublishNode`. `split`, `branch`,
`route`, `union`, `merge`, `join`, and `loop` remain registered module behavior represented by
`ModuleNode`; `loop` does not gain a separate graph-node family.

`WriteNode` (and `ActionNode`) carry semantic **intent only** — target, format, `mode`, and a single
unified `keys` list. The caller supplies just one `keys` because a target's `match_keyed_modes` and
`idempotent_modes` are disjoint, so the `(target, mode)` pair alone fixes whether keys mean
record-match identity or idempotency/deduplication identity — there is no separate `idempotency_key`.
They do **not** carry execution details
(`stream`/`buffered`/`incremental`, chunk
size, file handle, live resource, `WriteSession`); delivery granularity stays negotiated at execution
time. R4A serializes this intent and must **not** duplicate the write-session mechanism established
alongside R3. There is no `SinkNode` — terminality is a consumption behavior, not a node family.

Canonical port grammar:

```text
in / out             default port
in:N / out:N         positional port
out:<name>            semantic named output port
```

Legacy stable mapping begins with:

```text
_INPUT   -> in
_OTHER   -> in:1
_OTHER2  -> in:2
_OUTPUT  -> out
_OUTPUT2 -> out:1
_OUTPUT3 -> out:2
```

One source port may fan out to many stream edges. A target stream port has at most one incoming
stream edge; fan-in is represented by distinct `in`, `in:1`, `in:2`, ... ports. `split` uses
positional output ports; `branch`/`route` use semantic named ports where branch identity is semantic.
The registered node/module contract declares valid ports; edges only connect them.

Workflow v2 normalization is one ingress boundary:

```text
legacy v1 -> migrate_v1_to_v2()
authoring v2 sugar
        -> normalize_workflow()
        -> strict canonical WorkflowSpec v2
        -> validate
        -> compile / serialize / execute
```

Deliver:

- top-level `nodes`/`edges` graph envelope;
- full `source`/`target` edge endpoints with explicit node/port; reject `src`/`tgt` and `from`/`to`;
- top-level named `outputs`, with omitted output sugar only for one unambiguous leaf;
- top-level typed `inputs` declarations normalized to full JSON Schema;
- resource references and declared resource slots;
- configured immutable serializable `Target` and `Format` definitions/references;
- `TargetRegistry` contract and sync/async target capability protocols;
- canonical read/write/action/cache/subscription/checkpoint/loop structural fields even when runtime
  execution lands in later phases;
- deterministic serialization;
- during 0.x, released v1 input accepted only at the migration boundary, warning on migration and
  normalizing immediately to v2; v2 emitted only;
- released v1 `write` module nodes migrate to canonical `WriteNode` plus Target/Format structure;
  the interim fluent `sink()` never had a serialized node form, so there is no legacy `sink` grammar
  to accept;
- normal runtime loading becomes v2-only at 1.0; an offline pure `migrate_v1_to_v2()` utility may
  remain;
- strict closed canonical schema: unknown structural fields, ports, references, edge types, resource
  slots, duplicate ids, and unsupported versions fail before execution.

Authoring node ids are optional; every canonical node has an id. Omitted ids normalize to a
deterministic readable `<name>-<occurrence>` form. Generated ids are stable for that normalized
definition only; authors provide an explicit `id` when logical identity must survive structural
revisions.

`id` is graph-node identity; `name` is the stable registered implementation identity; `label` is
optional human text.

R4A also locks `Targets` as endpoint/provider identities and `Formats` as serialization formats.
Concrete provider/storage implementations remain R11 adapters. A canonical workflow can therefore
validate `Target`/`Format` structure without importing every optional client library.

Structural validation answers "is this a valid WorkflowSpec v2?" Runtime preparation later answers
"can this graph execute with the installed/available contracts and resources?" A valid v2 document
may therefore round-trip a node whose runtime capability has not landed yet, while execution fails
with a clear unsupported-capability error.

#### R4A slice ordering

R4A is the largest single slice in this sequence and lands as ordered PRs, not one sitting. The
contract for each slice is `extensibility.md` §E3; this ordering governs sequencing only.

```text
R4A.0  vocabulary split
R4A.1  canonical v2 model
R4A.2  normalize_workflow()
R4A.3  validate()
R4A.4  migrate_v1_to_v2()
R4A.5  deterministic serialization + acceptance
```

- **R4A.0 — vocabulary split.** Resolve the `Targets`/`Formats` collision (E3.7): the shipped export
  `Targets` (serialization formats) becomes `Formats`, and `Targets` is redefined as endpoint/provider
  identities (`FILE`/`HTTP`/`S3`/`POSTGRES`/`AIRTABLE`/`INTUNE`). Introduce immutable serializable
  `Target`/`Format` defs+refs, a `TargetRegistry` parallel to `ModuleRegistry`, and sync/async target
  capability protocols. Files: `collections.py`, `targets.py`, `_api_surface.py`.
- **R4A.1 — canonical v2 model.** The closed discriminated node union and edge families (E3.3/E3.4),
  full `{node, port}` endpoints and port grammar, the `nodes`/`edges`/`outputs`/`inputs` envelope
  (E3.2/E3.6), inputs-as-JSON-Schema, and the public immutable `Pipeline[T]`. Structural only, no
  runtime. Files: new `riko/workflow/` package, `riko/types/_pipeline.py`.
- **R4A.2 — `normalize_workflow()`.** Authoring sugar → strict canonical (E3.1): omitted
  outputs→`outputs.default`, inline `Target`/`Format`→explicit, singular `resource`→`resources`,
  omitted ids→`<name>-<occurrence>`, port aliases, inferred formats made explicit.
  `normalize(normalize(x))` is stable. File: `riko/workflow/normalize.py`.
- **R4A.3 — `validate()`.** Closed-schema rejection (E3.9): unknown fields/ports/families, duplicate
  ids, missing refs, >1 StreamEdge per stream port, fan-in positions, undeclared resource slots,
  unresolved `Target`/`Resource`/`Input` refs, contract-aware conf/params validation. Structural
  validity is not runtime capability. File: `riko/workflow/validate.py`.
- **R4A.4 — `migrate_v1_to_v2()`.** Pure v1→v2 (E3.1/E3.11): `_INPUT`/`_OUTPUT`/`_OTHERn`→canonical
  ports, v1 `write` module→`WriteNode`+Target/Format, terminal `_OUTPUT` passthrough→`outputs.default`,
  orphan handling deferred to validation rather than silent erasure. Warn during 0.x, emit v2 only;
  the interim fluent `sink()` had no serialized node form, so there is no legacy `sink` grammar. File:
  `riko/workflow/migrate.py`.
- **R4A.5 — deterministic serialization + acceptance.** Byte-stable canonical serialization, full
  round-trip of every supported topology, golden fixtures, `normalize ∘ migrate` never emitting
  v1-only structure, and CLI (`compile-pipe`/`convert-dag`) emitting v2 only (E3.10). Files:
  `riko/cli/`, `tests/` golden fixtures.

R4A.5 is the only slice gated on R2A (the canonical value encoder): the structural slices R4A.0–R4A.4
proceed without it, and the byte-stable serialization/golden-fixture work waits on it. R4A.0 is both
the true unblocked head and the highest-risk decision — the `Targets`→`Formats` rename touches the
STABLE `riko` surface (`_api_surface.py`, `tests/public/test_imports.py`) — so it is front-loaded to
force that decision early.

**Exit:**

- **ADD:** the public immutable `Pipeline[T]` and strict canonical Workflow v2 definition,
  validation, and serialization path exist.
- **MIGRATE:** compiler/CLI output and released v1 ingress normalize once into canonical v2, including
  v1 `write` → `WriteNode` migration.
- **DELETE:** v1 is absent as an emitted or internal/runtime representation. During 0.x, only the
  bounded v1→v2 ingress migration remains; the offline pure migration utility may survive 1.0.

### R4B — Private SyncExecution/AsyncExecution and lifetime

**Goal:** execute the frozen R4A definition model with one common lifetime boundary.

Deliver:

- private `_execution/` package;
- fresh `SyncExecution` from `iter(flow)`;
- fresh `AsyncExecution` from `aiter(flow)`;
- native-wins module resolution over P8 definitions;
- execution-owned task group;
- execution-owned exit stack;
- execution-owned worker/portal bridge;
- one execution-local bridge/portal where adaptation is needed;
- source normalization at one boundary;
- immutable fluent chaining;
- `with_execution(...)` for executor/concurrency/order settings plus the execution-level
  shutdown/cleanup budget;
- minimal execution-owned `EventSink` transport and no-op default;
- execution-local resource acquisition/entry/rollback/exit from R3;
- runtime factory-result handling: await awaitables once, honor explicit cleanup first, otherwise
  prefer context-manager lifecycle over close/aclose capability and native execution mode over
  bridging;
- lazy-resource single-flight acquisition and dependency-first/dependent-first lifetime ordering;
- transactional partial-acquisition unwind and comprehensive cleanup-error grouping;
- bounded cancellation-shielded resource teardown;
- external-resource lifecycle/concurrency proof;
- remove `SyncPipe`/`AsyncPipe`/Collection classes rather than retain deprecated wrappers;
- migrate P10 executor/bounded-stream mechanics out of `collections.py` rather than reimplementing
  them.

The minimal `EventSink` is infrastructure, not the full observability layer. R4B owns dispatch and
lifetime only. Later phases define the semantic events/results they produce; optional OpenTelemetry
and other consumers remain ecosystem/observability work.

#### R4B lifetime invariants

1. every execution-spawned task belongs to exactly one execution-owned task group; detached
   `asyncio.create_task()` exists only in explicitly characterized transitional code scheduled for
   removal;
2. every context-managed component is entered on the execution exit stack, and rollback is that
   stack unwinding rather than a separate teardown path;
3. lifecycle composition is not execution-mode adaptation: potentially blocking sync entry/exit is
   adapted to a worker before it reaches an async stack;
4. cross-mode adaptation happens only at an execution boundary chosen during preparation. Parser,
   module, factory, and extension code never creates event loops, portals, executors, worker
   threads, or task groups;
5. resource teardown is shielded from ambient cancellation only within the shared execution shutdown
   budget; cancellation remains the primary outcome and no per-resource timeout exists initially;
6. event delivery is execution-owned and must not create a parallel callback/lifecycle framework.

#### R4B external-resource proof

Do not wait until R12 to discover that the execution lifecycle cannot hold a real client. R4B exit
tests include at least one genuinely external async resource and one genuinely external sync
resource, each proven under **both** sync and async Pipeline execution.

Covered cases: eager open, lazy open, mid-execution failure rollback, early consumer abandonment,
cancellation, and cleanup-error grouping. R12 proves the **external package API**; R4B proves the
**runtime architecture**.

**Exit:**

- **ADD:** private sync/async executions own task groups, exit stacks, adaptation, resources, events,
  and shutdown.
- **MIGRATE:** P10 bounded/executor mechanics, R3 resource acquisition, and the write-session
  lifecycle run under the common execution lifetime.
- **DELETE:** `SyncPipe`/`AsyncPipe`/Collection runtime classes and superseded one-shot pipe lifecycle
  hosts are absent rather than wrapped; no parallel task-group/exit-stack/portal runtime remains.

### R5A — FeedResult, Metadata, and private per-item provenance

**Goal:** create the internal value envelope required by state, idempotency, generation, cache replay,
and cross-branch semantics without exposing wrapper objects to ordinary parsers.

Deliver:

- immutable `FeedResult[ItemsT]`;
- typed mapping/attribute `Metadata`;
- generic `FeedState[T]` shell;
- private `_FeedItem[T]` carrying value/item_key/generation/observation;
- automatic provenance propagation through ordinary 1→1 transforms;
- explicit derive/combine handling for 1→N/N→1/N→N;
- source-node namespace in root identity;
- node semantic fingerprints using R2A encoding and the R2B best-effort/version contract;
- custom-node `identity="preserve"|"derive"|"combine"` only where inference is ambiguous;
- node `version=` override plumbing;
- declared resource bindings included in semantic fingerprints by resolved definition, not Context
  lookup name.

Normal parser APIs still receive values and their prepared arguments, not `_FeedItem`.

Once R5A lands, ordinary Feed-native transforms whose semantics depend only on the final execution
envelope may migrate immediately rather than waiting for R10.

**Exit:**

- **ADD:** `FeedResult`, `Metadata`, and the private `_FeedItem` provenance/identity envelope exist.
- **MIGRATE:** ordinary streaming transforms that are otherwise ready use the final Feed-native
  envelope and resolved resource definitions participate in semantic fingerprints.
- **DELETE:** none at the public surface; migrated modules retain no second per-item
  provenance/identity carrier beside `_FeedItem`.

### R5B — CacheNode runtime / Mezmoize replay

**Goal:** implement explicit replay/materialization semantics without inventing another cache backend
hierarchy inside Riko.

`Pipeline.cache()` compiles to `CacheNode`. Runtime cache behavior uses a private Riko-to-Mezmoize
shim and Mezmoize/CacheLib backends rather than Riko-owned store classes.

Deliver the locked cache semantics:

- cache semantic identity belongs to the graph/Pipeline definition; mutable cache contents belong to
  the cache service;
- plain `.cache()` uses a deterministic bounded process-local Mezmoize `SimpleCache` resource;
- explicit persistent/shared cache behavior is supplied through the normal CacheNode `cache`
  Resource slot;
- no semantic TTL by default; `ttl: datetime.timedelta | None`, canonicalized as exact integer
  milliseconds when present;
- default process-local capacity `DEFAULT_CACHE_SIZE = ByteSize(mebibytes=64)`;
- private chunk size `_CACHE_CHUNK_SIZE = ByteSize(kibibytes=256)`;
- chunk + manifest storage; publish the manifest only after all chunks exist;
- stream items downstream while staging, but commit a fill only after successful complete traversal;
- error, cancellation, or early consumer exit discards the incomplete fill;
- missing chunk means miss plus stale cleanup;
- concurrent duplicate fills are allowed and isolated by generation; no single-flight requirement;
- `cached.invalidate()` rotates generation so old contents become unreachable without eager deletion;
- backend failure emits an `EventSink` diagnostic and bypasses cache for the rest of the current
  execution; the next execution retries the backend;
- upstream execution failures remain execution failures, never cache bypasses.

Cache capacity is Resource/backend policy, not a `.cache(limit=...)` node option. `ByteSize` is the
public size-value type; canonical size representation is bytes.

**Exit:**

- **ADD:** `CacheNode` has the finalized Mezmoize-backed chunk/manifest replay runtime.
- **MIGRATE:** cache identity, replay, invalidation, and backend access use the canonical graph/R2A
  identity plus the private Mezmoize shim.
- **DELETE:** superseded cache representations that bypass canonical identity or manifest/generation
  publication are gone; no parallel Riko-owned cache-store hierarchy remains.

### R5C — Provider-neutral write/action effects

**Goal:** establish one side-effect execution model before durable idempotency is layered on in R6.

Deliver:

- `WriteNode` runtime over the R4A Target/Format/registry contracts;
- `ActionNode` runtime over registered provider-neutral action contracts;
- `WriteResult` and `ActionResult` event/result values;
- original input records pass downstream unchanged after successful write/action processing;
- successful writes aggregate completion per write node;
- results are emitted out-of-band through the R4B `EventSink`;
- sync/async target/action implementations adapt through R4B rather than creating local bridges;
- failure propagation and cancellation obey the common execution contract;
- remove the shipped `riko.modules.write` Python module/discovery entry when `Pipeline.write()` /
  `WriteNode` lands; do not keep a deprecated wrapper;
- preserve only the bounded persisted-v1 `write` migration owned by R4A/extensibility.

`write()` is an effect operation, not a public module and not a terminal by definition. Its graph
position determines whether the user continues chaining. There is no *permanent* public `sink()`
counterpart in the target API; the interim fluent `sink()` that shipped with the R3 write-session
seam is removed here once `write()` at a graph leaf provides the same terminal consumption.

`read()` owns acquisition plus interpretation/parsing through Target + Format. `write()` owns
reconciliation/mutation. Provider commands that do not naturally mean data write are actions.
Concrete FILE/HTTP/S3/Postgres/Airtable/Intune/etc. adapters remain R11.

**Exit:**

- **ADD:** `WriteNode`/`ActionNode` execute through the common effect runtime and report
  `WriteResult`/`ActionResult` through `EventSink`.
- **MIGRATE:** internal write execution uses the canonical `WriteNode` path and execution-owned
  write-session/lifetime machinery.
- **DELETE:** `riko.modules.write`, its discovery entry, and the interim fluent `sink()` surface are
  absent. The only legacy `write` behavior retained is bounded persisted-v1 migration at the R4A
  Workflow ingress boundary.

### R6 — StateStore, checkpoint, CAS, and idempotency

**Goal:** add durability only after canonical identity, provenance, replay, and the effect runtime
exist.

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
- standardized configured-instance capability visibility;
- concrete `validate_state(state) -> None` preflight with `StateSerializationError` on failure;
- no generic leases.

Central execution derives idempotency keys from
`(node_id, fingerprint, item_key, generation, iteration)` and injects them into R5C side-effecting
nodes that declare support.

Checkpoint declarations already exist structurally in R4A. R6 adds owner resolution, restore,
persistence, CAS, cleanup, and runtime validation.

**Exit:**

- **ADD:** `StateStore`/`AsyncStateStore`, checkpoint ownership, CAS, and central idempotency key
  derivation form one durability contract.
- **MIGRATE:** recovery checkpoints, intrinsic source/poll state, and R5C idempotent effects use the
  shared state/identity contract.
- **DELETE:** none if no parallel durability prototype exists; no `SourceCheckpoint`,
  `CheckpointStore`, generic lease layer, or non-CAS persistence path may survive beside StateStore.

### R7 — Execution-owned publish/subscribe and split

**Goal:** implement the R4A `SubscribeNode`/`PublishEdge` topology and replace hidden global hub
lifecycle.

R7 depends on R5A so fanout transports the final `_FeedItem` provenance envelope. It does not depend
on cache/effects/state.

Deliver:

- `Publisher[T]`, `Subscription[T]`, `Channel[T]` runtime protocols;
- `Pipeline.subscribe(name, ..., func=...)` local declaration;
- `flow.publish(subscription_or_publisher, isolate=True)`;
- external `Subscription` accepted as `Pipeline(source=...)`;
- execution-owned local branches and cleanup, with every subscriber/branch/merge task created under
  R4B's task group;
- multiple same-name local subscriptions distinguished by object identity;
- multiple publishers complete a subscription only after all attached publishers finish, derived
  structurally from incoming `PublishEdge`s and owned sender endpoints;
- no PENDING/DONE/sender-id markers in the data stream;
- per-subscription order guarantees;
- buffer default `0`, overflow `block`, optional drop-oldest where permitted;
- receive-time `func=` semantics in sync and async together: run at subscription
  delivery/materialization time, discard the return value, and preserve the original item;
- `split()` upstream-once, active-branches-only, bounded, never lossy;
- branch/route port behavior from the R4A contract;
- no cleanup dependency on draining branch output;
- remove legacy `send` / `receive` Python modules when the object-first surface lands rather than
  retain low-level compatibility modules.

`func` is intentionally retained rather than renamed to `on_receive`: its materialization timing is
part of subscription semantics and differs from ordinary downstream UDF evaluation timing.

Feed-native send/receive/split implementation migration belongs in this phase rather than being
deferred to R10; only the useful mechanics survive behind the new API.

**Exit:**

- **ADD:** publish/subscribe/split use execution-owned topology, buffering, task ownership, and
  lifetime.
- **MIGRATE:** useful send/receive/split mechanics are Feed-native behind `PublishEdge`,
  `SubscribeNode`, and the object-first API.
- **DELETE:** legacy `send`/`receive` modules, global/context-local hub lifecycle, and
  PENDING/DONE/sender-id stream bookkeeping are absent.

### R8 — Single-Pipeline batch execution

**Goal:** add batching without a parallel BatchPipe hierarchy.

Deliver:

```python
Pipeline(source=source, batch=False)
Pipeline(source=source, batch=True, batch_size=...)
```

with capability/conversion-cost backend negotiation rather than a global library ranking:

```text
candidates = upstream representations ∩ representations the node accepts

1. current representation
2. zero-copy/interchange-backed candidate
3. cheapest supported conversion
4. Python objects (universal fallback)
```

Equal-cost ties resolve through a documented stable order so identical graphs negotiate identically
across processes. Forced unavailable backend raises. `batch_size` is invalid when `batch=False`.
Batches are ordinary logical values, so `.map(func)` receives the current batch in batch mode.

Batch-aware Feed-native representation optimization lands here; no separate R10 rewrite is required.

**Exit:**

- **ADD:** batch mode runs on ordinary `Pipeline` with deterministic capability/conversion-cost
  representation negotiation.
- **MIGRATE:** batch-aware modules use the same Pipeline execution path and negotiated Feed-native
  representations.
- **DELETE:** none if no parallel batch prototype exists; no `BatchPipe`, public `BatchPolicy`, or
  global backend-preference runtime may coexist with the single-Pipeline model.

### R9 — Loop/resumable iteration

**Goal:** extend the existing `loop` module rather than add a LoopNode or agent execution engine.

Current/default semantics stay unchanged: for each parent, run the embedded processor/sub-pipeline
once and fold its zero-to-many outputs according to the existing `count`/`emit`/`assign` behavior.

Iterative behavior is opt-in by the presence of iterative controls:

```text
loop(embed=...)
    -> current one-run-per-parent behavior

loop(embed=..., max_iterations=N)
    -> iterative fixed-count behavior

loop(embed=..., until=...)
    -> iterative conditional behavior

loop(embed=..., until=..., max_iterations=N)
    -> conditional behavior with a hard bound
```

There is no redundant `iterative=True` or mode enum.

Deliver iterative mode:

- each iteration's single embedded result becomes the next state;
- zero/multiple result → `LoopStateError` in iterative mode only;
- `until(state, iteration)` checked before first iteration;
- `max_iterations=None` default;
- explicit false-at-limit → `LoopIterationError`;
- checkpoint payload `LoopState[T](value, iteration)` through R6;
- explicit stable loop `id=` where cross-revision state identity is required;
- resume counts total iterations across executions;
- Pipeline DAG remains acyclic; feedback is internal loop execution semantics.

Agent packages compose Pipeline + loop + Publisher/Subscription + StateStore rather than creating
`AgentGraph`/`AgentNetwork` runtime primitives.

**Exit:**

- **ADD:** the existing `loop` module supports bounded/conditional resumable iteration through R6
  state while preserving its default one-run semantics.
- **MIGRATE:** iterative and resumed execution use the ordinary Pipeline/loop/StateStore contracts.
- **DELETE:** none if no parallel loop prototype exists; no `LoopNode`, feedback-graph runtime,
  `AgentGraph`/`AgentNetwork`, or redundant iterative mode surface may coexist with this model.

### R10 — Final Feed-native legacy-seam cleanup

**Goal:** finish and prove the migration rather than begin it here.

By R10, migrations that naturally belonged to earlier runtime capabilities have already landed:

```text
R5A  ordinary streaming transforms/reducers where otherwise ready
R5C  streaming WriteNode + removal of the legacy Python write module
R7   publish/subscribe runtime + removal of send/receive modules + bounded split
R8   batch representation optimization
```

R10 therefore owns:

- remaining eligible source/composer/module migrations;
- final removal/minimization of the legacy whole-source materialization seam;
- sync/async laziness/order/memory/side-effect timing parity audit;
- cleanup of transitional/internal shims made obsolete by the final execution envelope, including
  the async-wrapper shapes the R3-adjacent operator fix left in place: `Awaitable[Stream]` async
  **processor** wrappers, legacy coroutine-completed iterable parsers, and obsolete async-wrapper
  aliases (async **operators** already return an `AsyncIterator` directly);
- proof that genuinely eager operators (`sort`, `reverse`, etc.) are the only intentional
  materialization points.

**Exit:**

- **ADD:** no new public runtime abstraction; parity/laziness/memory proofs cover the final
  Feed-native execution path.
- **MIGRATE:** all remaining eligible sources, composers, and modules use that path.
- **DELETE:** the legacy whole-source materialization seam and obsolete async-wrapper/shim shapes are
  gone; only intentionally eager operators still materialize.

### R11 — adapters: CLI, orchestration, providers, MCP

Only after the core contracts above are stable:

- concrete Target adapters and Format integrations implement the R4A/R5C contracts;
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
- RDP projects R5A/R6 identity/state rather than owning parallel checkpoint semantics.

**Exit:**

- **ADD:** concrete adapters, Click-native CLI seams, orchestration adapters, provider sessions, and
  MCP/provider capability integration consume the stabilized Core contracts.
- **MIGRATE:** provider state/effects/idempotency, long-running operation waiting, and RDP projections
  use R3/R5C/R6/shared capability contracts.
- **DELETE:** provider/RDP/orchestration-local duplicates of state, capability catalogs,
  idempotency, provider waiting, or operation-planning ownership are absent.

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

**Exit:**

- **ADD:** the external `riko-ops` scaffolding and both implementation-readiness fixtures compose the
  intended Operations as Code architecture.
- **MIGRATE:** validate/plan/apply/verify flows consume the shared capability, provider,
  orchestration, Microsoft-plan, and Pipeline contracts.
- **DELETE:** none in Core; the slice is invalid if it introduces a second capability catalog, state
  store, scheduler, provider waiter, Microsoft plan, or runtime execution model.

### R12 — external proof and release gate

Prove the architecture with at least one external extension package before freezing 1.0:

- entry-point module registration through retained P8 seam;
- declared Resource dependency;
- sync-only or async-only implementation adapted in the opposite execution mode;
- external Publisher/Subscription or StateStore implementation;
- generated P9 discoverability includes the extension and contains no removed `Sinks`/legacy-module
  surface;
- no core edit required.

Operations as Code scaffolding may provide an additional ecosystem proof, but it does not replace the
Core external-extension proof above; Core 1.0 must remain independently extensible without requiring
`riko-ops`.

Then run the release-readiness wheel, typing, docs, optional-dependency, public-surface, and Workflow
v1-cutoff gates.

**Exit:**

- **ADD:** an external extension package proves the frozen resource/state/pubsub/target/action seams,
  and the 1.0 release-readiness gates pass.
- **MIGRATE:** generated discovery, release docs, wheels, and public-surface checks describe only the
  final architecture.
- **DELETE:** remaining superseded 0.x APIs/categories and normal Workflow v1 runtime loading are
  gone. Only the explicitly allowed offline pure v1→v2 migration utility may remain.

## 4a. Contracts that are not frozen yet

Two areas remain deliberately provisional:

- **automatic semantic fingerprinting (R2B).** The best-effort helper may grow or shrink. Nothing
  durable may depend on its completeness; `version=` is the stable surface;
- **batch representation negotiation (R8).** The candidate-intersection and cost model is right in
  shape, but declared conversion costs and the tiebreak order need real graphs before they are
  fixed.

The Workflow v2 topology/normalization decisions, Pipeline/private-execution split, Target/Format
structural model, cache replay semantics, write/action effect model, state/checkpoint ownership,
fanout topology, and additive loop iteration semantics are treated as settled.

## 5. Parallelizable work

After R0/R1:

- R2A encoding work and most R3 Context/Resource definition work may proceed in parallel if their
  shared `identity_encoder` interface is kept narrow. R2B may proceed beside both;
- remaining P9 generated discoverability work can proceed independently of R2A/R2B/R3/R4A, provided
  stubs target final `Pipeline` names only when R4A is available and do not preserve the old `Sinks`
  bucket;
- CLI command registry/Click plugin mechanics can proceed independently, but execution commands must
  wait for R4B.

After R4B/R5A:

- R5B cache/effect/state work follows its dependency chain, while R7 fanout may proceed independently
  from R5A;
- ordinary Feed-native transforms may migrate as soon as their only missing prerequisite is R5A;
- observability consumers may be developed against the R4B `EventSink` contract while semantic event
  types continue to land with their owning phases.

After R11 service seams stabilize, provider import/export scaffolding, operation repository/model
work, and CLI command-provider stubs may proceed in parallel only where their interfaces are already
owned. The first cross-provider compatibility and orchestration scenarios wait for those seams.

Do **not** parallelize competing implementations of identity, workflow normalization, resource
lifecycle, cache replay, state, pub/sub, effect dispatch, capability discovery/policy, operation
planning, provider waiting, or compatibility ownership. Each has one authoritative implementation.
In particular, no PR after R4B may introduce its own task group, exit stack, portal, event transport,
or executor.

## 6. First implementation slice

The recommended next coding PR remains **R0**, not an Operations as Code, state-store, cache, or
pub/sub PR, unless the branch has already completed the prerequisite sequence by the time
implementation starts.

R0 is deliberately small and low-risk:

1. rename the internal `Pipeline` callable alias to `PipeCallable`;
2. add characterization tests for resolver native selection and source normalization;
3. add the failing desired-behavior test for R2A omitted-vs-`None` semantics;
4. add characterization tests around current pub/sub lifecycle;
5. make no released public runtime change yet.

After R0, R1/R2A/R2B/R3 can proceed without fighting the public `Pipeline` class name or relying on
unrecorded legacy behavior. R11A is **not** permission to jump around those prerequisites; it is the
first Operations as Code slice once the owning lower-level seams exist.

## 7. Completion criteria

The implementation reconciliation is complete when:

1. `Pipeline` is the only target public pipeline definition and the old Pipe/Collection classes are
   absent rather than wrapped;
2. authoring forms normalize once to a strict canonical Workflow v2 definition consumed by
   serialization, validation, compilation, and execution;
3. during 0.x released Workflow v1 input migrates only at the loader boundary, and normal 1.0
   runtime loading is v2-only;
4. each iteration creates independent private execution state;
5. Context contains immutable definitions; execution-created resource values never live in Context,
   while explicitly caller-owned `Resource.from_external(...)` values remain process-local and
   carry no durable serialization guarantee;
6. all durable identity/fingerprints/idempotency/checkpoints share one canonical encoder, and durable
   semantics rest on explicit `version=` rather than on automatic callable introspection being
   complete;
7. reusable owned resource lifecycle is definition/factory based, and every execution-owned
   acquisition, context manager, task, rollback, bridge, and teardown is attached to the execution's
   lifetime primitives;
8. cache replay uses the finalized Mezmoize-backed CacheNode contract and never publishes an
   incomplete fill;
9. `write`/actions pass records through and report completion through the common EventSink; the
   legacy Python `write` module and the interim fluent `sink()` surface are absent;
10. StateStore is the one persistence protocol and all writes are CAS-protected;
11. pub/sub/split lifecycle is execution-owned, bounded, and derived from canonical topology rather
    than hidden DONE/PENDING bookkeeping; legacy `send`/`receive` modules are absent and subscriber
    `func=` retains its receive/materialization-time semantics;
12. batch mode does not create a second pipeline hierarchy, and representation is negotiated by
    capability/cost rather than by a global backend ranking;
13. iterative behavior extends the existing loop module and is activated by `until`/
    `max_iterations`, while the default preserves current one-run semantics;
14. Feed-native migration happens with its owning runtime phases and R10 leaves only genuinely eager
    materialization points;
15. generated discovery contains module `Sources`/`Transforms` plus separate `Targets`/`Formats`,
    with no `Sinks` compatibility bucket;
16. external packages can use resources/state/pubsub/targets/actions without core changes;
17. Operations as Code scaffolding lives outside Core and composes provider/capability/orchestration
    owners without duplicate contracts;
18. the SuperOps→GitHub Actions and Autopilot fixtures prove import/deploy and
    plan/approval/wait/verify composition respectively;
19. the release docs and generated public surface contain none of the superseded abstractions listed
    in §2.
