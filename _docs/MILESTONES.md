# riko Milestones — P-track file maps & exit tests

Consolidates the former `MILESTONE1_FILEMAP/TESTS.md` and `MILESTONE2_FILEMAP/TESTS.md`.
It is the breadth-first companion to [PHASE_CHECKLISTS.md](PHASE_CHECKLISTS.md).

This document now owns **P-track history, retained file maps, and phase exit-test references**.
It does **not** own the reconciled end-state API or the forward implementation dependency graph.

Authoritative routing:

```text
live phase status
    PHASE_CHECKLISTS.md

what ships / where it lives
    IMPLEMENTED.md

end-state semantic contracts
    matching gameplan, especially execution-semantics.md

forward implementation dependency order
    gameplans/implementation-sequence.md

release gate
    gameplans/release-readiness.md
```

Historical P8–P14 sketches below are useful provenance only. If an older phase shape conflicts with
a reconciled gameplan, the gameplan wins.

Legend: **NEW** create · **MOD** edit in place · **EXT** separate distribution, not core.

---

## Milestone 1 (Phases 1–7)

Everything the M1 filemap/tests specified shipped. As-built locations live in
[IMPLEMENTED.md](IMPLEMENTED.md), while phase decisions/carryovers live in
[PHASE_CHECKLISTS.md](PHASE_CHECKLISTS.md).

The M1 exit-test tree includes:

- `tests/public/test_imports.py` (P1 tiers), `test_config_public.py` (P2);
- `tests/internal/test_config_dynamic.py` / `test_preparation.py` (P2/P3),
  `test_inference.py` (P4), `test_assignment.py` (P3);
- `tests/public/test_pipe_lifecycle.py` (P5), `test_context_modes.py` (P6),
  `test_sync_async_parity.py` (P7);
- `tests/typing/{valid,invalid}/` — Pyright gate on the public surface.

---

## Milestone 2 (Phases 8–14)

The P-track remains useful for status/history, but the architecture has since been reconciled across
runtime, state, resources, pub/sub, batching, CLI, orchestration, and agents.

### Retained foundations

#### P8 — registry + resolution

The P8 separation remains structurally correct and shipped:

```text
ModuleRegistry
    leaf module implementations

PipelineResolver
    named composed pipelines

PipeResolver
    compiler-free facade
```

Retain:

- runtime registration -> entry-point -> built-in precedence;
- named-pipeline resolution separate from module resolution;
- compiler-local `output` handling;
- no mutation of resolved callables;
- transitive `ModuleNotFoundError` preservation;
- external package registration through `riko.modules` entry points.

The future public `Pipeline` class requires the current internal callable alias named `Pipeline` to
be renamed to `PipeCallable`; that is an implementation-sequence task, not a P8 redesign.

#### P9 / P9A — discoverability

Retain the generated `Modules` / `Sources` / `Transforms` / `Sinks` discovery layer,
`list_modules()`, `describe_module()`, and generated-code tooling.

Remaining stub/installed-environment work must target the **final public `Pipeline`** surface and must
not encode removed `SyncPipe` / `AsyncPipe` APIs. Exact design lives in
[gameplans/module-enums.md](gameplans/module-enums.md).

The earlier `.then(...)` proposal is not authoritative; current Pipeline fluent shape is owned by
[gameplans/release-readiness.md](gameplans/release-readiness.md) and
[gameplans/execution-semantics.md](gameplans/execution-semantics.md).

#### P10 — bounded execution algorithms

Retain the bounded async mapping, ordered/unordered delivery, worker/executor, and shared-budget
algorithms. Their current placement in legacy collection/runtime classes is temporary; the final
private execution layer reuses/refactors those mechanics.

### Superseded pending-phase sketches

Do **not** implement these older P11–P14 shapes merely because they appear in historical P-track
notes or old file maps:

```text
public ExecutionContext
mutable Context.resources containing live handles
process-global pub/sub as final ownership
poll(interval|event|hybrid) as one generic source API
BatchPipe / public BatchPolicy hierarchy
SourceCheckpoint / CheckpointStore parallel to StateStore
generic StateStore leases
AgentGraph / AgentNetwork
argparse-shaped CLI plugin contracts
execution knobs on with_config()
public collect()/first() execution terminals
```

Current replacements are:

- immutable `Context` + `Resource` definitions; private execution owns live handles;
- object-first `Publisher` / `Subscription` / `Channel` and execution-owned fan-out;
- `Pipeline.poll(source, interval=...)` for repeated source observation;
- `wait_operation(..., mode="interval"|"event"|"hybrid")` only for an already-started provider
  operation;
- one `Pipeline(batch=True, batch_size=...)` batch model;
- one `FeedState` / `StateStore` / CAS checkpoint model;
- agents reuse `Pipeline` + existing `loop`;
- Click-native CLI extensions;
- `with_execution(...)` for execution-wide options;
- Python iteration (`list`, `for`, `async for`) as the execution mechanism.

See [gameplans/ownership.md](gameplans/ownership.md) for the owner map.

---

## Historical P-track file map

The following entries remain useful as a map from phase names to implementation areas. They are not
an alternative semantic specification.

| Area | P-track phase | Current interpretation |
|---|---:|---|
| `riko/ext/registry.py` | P8 | retained module implementation registry |
| `riko/ext/_pipelines.py` | P8 | retained named-pipeline resolver |
| `riko/ext/_resolver.py` | P8 | retained resolution facade |
| generated module names/stubs | P9 | discovery layer over final Pipeline surface |
| bounded async map / concurrency helpers | P10 | mechanics migrate/reuse under private executions |
| pub/sub protocols | P11 | target owned by `fanout-topology.md` + `execution-semantics.md` |
| source recurrence | P11 | `Pipeline.poll`; monitoring semantics in `feed-monitoring.md` |
| stable errors/events | P12 | common error/event foundations, extended by identity/state errors |
| public/internal/typing split | P13 | status + test ownership in `testing.md` |
| external packages | P14 | prove extension seams after core contracts stabilize |

### External distributions

| Package | Intended proof |
|---|---|
| `riko-microsoft` | Graph/ARM/PowerShell + Service Bus/Event Grid + declared resources + provider operations; Autopilot remains a concrete end-to-end scenario |
| `riko-ai` | inference/tool/retrieval adapters composed with ordinary Pipeline/loop/state/pubsub contracts |

Core changes should not be required per external integration once the common extension/resource/state
contracts are stable.

---

## Forward implementation dependency order

The authoritative dependency graph is now
[gameplans/implementation-sequence.md](gameplans/implementation-sequence.md).

Its high-level order is:

```text
R0  characterization + internal type-name cleanup
R1  stable errors
R2A canonical value encoding
R2B semantic identity + explicit version contract
R3  immutable Context + Resource definitions (context-manager lifecycle)
R4  public Pipeline + private SyncExecution/AsyncExecution
    (task group + exit stack + portal/worker bridge established here)
R5  FeedResult / Metadata / private per-item provenance
R6  StateStore / checkpoint / CAS / StateStoreCapabilities / idempotency
R7  execution-owned pub/sub + streaming split
R8  single-Pipeline batch execution
R9  loop/agent resumable state
R10 Feed-native module migration
R11 CLI/orchestration/provider/MCP adapters
R12 external extension proof + release gate
```

This R-sequence is intentionally not a renumbering of P8–P14; it captures cross-cutting foundations
that were discovered during reconciliation.

Note the namespace collision: `correctness-audit.md`, `rdp-connect.md`, and `rest-incremental.md`
each use their own `R<n>` labels for unrelated things. A bare "R2" is ambiguous across documents;
always qualify it (implementation-sequence R2A, correctness-audit R2).

---

## Pipeline / private-execution release gate

This is the central cross-cutting API change and remains a release gate rather than a standalone
P-phase.

Semantic owners:

- API shape: [release-readiness.md](gameplans/release-readiness.md);
- execution/resource/state semantics: [execution-semantics.md](gameplans/execution-semantics.md);
- callable/decorator specialization: [callable-pipes.md](gameplans/callable-pipes.md);
- source normalization/Feed-native migration: [feed-native-streaming.md](gameplans/feed-native-streaming.md);
- fan-out: [fanout-topology.md](gameplans/fanout-topology.md).

### Target file map

| File | Purpose |
|---|---|
| `riko/pipeline.py` NEW | public immutable `Pipeline[T]` definition/DAG; `iter` -> private sync execution, `aiter` -> private async execution |
| `riko/_execution/__init__.py` NEW | private execution package |
| `riko/_execution/base.py` NEW | shared execution scaffolding/options/plan state |
| `riko/_execution/lifetime.py` NEW | the three execution lifetime primitives: task group, exit stack, portal/worker bridge. Every later feature borrows these rather than creating its own |
| `riko/_execution/sync.py` NEW | `SyncExecution`, portal/resource ownership, deterministic teardown |
| `riko/_execution/async_.py` NEW | `AsyncExecution`, native async, bounded concurrency, structured task-group ownership |
| `riko/_execution/adapters.py` NEW | private sync<->async adaptation; native implementation wins |
| `riko/_execution/streams.py` NEW | one source-normalization boundary |
| `riko/_execution/plan.py` NEW | resolved DAG/steps and execution preparation |
| `riko/context.py` MOD | immutable Context definitions, Context-local modules/resources, first-class state-store capability |
| `riko/resources.py` NEW/MOD | `Resource`, factories, dependency declarations; context-manager/generator lifecycle with `from_external()` for caller-owned objects |
| `riko/types/general.py` MOD | current internal callable alias `Pipeline` -> `PipeCallable` before public class lands |
| `riko/collections.py` MOD/RETIRE | migrate reusable mechanics into `_execution`; legacy public classes are not the target surface |
| `riko/modules/_decorators.py` MOD | Feed-native async parser forms and prepared `resources` argument |
| `riko/ext/{registry,_resolver}.py` MOD | execution-mode/native-wins resolution over retained P8 definitions |
| `riko/api.py` / `riko/__init__.py` MOD | export final public Pipeline/Context/state/pubsub surface deliberately |

### Configuration correctness / correctness-audit R2

(That is the audit register's R2, not implementation-sequence R2A/R2B.)

The current `PyPipe.__call__` can erase constructor options when omitted call-time kwargs are written
as `None`, and object attributes can disagree with the kwargs actually executed.

The final architecture discharges that defect by removing mutable pipe reconfiguration:

- a Pipeline step's configuration is fixed when that step is declared;
- fluent composition creates a **new immutable Pipeline definition**;
- omitted step arguments are never interpreted as explicit clearing;
- `with_execution(...)` changes only execution-wide settings;
- no mutable definition/runtime copy can drift from the options actually executed.

There is therefore no target equivalent of "call an existing pipe object to partially reconfigure
it". Explicit `None` remains meaningful only where the specific declared step API accepts it.

### Exit tests

At minimum:

- same Pipeline definition can run under sync and async execution;
- each iteration creates fresh private runtime state;
- replayable sources replay, generator instances remain one-shot and are never secretly buffered;
- a Mapping source is one record, not an iterable of keys;
- native sync/async module implementation wins for the matching execution mode;
- sync-only under async does not block the event loop; async-only under sync uses one execution
  portal rather than one runtime per item;
- resource open/rollback/cleanup semantics hold on success, early close, failure, cancellation, and
  partial consumption;
- `with_execution(...)` changes execution settings without altering declared step configuration;
- legacy `SyncPipe` / `AsyncPipe` / Collection names are absent from the final public target surface;
- no Asyncer/portal/private execution implementation leaks into stable imports.

---

## Pending phase exit-test ownership

Detailed semantic tests live with their owning gameplans. P-track categories remain:

- **P8** — registry/resolver precedence, compiler independence, extension entry-point proof;
- **P9** — installed-environment discovery, generated stubs, typing;
- **P10** — bounded concurrency/backpressure regression coverage;
- **P11** — public pub/sub/poll behavior, now specified by fanout/monitoring/execution owners;
- **P12** — stable errors/events, including identity/state families as required by later runtime work;
- **P13** — public/internal/typing suite boundaries;
- **P14** — external package proof with no per-integration core edit.

Do not copy owner-level contract tests into this file; link to their gameplans/test plans instead.

---

## M2 exit

M2 is complete when the retained P8/P9/P10 foundations and the reconciled R0–R12 implementation
sequence satisfy their owner-level exit criteria, the M1 suite remains unregressed, Pyright is clean
on the public surface, and at least one external extension proves registration + resources +
sync/async adaptation + pub/sub or StateStore integration with **no core edit**.
