# Release readiness gameplan

## 1. Mission

Treat the last mile to a public 1.0 as a **release-gate pass on semantics**, not cosmetic cleanup.
Riko's core is mature; the remaining rough edges are places where implementation mechanics leak into
the user model. This plan owns the cross-cutting **DX/API-shape** decisions and the **release/package
fidelity** gate; it routes the parts owned elsewhere to their owners.

> **Scope:** A release gate — not a single P-phase; it *pulls forward and
> sequences* items across P9/P11/P12/P13 plus new API-shape decisions. Guiding triage in § 8.
>
> **Provenance.** Folded in from the untracked `_docs/ux_polish.md` scratch analysis.
>
> **Ownership boundary.** This is **internal API-shape + release readiness**. It owns the pre-1.0
> Python API compatibility/removal policy below. It is distinct from
> [extensibility.md](extensibility.md) **E7 "1.0 readiness"**, which owns the *ecosystem* side
> (conformance badges, stable-API publication, external-plugin proof) and E3, which owns the bounded
> Workflow v1 → v2 persisted-format migration/cutoff. Owned-elsewhere clusters this plan only
> *sequences*:
> - **Pub/sub 1.0 contract** → [fanout-topology.md](fanout-topology.md) **F1/F4/F5** + P11;
> - **Fluent discoverability** → [module-enums.md](module-enums.md) (P9);
> - **Error hierarchy** → P12 ([MILESTONES.md](../MILESTONES.md));
> - **Execution, Context/resources, state, identity, batching** →
>   [execution-semantics.md](execution-semantics.md);
> - **Unified CLI** → [cli.md](cli.md).

### 1.1 Pre-1.0 compatibility policy

Compatibility follows the status and persistence of the surface, not whether useful implementation
code exists behind it:

```text
unreleased API/experiment
    -> remove outright
    -> no deprecation alias, loader form, or compatibility burden

released Python API superseded by the target architecture
    -> clean break during 0.x
    -> document old -> new migration
    -> no deprecated wrapper solely for compatibility

released persisted/user-authored format
    -> deterministic migration for a bounded window when practical
    -> normalize immediately to the current canonical form

retained architecture
    -> preserve normally
```

Concrete consequences already locked:

- unreleased `sink()` and its sink-specific public/discovery/serialization surfaces are removed
  outright;
- the shipped `riko.modules.write` module is removed when `Pipeline.write()` / `WriteNode` lands;
- `SyncPipe` / `AsyncPipe` / `SyncCollection` / `AsyncCollection` are removed when the Pipeline /
  private-execution replacement lands;
- low-level `send` / `receive` Python modules are removed when R7 lands the object-first
  `publish` / `subscribe` API;
- Workflow v1 is accepted only through the migration boundary during 0.x; normal v1 loading is
  removed at 1.0, while an offline `migrate_v1_to_v2()` utility may remain.

Useful algorithms, adapters, codecs, or lifecycle mechanics may be refactored behind replacement
APIs. Reusing implementation does not preserve the superseded public abstraction.

## 2. Pub/sub: the minimum 1.0-caliber contract (owned by fanout-topology.md)

The pre-1.0 gate requires the full pub/sub contract — whose mechanics and rationale are owned by
[fanout-topology.md](fanout-topology.md) and the shared protocols/runtime semantics in
[execution-semantics.md](execution-semantics.md) — to land at release quality.

Release-readiness gates these outcomes:

- public object-first `publish` / `subscribe` vocabulary; low-level `send` / `receive` are removed
  when the replacement lands rather than retained as compatibility modules;
- eager local subscription declarations, with no `next(receiver)` priming;
- no `PENDING` records on the data stream — waiting is a `Subscription` concern, not an `Item`
  variant;
- bounded buffers with `buffer_size=0` / rendezvous as the default;
- lossless/blocking behavior by default, with explicit opt-in drop semantics only where the
  subscription contract permits it;
- pub/sub runtime state owned by each private execution, never by process globals or mutable public
  `Context` state;
- async receive/delivery is incremental and sync/async observable semantics match;
- subscriber `func=` is retained as the receive-time hook; its return value is discarded and the
  original item passes onward;
- subscription objects replace hidden `ids`/`DONE` bookkeeping;
- local `publish(subscription_pipeline)` attaches the complete side branch to the owning execution,
  so cleanup does not depend on the user draining ignored branch output.

**Vocabulary:** `others`→`targets`, `max_len`→`buffer_size`, `max_wait`→`timeout`/`idle_timeout`.
`func` is retained intentionally: it runs at subscription delivery/materialization time, which is
semantically different from ordinary downstream UDF evaluation timing. This is a clean break for the
final public Pipeline API; legacy low-level names are migration inputs only until R7 removes them.

## 3. Configuration correctness

- **Stop silently accepting invalid `Context`.** Remove the catch-all `**kwargs`
  (`Context(verbsoe=...)` must not look successful). Unknown/renamed kwargs raise an actionable
  error.
- **`Context` is immutable environment definition, not live execution state.** Context-local module
  and `Resource` definitions are derived with `with_module()` / `with_resource()`; resolved handles,
  portals, state-store adapters, and pub/sub hubs belong to the private execution.
- **Validate module config early** — unknown keys, invalid enums/operators, conflicting options,
  wrong types — at Pipeline construction/preparation rather than after source consumption begins.
- **Step config and execution config are separate.** Step configuration is fixed when a step is
  declared; execution-wide settings are derived with `with_execution(...)` and never mutate a step.

## 4. API-shape compression (the highest-value remaining work)

> **Make streaming, boundedness, ordering, and side-effect semantics properties of the pipeline
> definition and execution plan, not consequences of whether the user picked `SyncPipe` or
> `AsyncPipe`.**

> **Decisions locked (2026-08).** Clean break for the target Pipeline surface. Go straight to the
> full `Pipeline` definition/private-execution split — no interim immutable-`PyPipe` stepping stone.
> `Pipeline(source=...)` is the stream constructor; execution settings derive through
> `with_execution(...)`.

- **`Pipeline` is the sole public pipeline concept.** A reusable, immutable definition lives in
  `riko/pipeline.py`, exported from `riko`. `Pipeline("fetch", source=...)` or
  `Pipeline(source=...)` creates a definition; fluent composition returns new definitions and never
  mutates the original.
- **Definition vs execution — the full split.** `iter(flow)` builds a fresh private
  `SyncExecution`; `aiter(flow)` builds a fresh private `AsyncExecution`. The same definition runs
  under `for` or `async for`; each iteration is an independent one-shot execution. No public
  `Execution(...)` constructor is needed for normal use.
- **`SyncPipe`/`AsyncPipe`/`SyncCollection`/`AsyncCollection` are not the target public surface.**
  Their mature mechanics are refactored into private execution machinery rather than preserved as
  parallel public concepts.
- **Collection disappears as a separate concept.** `Pipeline(source=[...])` covers iterable
  sources. Source classification is one boundary: mapping = one record; iterable = stream;
  `str`/`bytes` = one item; async iterables/awaitables resolve through async execution. Replayability
  follows the source itself: a list can replay, while a generator instance remains one-shot and is
  never secretly buffered.
- **Rename the internal `Pipeline` callable alias first.** `riko/types/general.py` currently uses
  `Pipeline` for parser callables; rename that internal alias to `PipeCallable` before the public
  class lands.
- **Iteration is the execution API.** Do not add executing `collect()` or `first()` terminals.
  `list(flow)`, `for`, and `async for` execute; `take(n)` remains a transform. Side-effecting
  operations such as `write` remain explicit pipeline nodes/effects rather than a second execution
  mechanism.
- **One execution-configuration vocabulary.** Use
  `flow.with_execution(executor=..., concurrency=..., ordered=..., ...)` for execution-wide
  settings. Do not overload `with_config()` with execution knobs and do not carry forward
  `parallel`/`threads`/`pool`/`pool_scope` as final Pipeline vocabulary.
- **Execution-mode adaptation is owned by
  [execution-semantics.md](execution-semantics.md).** Native implementations win; sync-only code is
  adapted for async execution and async-only code is adapted through the sync execution portal.
  AnyIO/portal implementation details remain private.
- **Decorator DX is owned by [callable-pipes.md](callable-pipes.md).** `@processor async def pipe`
  works for single-implementation async modules; `isasync=`/`async_pipe` remain for the cases where
  they are structurally needed.
- **`Context` becomes the immutable environment.** Runtime handles do not live on it. Resource
  definitions, optional `state_store`, Context-local module definitions, and identity-encoder
  selection are resolved during execution preparation.
- **Constructor stops being a union of every module's knobs.** `assign`/`field`/`func`/`targets`/
  `skip_if` belong to the declared node/step rather than global Pipeline execution config.
- **Collapse the runtime-utility surface.** De-emphasize backend/bridge helpers from the stable API;
  users write normal Python iteration.

**Migration shape:**

```text
SyncPipe(mod, ...)           → Pipeline(mod, source=...)
AsyncPipe(mod, ...)          → Pipeline(mod, source=...)
SyncCollection(mod, srcs)    → Pipeline(mod, source=srcs)
AsyncCollection(mod, srcs)   → Pipeline(mod, source=srcs)
```

## 5. Error UX (owned by P12 / execution-semantics)

Pull stable errors forward before declaring the API stable. The release surface needs actionable,
Riko-owned exceptions rather than bare `ValueError`/`RuntimeError`/deep dependency errors.

At minimum this includes the module/config/lifecycle/pubsub hierarchy plus the finalized identity
and state families (`IdentityError`/`StateKeyError`, `CheckpointConflictError`, and state codec
errors). Error messages carry the offending value or key and enough context to correct the problem
without exposing secret material.

## 6. Optional-dependency UX

Calling something that needs an extra must produce an actionable message, never a deep
`ModuleNotFoundError` or a `backend == "empty"` puzzle:

```text
Async support is not installed.
Install it with: pip install "riko[async]"
```

Same principle for optional parser/frame/finance/connector dependencies.

## 7. Release & package fidelity

- **Built-wheel smoke gate** (not just editable-install testing). Before publish: `uv build` →
  `twine check dist/*` → install the **wheel** into a pristine venv → smoke-test `import riko`,
  `py.typed`, bundled data, core CLI (`riko --help`), async support, and one sync + one async
  Pipeline. Publish only that exact tested artifact.
- **CI enforces formatting** — `ruff check` + `ruff format --check`, not an ephemeral `--fix` pass.
- **Public dependency-graph lane** — add a job that ignores workspace/source overrides and tests the
  dependency graph users actually install, plus min-supported and latest-compatible lanes.

## 8. Surface & doc hygiene

- **Shrink `riko.modules.__all__`** to module-author contracts only; keep implementation details
  private.
- **Final discovery matches the target model.** Module discovery exposes `Sources` and `Transforms`;
  endpoint/provider and serialization discovery use `Targets` and `Formats`. The legacy `Sinks` /
  `"sink"` module category does not survive once `output` and `write` leave module space.
- **Resolve doc/spec drift** — one authoritative shipped-behavior document, one roadmap/router,
  gameplan owners for planned contracts, and generated API documentation.
- **Docs teach only public imports.** User-facing examples should teach `Pipeline`, `Context`,
  `Resource`, `Publisher`/`Subscription`, `Targets`/`Formats`, and normal iteration rather than
  private runtime helpers or removed compatibility APIs.

## 9. Pre-public-release triage (the gate)

**Must land:** remaining P9 discoverability/stubs aligned to `Sources`/`Transforms`/`Targets`/`Formats`;
strict configuration validation; the Pipeline/private-execution split and `with_execution(...)`;
P12/stable state+identity errors; unified CLI; wheel/dependency smoke tests; the pub/sub release
contract; and removal of superseded Python surfaces according to §1.1.

**Strongly preferred:** shrink `riko.modules`; finish doc drift cleanup; benchmark the private
sync/async adapters and canonical identity encoder before freezing optimization choices.

**Can wait:** new connector/provider modules, richer orchestration surfaces, additional batch
backends, and performance-only sync-island grouping that does not change semantics.

**Resolved (2026-08):** `SyncPipe`/`AsyncPipe` do not survive as the target definition+cursor model.
Separate immutable `Pipeline` from private one-shot executions now. Forward dependency order and
exit criteria live in [implementation-sequence.md](implementation-sequence.md); P-track history and
file maps remain in [MILESTONES.md](../MILESTONES.md).

### 9.1 Merge gate (`features` → `main`)

The correctness-audit P0 rows gate the merge because they silently alter data/laziness rather than
failing loudly.

R1 and R3 are fixed. **R2 remains open until the Pipeline/private-execution split actually lands.**
Planning or documenting the replacement does not discharge the defect.

| Row | Merge status |
|---|---|
| ~~**R1** `_io.opener`~~ | fixed |
| **R2** `PyPipe.__call__` | **blocks until the replacement lands**; omitted configuration currently erases constructor state, so the new immutable Pipeline must distinguish omitted from explicit `None` and keep one source of truth between definition and execution |
| ~~**R3** `join`~~ | fixed |

After R2, continue the remaining audit in dependency order, including async send/fan-out,
canonicalization/cache correctness, compiler identifiers, gather/reencoder/source edges, and the
remaining parser/date cases. Each repair lands with its matching regression test.

## 10. Relationship to the P-track

- **Sequences, not replaces, the P-track.** Forward implementation dependency order lives in
  [implementation-sequence.md](implementation-sequence.md); phase status remains in
  [PHASE_CHECKLISTS.md](../PHASE_CHECKLISTS.md), and P-track history/file maps remain in
  [MILESTONES.md](../MILESTONES.md).
- P8 and P10 foundations are retained. P9 completion can proceed independently where it does not
  encode removed runtime classes or the removed `Sinks` module category. P11/P12 are reshaped by the
  finalized execution/resource/state contracts rather than implemented from their older phase
  sketches verbatim.
