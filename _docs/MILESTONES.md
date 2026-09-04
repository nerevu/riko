# riko Milestones — P-track file maps & exit tests

Consolidates the former `MILESTONE1_FILEMAP/TESTS.md` and `MILESTONE2_FILEMAP/TESTS.md`.
It is the breadth-first companion to [PHASE_CHECKLISTS.md](PHASE_CHECKLISTS.md).

This document owns **P-track history, retained file maps, and phase exit-test references**. It does
**not** own the reconciled end-state API or forward implementation dependency graph.

Authoritative routing:

```text
live phase status
    PHASE_CHECKLISTS.md

what ships / where it lives
    IMPLEMENTED.md

end-state semantic contracts
    matching gameplan / ownership.md

forward implementation dependency order
    gameplans/implementation-sequence.md

release gate
    gameplans/release-readiness.md
```

Historical P8–P14 sketches below are useful provenance only. If an older phase shape conflicts with a
reconciled gameplan, the gameplan wins.

Legend: **NEW** create · **MOD** edit in place · **EXT** separate distribution, not core.

---

## Milestone 1 (Phases 1–7)

Everything the M1 filemap/tests specified shipped. As-built locations live in `IMPLEMENTED.md`, while
phase decisions/carryovers live in `PHASE_CHECKLISTS.md`.

The M1 exit-test tree includes:

- `tests/public/test_imports.py` (P1 tiers), `test_config_public.py` (P2);
- `tests/internal/test_config_dynamic.py` / `test_preparation.py` (P2/P3), `test_inference.py` (P4),
  `test_assignment.py` (P3);
- `tests/public/test_pipe_lifecycle.py` (P5), `test_context_modes.py` (P6),
  `test_sync_async_parity.py` (P7);
- `tests/typing/{valid,invalid}/` — Pyright gate on the public surface.

---

## Milestone 2 (Phases 8–14)

The P-track remains useful for status/history, but architecture has since been reconciled across
workflow definition, execution, resources, cache, effects, state, pub/sub, batching, CLI,
orchestration, and agents.

### Retained foundations

#### P8 — registry + resolution

The shipped P8 separation remains structurally correct:

```text
ModuleRegistry
    leaf module implementations

PipelineResolver
    named composed pipelines

PipeResolver
    compiler-free facade
```

Retain runtime-registration -> entry-point -> built-in precedence, named-pipeline resolution separate
from module resolution, compiler-local legacy output handling during migration, transitive
`ModuleNotFoundError` preservation, and external package registration through entry points.

The future public `Pipeline` class requires the old internal callable alias named `Pipeline` to become
`PipeCallable`; that is implementation-sequence R0, not a P8 redesign.

#### P9 / P9A — discoverability

Retain generated `Modules` / `Sources` / `Transforms` / `Sinks` discovery, `list_modules()`,
`describe_module()`, and generated-code tooling.

Remaining stub/installed-environment work must target the final public `Pipeline` surface and must not
encode removed `SyncPipe` / `AsyncPipe` APIs. Exact design lives in `gameplans/module-enums.md`.

#### P10 — bounded execution algorithms

Retain bounded async mapping, ordered/unordered delivery, worker/executor, and shared-budget
algorithms. Their current placement in legacy collection/runtime classes is temporary; R4B private
execution reuses/refactors those mechanics.

### Superseded pending-phase sketches

Do **not** implement these older P11–P14 shapes merely because they appear in historical notes:

```text
public ExecutionContext
mutable Context.resources containing resolved resource values
process-global pub/sub as final ownership
poll(interval|event|hybrid) as one generic source API
BatchPipe / public BatchPolicy hierarchy
SourceCheckpoint / CheckpointStore parallel to StateStore
generic StateStore leases
AgentGraph / AgentNetwork
argparse-shaped CLI plugin contracts
execution knobs on with_config()
public collect()/first() execution terminals
public sink() terminal parallel to write()
global Arrow -> Polars -> Pandas backend preference
```

Current replacements include:

- immutable Context + Resource definitions; private execution owns resolved resource values;
- canonical Workflow v2 with explicit node/edge/port identity;
- one execution EventSink transport;
- object-first Publisher/Subscription and `SubscribeNode` + `PublishEdge`;
- `Pipeline.poll(source, interval=...)` for source recurrence;
- provider `wait_operation(...)` only for an already-started operation;
- one `Pipeline(batch=True, batch_size=...)` batch model with capability/cost negotiation;
- explicit `Pipeline.cache()` backed through Mezmoize;
- one FeedState/StateStore/CAS checkpoint model;
- `Pipeline.write()`/ActionNode effects with out-of-band results; no target public sink terminal;
- agents reuse Pipeline + existing loop;
- Click-native CLI extensions;
- `with_execution(...)` for execution-wide options;
- Python iteration (`list`, `for`, `async for`) as execution mechanism.

See [gameplans/ownership.md](gameplans/ownership.md) for the owner map.

---

## Historical P-track file map

These entries remain a map from phase names to implementation areas, not an alternative spec.

| Area | P-track phase | Current interpretation |
|---|---:|---|
| `riko/ext/registry.py` | P8 | retained module implementation registry |
| `riko/ext/_pipelines.py` | P8 | retained named-pipeline resolver |
| `riko/ext/_resolver.py` | P8 | retained resolution facade |
| generated module names/stubs | P9 | discovery layer over final Pipeline surface |
| bounded async map/concurrency helpers | P10 | mechanics migrate/reuse under R4B private executions |
| pub/sub protocols | P11 | topology/runtime owned by fanout + execution owners |
| source recurrence | P11 | `Pipeline.poll`; monitoring semantics in `feed-monitoring.md` |
| stable errors/events | P12 | common errors + EventSink transport/payload owners |
| public/internal/typing split | P13 | status/test ownership in `testing.md` |
| external packages | P14 | prove extension seams after Core contracts stabilize |

### External distributions

| Package | Intended proof |
|---|---|
| `riko-microsoft` | Graph/ARM/PowerShell + Service Bus/Event Grid + resources + provider actions; Autopilot is end-to-end scenario |
| `riko-ai` | inference/tool/retrieval adapters composed with Pipeline/loop/state/pubsub contracts |

Core changes should not be required per external integration once extension/resource/state/target/
action contracts are stable.

---

## Forward implementation dependency order

The authoritative graph is
[gameplans/implementation-sequence.md](gameplans/implementation-sequence.md).

High-level order:

```text
R0   characterization + internal naming
R1   stable errors
R2A  canonical value encoding
R2B  semantic identity + explicit version contract
R3   immutable Context + Resource definitions
R4A  public Pipeline definition + canonical Workflow v2 IR
R4B  private SyncExecution/AsyncExecution + task group/exit stack/bridge/EventSink transport
R5A  FeedResult / Metadata / private per-item provenance
  ├──────────────> R7 execution-owned publish/subscribe + streaming split
  ↓
R5B  CacheNode runtime / Mezmoize replay
  ↓
R5C  WriteNode + ActionNode effects
  ↓
R6   StateStore / checkpoint / CAS / idempotency
R8   single-Pipeline batch execution
R9   additive iterative loop state
R10  final Feed-native compatibility cleanup
R11  adapters/providers/orchestration/MCP
R12  external extension proof + release gate
```

Feed-native module conversion occurs incrementally as its owning runtime capability lands; R10 is the
final seam-removal/parity proof, not the start of the migration.

This R-sequence is not a renumbering of P8–P14; it captures cross-cutting foundations discovered
during reconciliation.

Note the namespace collision: `correctness-audit.md`, `rdp-connect.md`, and `rest-incremental.md` use
their own unrelated `R<n>` labels. Always qualify an R label when ambiguity is possible.

---

## Pipeline / Workflow v2 / private-execution release gate

This is the central cross-cutting API change and remains a release gate rather than a standalone
P-phase.

Semantic owners:

- Workflow v2 definition/normalization: `gameplans/extensibility.md`;
- execution/resource/state semantics: `gameplans/execution-semantics.md`;
- execution event transport: `gameplans/events.md`;
- cache/replay: `gameplans/cache.md`;
- write/action effects: `gameplans/effects.md`;
- callable/decorator specialization: `gameplans/callable-pipes.md`;
- source normalization/Feed-native migration: `gameplans/feed-native-streaming.md`;
- fan-out: `gameplans/fanout-topology.md`.

### Target file map

The exact file split may evolve, but responsibilities must stay separated:

| File/area | Purpose |
|---|---|
| `riko/pipeline.py` NEW | public immutable `Pipeline[T]` definition/DAG; iteration creates private execution |
| workflow-definition/private schema modules NEW | canonical Workflow v2 node/edge/port/input/Target/Format types + normalization/migration/validation |
| `riko/_execution/__init__.py` NEW | private execution package |
| `riko/_execution/base.py` NEW | shared execution scaffolding/options/preparation state |
| `riko/_execution/lifetime.py` NEW | task group, exit stack, portal/worker bridge |
| `riko/_execution/sync.py` NEW | SyncExecution, portal/resource ownership, teardown |
| `riko/_execution/async_.py` NEW | AsyncExecution, native async, structured concurrency |
| `riko/_execution/adapters.py` NEW | private sync/async adaptation |
| `riko/_execution/streams.py` NEW | one source-normalization boundary |
| event transport private module NEW | EventSink dispatch owned by each execution |
| cache private shim NEW | CacheNode -> Mezmoize integration; no Riko cache-store hierarchy |
| `riko/context.py` MOD | immutable Context/resources/state-store capability |
| `riko/resources.py` MOD | Resource definitions/from_external/context-manager lifecycle |
| `riko/types/general.py` MOD | internal callable alias Pipeline -> PipeCallable |
| `riko/collections.py` MOD/RETIRE | migrate mechanics; legacy classes not target public surface |
| `riko/modules/_decorators.py` MOD | Feed-native parser forms + prepared resources |
| `riko/ext/{registry,_resolver}.py` MOD | native-wins resolution over retained P8 definitions |
| `riko/api.py` / `riko/__init__.py` MOD | deliberate final stable exports |

### Configuration correctness / correctness-audit R2

The current `PyPipe.__call__` can erase constructor options when omitted call-time kwargs are written
as `None`, and object attributes can disagree with executed kwargs.

The final architecture discharges that defect by removing mutable pipe reconfiguration:

- step configuration is fixed when declared;
- fluent composition creates a new immutable Pipeline definition;
- omitted arguments are never interpreted as explicit clearing;
- `with_execution(...)` changes only execution-wide settings;
- no mutable definition/runtime copy can drift from executed options.

### Exit tests

At minimum:

- same Pipeline definition can run under sync and async execution;
- each iteration creates fresh private runtime state;
- authoring forms normalize once to deterministic strict Workflow v2;
- fan-in/branch semantics survive deterministic edge sorting because ports carry identity;
- replayable sources replay, generator instances remain one-shot and are never secretly buffered;
- Mapping source is one record, not iterable keys;
- native sync/async module implementation wins for matching mode;
- sync-only under async does not block event loop; async-only under sync uses one execution portal;
- resource rollback/cleanup holds on success, early close, failure, cancellation, partial consumption;
- EventSink is execution-local and out-of-band;
- incomplete cache fills never replay;
- write/action effects preserve records and emit result events;
- `with_execution(...)` changes execution settings without altering step configuration;
- legacy SyncPipe/AsyncPipe/Collection and target public sink names are absent from final target
  surface;
- no AnyIO/portal/private execution type leaks into stable imports.

---

## Pending phase exit-test ownership

Detailed semantic tests live with owning gameplans. P-track categories remain historical/status
buckets:

- **P8** registry/resolver precedence/compiler independence/entry-point proof;
- **P9** installed-environment discovery/generated stubs/typing;
- **P10** bounded concurrency/backpressure regression coverage;
- **P11** pub/sub/poll historical category, now fanout/monitoring/execution-owned;
- **P12** errors/events historical category, now split among error/event/feature owners;
- **P13** public/internal/typing suite boundaries;
- **P14** external package proof with no per-integration Core edit.

Do not copy owner-level contract tests here.

---

## M2 exit

M2 is complete when retained P8/P9/P10 foundations and the reconciled R0–R12 implementation sequence
satisfy their owner-level exit criteria, the M1 suite remains unregressed, Pyright is clean on the
public surface, canonical Workflow v2/private execution are established, and at least one external
extension proves registration + resources + cross-mode adaptation + pub/sub or StateStore integration
with **no Core edit**.
