# riko Phase Checklists & Tracker (P1–P14)

The **authoritative P-track**: the live phase tracker plus per-phase detail for done phases.
Companion: [MILESTONES.md](MILESTONES.md) (file maps + exit tests + the M2/P8–P14 design and
sequencing). Consolidates the former `P1/P2/P5/P6/P7/P10_CHECKLIST.md` and the former
`REFINEMENT_PLAN.md` (tracker + guiding decisions folded in here; pending-phase design → MILESTONES).

## Progress tracker (authoritative)

Suite: **802 passed** (pyright/ruff clean). Branch: `features` (the user commits).

**Merge gate (`features` → `main`): clear.** R3 (`join` materializing its primary stream)
was the last P0 in the [correctness-audit register](gameplans/correctness-audit.md#8-open-defect-register--features-branch-audit);
R1 is fixed and R2 is folded into the Pipeline/Execution split. Remaining register rows are
P1–P3 and belong to the release gate — next up is R4 (async `send` buffers its whole stream).

| Phase | Status | Notes |
|---|---|---|
| **P1** API boundaries | ✅ done | § P1; `riko/api.py`, `ext/`, `context.py`, `py.typed` |
| **P2** `DynamicConf` (`Objconf` gone) | ✅ done | § P2 |
| **P3** split `modules/__init__.py` | ✅ done | § P3; leaf `_*.py` modules |
| **P4** inference diagnostics | ✅ done | § P4; `ReturnInference` |
| **P5** one-shot lifecycle | ✅ done | § P5; `PipeState` |
| **P6** `ExecutionMode` | ✅ done | § P6 |
| **P7** sync/async parity + true async streaming | ✅ done | § P7. **Carryover:** bounded-memory streaming *export* → design in [gameplans/feed-native-streaming.md](gameplans/feed-native-streaming.md). |
| **P8** module registry + entry points | ✅ done | § P8; `ext/{registry,pipelines,resolver}.py`, `Resolver` protocol, symmetric dispatch |
| **P9** fluent discoverability | ⏳ in progress | **P9A done** (§ P9A): generated flat `Modules` namespace + `Sources`/`Transforms`/`Sinks` bucket tree (`riko/modules/_names.py`), `derive_category` taxonomy, `riko.ext.codegen` + `gen-names` CLI/drift guard, `list_modules`/`describe_module`, value-taking `.pipe`/`\|`. **Remaining (non-P9A):** installed-env aggregate `riko.generated.Modules` + `.pyi` stubs → [gameplans/module-enums.md](gameplans/module-enums.md) |
| **P10** bounded parallelism + backpressure | ✅ done | § P10. **Carryover:** pipe-level budget via `Context` → P14. |
| **P11** pub/sub + poll protocols | ⬜ pending | `Publisher`/`Subscription`/`.poll` |
| **P12** stable errors + events | ⬜ pending | `RikoError` tree, `EventSink` |
| **P13** public/typing/internal test split | ⬜ pending | `tests/typing/`; test-layering audit + fix/remove/consolidate plan → [gameplans/testing.md](gameplans/testing.md) |
| **P14** extensions outside core | ⬜ pending | `riko-microsoft`, `riko-ai` |

**Milestone 1 (P1–P7): complete** (P10 landed early, out of sequence, at the user's request). **P8
landed** (the M2 seam). **P9A is complete** (v0.76.0): the generated `Modules` tree +
`derive_category` taxonomy + `riko.ext.codegen`/`gen-names` + `list_modules`/`describe_module`
(on top of the v0.75.0 prerequisites — value-taking `|`/`.pipe()`, `ModuleName` base, `isasync`
inference). **Concrete next action: the remaining non-P9A P9 work** — the installed-environment
aggregate `riko.generated.Modules` (covering entry-point extensions) and `.pyi` fluent stubs. Full
plan: [gameplans/module-enums.md](gameplans/module-enums.md). Other pending-phase design + file maps
+ exit tests are in [MILESTONES.md](MILESTONES.md).

**Accepted/deferred (documented, not bugs):** sync/async **udf-count divergence under partial
consumption** (eager-concurrent async vs lazy-sequential sync — see the `AsyncPipe` docstring +
§ P7); bare `async for … break` without close emits GC noise. The former `parallel`/`threads` →
`executor` migration is **subsumed by the pre-1.0 clean break** (§ release gate): `parallel`/
`threads` live only on the removed `SyncPipe`/`SyncCollection`, so `executor=` becomes the sole
concurrency vocabulary and `Pipeline.with_config` never grows them — no shim doc.

**Done phases** below carry a full summary (what landed / decisions / carryovers). Guiding &
resolved decisions are at the bottom.

> **Pre-1.0 release gate.** The cross-cutting DX/API-shape polish that *sequences* items across
> P9/P11/P12/P13 (pub/sub 1.0 contract, config-validation strictness, **clean-break**
> Pipeline/Execution split, `Collection`→`Pipeline(source=…)`, `with_config`/`executor=` cleanup,
> wheel/PyPI release fidelity) plus its Must-land/Preferred/Can-wait triage lives in
> [gameplans/release-readiness.md](gameplans/release-readiness.md); its file map · sequence · exit
> tests · DoD live in [MILESTONES.md](MILESTONES.md) § Pipeline/Execution split. Phase *status*
> still lives only in this tracker.

> **Landing a phase → update (single-source-of-truth checklist):** (1) this tracker row +
> suite count; (2) add a done-phase summary section below (migrate the design out of
> [MILESTONES.md](MILESTONES.md), don't copy it); (3) its as-built entry in
> [IMPLEMENTED.md](IMPLEMENTED.md) (+ an `As-built:` pointer in
> [RUNTIME_CONTRACT.md](RUNTIME_CONTRACT.md) if the section is newly shipping); (4) any gameplan
> stub. **Phase status lives only in this tracker; "what ships" only in IMPLEMENTED.md** — no
> other doc carries its own status markers.

---

## P1 — API boundaries

**Delivered.** A three-tier import surface knowable from the path alone — STABLE (`riko`/`riko.api`),
EXT (`riko.ext`), PRIVATE (`_*`). New `riko/api.py` (stable hub), `riko/context.py` (Context home),
`riko/py.typed`, `riko/ext/` (`decorators`/`protocols`/`__init__`). `riko.__all__ == riko.api.__all__`.
`Context` moved to `context.py` behind a top-level re-export shim; demoted utils
(`Objectify`/`objectify`/`listize`/`get_path`/`get_abspath`/`replacer`) stay importable but absent
from `__all__`.

**Decisions.** `riko/__init__.py` binds `Context` (+ `objectify`/`listize`) *before* the bottom
`from riko.api import *` — the only cycle-sensitive ordering. DoD: stability tier inferable from
import path (gated by `tests/public/test_imports.py`). No carryover.

## P2 — Objconf → DynamicConf (`ParsedConf` collapsed away)

**Delivered.** The `Objconf(Objectify)` ~45-attribute type fiction is gone. `DynamicConf(Objectify)`
is the single parsed-config base actually instantiated at runtime — a case-insensitive attribute +
mapping bag (parsers spread/iterate/subscript it, so it stays Mapping-like, **not** a frozen
dataclass). Precise per-module types ship as generated `<Name>Objconf(DynamicConf)` in
`riko/types/configs.py`.

**Decisions (supersede the original spec).**
- The planned frozen `@dataclass ReceiveConf(ParsedConf)` was **incompatible** with Mapping-access
  parsers → **`ParsedConf` was collapsed away**; `DynamicConf` is the base and `get_conf_type` tests it.
- `configs.py` is **generated** by `gen-config` (`riko/cli/gen_config.py`) from the nonraw `<Name>Conf`
  TypedDict contracts in `types/modules.py`; drift-guarded by `tests/internal/test_gen_config.py`.
  Edit the contracts, never `configs.py`.
- `Objconf` survived one release as a deprecated factory → `DynamicConf`, then was **removed entirely**
  in the post-v0.72.0 legacy removal. Import `DynamicConf` from `riko.ext.config`. See MIGRATION.rst /
  CHANGES.rst.

**Carryover:** none. 62 parsers carry precise `<Name>Objconf`; the ~10 `DynamicConf` cases are
conf-less modules or extraction-taking operators (both correct).

## P3 — split `modules/__init__.py`

**Delivered.** The 1807-line package `__init__` decomposed into behavior-preserving leaf modules —
`_decorators.py` (`processor`/`operator`/`splitter`), `_inference.py`, `_prepare.py`,
`_assignment.py`, `_metadata.py`, `_loop.py`; `modules/__init__.py` is now re-exports of the
module-dev surface only.

**Carryover:** none.

## P4 — inference diagnostics

**Delivered.** `ReturnInference(kind, source, reason)` wraps the existing AST/annotation/generator
inference; failures carry an actionable `reason`. No override that can drift from the function.
Tested in `tests/internal/test_inference.py`.

**Carryover:** none.

## P5 — One-shot lifecycle

**Delivered.** A pipe/collection instance is one execution. `PipeState(StrEnum)` =
`NEW/RUNNING/EXHAUSTED/CLOSED/FAILED` + a shared `_Lifecycle` mixin on `PyPipe`/`PyCollection`;
read-only `state`/`closed`/`exhausted`/`failed`; standalone `PipelineStateError` (re-parents under
`RikoError` in P12). Sync silent-empty re-iteration and async silent-restart both removed.

**Decisions (revised during implementation).**
- **Chaining gate revised** from the original "gate on NEW": chaining is allowed while
  `NEW`/`RUNNING`/`EXHAUSTED` (wraps all / leftovers / nothing, like a native iterator); only
  `CLOSED`/`FAILED` raise. `_chain` calls `_require_usable("chain")`.
- **Iteration never raises** — post-exhaustion/close `iter(pipe)` yields `[]` (Python-iterator
  semantics), it does not restart. `PipelineStateError` is reserved for chaining/reconfiguring a
  `CLOSED`/`FAILED` pipe.
- `_begin()` must be the first statement *inside* the `_stream` generator body (fires on first pull).

**Carryover:** none. Sync/async identical — parametrized `tests/public/test_pipe_lifecycle.py`.

## P6 — ExecutionMode

**Delivered.** `Context.mode: ExecutionMode` (`RUN`/`DESCRIBE_INPUTS`/`DESCRIBE_DEPENDENCIES`/
`DESCRIBE`), part of the stable surface. `describe_input`/`describe_dependencies` are read-only
properties derived from `mode`; `compile.py` branches on `mode`; `verbose`/`test`/`submodule`/`inputs`
stay independent fields.

**Decisions.**
- The "both bools independently true/false" state is unrepresentable — `DESCRIBE` is the one combined
  mode (the DoD).
- P6 kept the legacy `describe_input=`/`describe_dependencies=` **construction kwargs** (translated to
  `mode`); those were **removed** in the post-v0.72.0 legacy removal (they now fall through `**kwargs`
  and are ignored; the derived properties stay). See MIGRATION.rst Upgrading from the `legacy` branch.
- `Context` stays a hand-written class (the legacy-kwarg shim fought `@dataclass` sugar).

**Carryover:** none.

## P7 — Sync/async parity + true async streaming

**Delivered (P7.1–P7.6).** Observable sync/async differences are execution mechanics only. Async type
vocabulary (`AsyncStream`/`AsyncItems`/`Feed` in `types/general.py`, surfaced via
`riko.ext.protocols`); `AsyncPipe.source` accepts async-iterable / awaitable / sync-iterable (adapted
via `async_iter`); an incremental `_stream` that shares a single execution through the memoized
`__aiter__` (chaining consumes leftovers, doesn't restart — clears the strict xfail); `AsyncPipe._chain`
parity; async lifecycle (`aclose` + async context manager + `_fail`); async `split`/`export`; the AnyIO
runtime migration (`async_map_stream`); the parity matrix (`tests/public/test_sync_async_parity.py`).

**Runtime decision (settled).** The core runtime is **AnyIO**; **Twisted is dropped as the runtime**
(P7.6 moot — no Twisted remains). Twisted *protocols* stay available to adapter packages via
`asyncioreactor`, never the core loop (ROADMAP §23.1).

**Deferred / accepted (non-blocking).**
- **Streaming (bounded-memory) export** — async `export` drains to a `list` (meza's converters are
  sync). For unbounded streams, bridge a drain task → sync queue rather than porting meza to async.
  The one open P7 carryover.
- **Accepted (not a bug):** sync/async udf-count divergence under *partial* consumption (async is
  eager-concurrent; output under *full* consumption is identical). Documented in the `AsyncPipe` docstring.
- **Accepted async-hygiene caveat:** bare `async for … break` with no close emits GC shutdown noise;
  close via `async with`/`aclose`.

**Landed since the original deferral list.**
- Cancel-scope teardown of streaming pipes (`aclosing` + benign `GeneratorExit`-group unwrap) — a
  supported early close (`async with`/`aclose`) is clean while as-complete delivery is kept.
- Child-level `count="first"` early-exit + close via `_take_first` (`riko/modules/_loop.py`) — yields
  the first result per parent then closes the child iterator in a `finally`; shared by sync + async loops.

### Loop restructure & implicit looping (code-verified)

> Consolidated from the retired `docs/gameplans/implicit-looping.md` and
> `docs/gameplans/loop-restructure.md`. Names below are **code-verified** — where the gameplans
> drifted from what shipped, this section is authoritative.

The lazy async loop is the tail end of a three-phase loop restructure plus a prerequisite "implicit
looping" change. All landed; the loop's public vocabulary is unchanged
(`loop` / `embed` / `field` / `assign` / `emit` / `count`).

**Implicit looping (thread 0 — prerequisite).** A processor wrapper processes one item; fed a stream
it used to take the first and warn — the explicit `loop` was the only thing that mapped a processor
per item, so collapsing a processor-loop to a direct `rename(source)` node corrupted multi-item
streams. Fixed by making a bare processor **auto-map** over an iterator source, exactly
equivalent to looping it:

- Seam is at the **top of the processor wrapper**, before `parse`: `sync_wrapper`/`async_wrapper`
  (`riko/modules/_decorators.py`) test `isinstance(item, Iterator)` and, when true, recurse once per
  source item via `chain.from_iterable(map(_wrapper, item))`. Per-item `count`/`field`/`assign`/`emit`
  fold via the processor's own `process`.
- A single item (`Mapping`/scalar) takes the single-item path; an explicit `loop` calls the wrapper
  with a **single parent**, so loops and implicit looping coexist with **no double-mapping**. Source
  processors (`ftype=NONE`) are unaffected. `parse`'s old `Iterator` "Did you forget to use a loop?"
  branch stays as a harmless fallback guard.
- **Settled:** detection is `Iterator`-only (a materialized `list` is one item); prepare-per-item is
  accepted; async covers **sync-iterator** inputs only. Purely additive.

**Loop restructure — three phases.**
- **Phase 1 — restructure, behavior-neutral.** Loop execution moved out of the generic operator
  decorator into loop-owned `riko/modules/_loop.py`; compact-form schema types (`EmbedRef`,
  `LoopModule`, `CountArg`, a shared `RawModule` base) added as accepted input only. Characterization
  tests pinned the then-wrong global-flatten output first.
- **Phase 2 — full Yahoo per-parent semantics (eager async).** Correct per-parent folding shared by
  the processor and the explicit `loop`, via `_fold_parent`/`_take` in `_loop.py`
  (`_run_loop_sync`, `loop_embed_sync`). No cross-parent flatten before `count`/`assign`; `assign`
  folds onto the **parent**; loop-level `field`/`assign`/`emit` win over embed-level. `count` became a
  first-class top-level kwarg (distinct from a module's own `conf.count`, resolved by location). The
  **compact form is canonical**: `normalize_raw_module` lifts legacy → compact (processor-loop → direct
  node; `pipe:<id>` loop → compact loop), the compiler/runtime consume compact, every
  `tests/pypipelines/*.py` regenerated. A loop embedding a `pipe:` sub-pipeline runs **per parent**
  through the same fold; sub-pipelines are detected by **declared** metadata (`riko/modules/_subpipe.py`:
  `SUBPIPE_TYPE`, `mark_subpipe`, `is_subpipe`) stamped at `resolve_module` + in the codegen templates.
  `_resolve_leaf_modules` fail-fast-resolves every leaf (incl. graph-disconnected) so an unreached
  unsupported module raises at build. Per-parent fold contract:

  | emit | count | child → | output |
  |---|---|---|---|
  | True | first | X,Y | X |
  | True | all | X,Y | X, Y |
  | False, assign=r | first | X,Y | parent+{r:X} |
  | False, assign=r | all | X,Y | parent+{r:X}, parent+{r:Y} (one parent copy per result) |
  | True | — | (none) | nothing |
  | False | — | (none) | parent unchanged, once |

- **Phase 3 — lazy async loop = §P7.3.** `riko/modules/_loop.py` `_run_loop_async` (async generator) +
  `loop_embed_async` run the embed **once per parent sequentially** — no `list(source)`; ordering,
  backpressure, and `count="first"` early-exit fall out of iterating one parent at a time. The async
  operator wrapper calls `loop_embed_async` (no `await`); `AsyncPipe._stream` `async for`s the
  `AsyncIterable` result. Eager `_run_loop_async_eager`/`loop_embed_async_eager` were retired.

  > **Correction (code vs. gameplan).** The retired plan proposed `riko/modules/_loop_async.py` with
  > `_run_loop_async_stream`/`loop_embed_async_stream`; what shipped consolidated into `_loop.py` as
  > `_run_loop_async`/`loop_embed_async`. It also listed child-level `count="first"` close as "not yet"
  > — that landed (§P7.5) via `_take_first`.

**Raw-schema matrix (canonical target).**

| Form | Accepted | Canonical writer |
|---|---|---|
| Legacy nested `conf.embed.value` loop | yes (normalized) | no |
| Ordinary processor (count optional) | yes | yes |
| Processor with top-level `count` | yes | yes |
| Compact loop embedding `pipe:<id>` | yes | yes |
| Direct `pipe:<id>` (whole-stream composition) | yes | yes |
| Direct `pipe:<id>` + top-level `count` | **rejected** (per-parent must be an explicit `loop`) | no |
| `lazy`/`async`/`stream` flags in JSON | **rejected** (execution strategy is engine-chosen) | no |

## P8 — Module registry + resolution seam

**Delivered.** The backwards runtime→compiler resolution coupling is inverted behind three
**compiler-free** layers that share one `resolve(name, interface)` contract
(`riko/types/general.py::Resolver`, an overloaded `Protocol`):

- **`riko/ext/registry.py`** — `ModuleRegistry` (built-ins imported lazily per name; runtime
  `register` + `reset()`; entry points via `[project.entry-points."riko.modules"]`, discovered by
  name lazily; precedence **runtime → entry-point → built-in**) + `ModuleDefinition`
  (`module=` by-convention *or* explicit `sync_pipe`/`async_pipe`; `name` optional, stamped from the
  entry-point key with a mismatch guard).
- **`riko/ext/pipelines.py`** — `PipelineResolver` + an injectable `ModuleStore`
  (`Package`/`Mapping`/`Composite`) and `DirectoryStore`; core ships no locations (conftest injects
  the suite's `tests.pypipelines` / `tests/pipelines`, so no `tests.*` in `riko/`).
- **`riko/ext/resolver.py`** — the `PipeResolver` façade: one symmetric dispatch
  (`pipe*` → pipelines, else registry). `collections` resolves through it; `compile.resolve_module`
  is now a one-line delegate to it (P8.11).

**Decisions/landings.** Registry lifetime = **hybrid** (immutable global built-ins/entry points;
runtime `register` global-with-`reset()`, Context-scopable later). **DoD #2** (runtime resolution
imports no compiler) and **DoD #1** (external module via entry point, no core edit —
`examples/riko-example-ext/`) both met. `compile_missing` polymorphism **dropped** (`resolve_module`
always returns a callable; JSON compile → `load_definition`). Sub-pipelines are marked via a **fresh
wrapper** (the generated module fn is never mutated). Codegen emits a **stable `pipe`/`async_pipe`
entry**, so a sub-pipeline resolves exactly like a built-in — this removed the overloaded `pipe_name`
argument (P8.6). `list_modules` overlays registry (runtime + entry-point) modules. `mark_subpipe`
widened (it only stamps metadata). Speculative `ModuleDefinition` discovery fields
(`provider`/`enum_name`/`category`/`docs_url`) dropped until P9A needs them. Entry-point group name:
`riko.modules`.

**Pipe-authoring ergonomics (landed alongside).** The decorators now **infer `isasync`**
(`_resolve_isasync`) from an `async def` or the conventional `async_pipe` name, so it's rarely passed;
explicit `isasync=True` remains only for the cases the name signal can't type — a sync async-interface
callable not named `async_pipe` (a lambda), or a sync `def async_pipe` handed to
`ModuleDefinition(async_pipe=…)`. A `pipe`-named async function raises `TypeError`; typed `__call__`
overloads make `@operator()` on a coroutine statically async. Also on this branch: `pool_scope`'s
`"stage"` value renamed to `"pipe"` (vs `"pipeline"`). Tests: `tests/internal/test_decorators.py`.

**Carryover:** none. Unblocks **P9A** (the generated flat `Modules` namespace +
`Sources`/`Transforms`/`Sinks` bucket tree reads the registry/catalog). Tests:
`tests/internal/test_resolver.py`.

## P9A — enum + taxonomy discoverability

**Delivered** (v0.76.0). A typed *discovery* layer over the canonical string ids — strings stay
canonical everywhere (JSON, entry points, resolver); every enum member's `.value` **is** the id.

- **Taxonomy (`derive_category`, `riko/ext/names.py`).** Pure/total `category` derivation from
  **data-flow capability only** (never the runtime `type`/`subtype` axis) into
  `ModuleCategory = Literal["source", "transform", "sink"]` (lowercase singular — this is the
  `list_modules(category=…)` filter vocabulary): precedence `override → provider (non-`riko` →
  provider namespace) → `md.name in SINK_NAMES` → `md.subtype == "source"` (≡ `ftype is NONE`) →
  `"transform"`. `SINK_NAMES` = `frozenset({"output", "write"})`. Codegen maps those three strings to
  the plural bucket **enum class names** (`_CATEGORY_CLASS`: `source`→`Sources`, `transform`→
  `Transforms`, `sink`→`Sinks`). **`Sinks` now has one built-in: `write`** (`riko/modules/write.py`, a
  pass-through operator serializing the stream to `conf['url']` via a `Targets` converter); `output`
  stays unmatched (compiler-local passthrough, absent from the pkgutil catalog).
- **Generator (`riko/ext/codegen.py`).** `enum_member_name` (uppercase; `._-/`+ws → `_`; collapse
  repeats; leading-digit → `_`-prefix; `enum_name` override) — **collisions raise `ValueError`** with
  both ids, never silently disambiguate. `generate_module_names` emits leaf `StrEnum`s grouped by
  `category` (+ a flat `Modules` wrapper so `Modules.FETCH is Sources.FETCH` — ids are globally unique,
  so the wrapper needs no category segment), sorted by id, fixed header, no timestamps →
  byte-stable/VCS-checkable. `catalog_entries()` reads built-ins only.
- **Committed surface (`riko/modules/_names.py`).** `Modules`/`Sources`/`Transforms`/`Sinks`
  re-exported from the **stable `riko`/`riko.api`** surface — *not* `riko.modules`, whose `Module`
  already names the decorator base (unflagged collision; see Guiding decisions). Canonical import is
  `riko.modules._names`. `ModuleName` base stays an `riko.ext` symbol.
- **Introspection (`riko/modules/_metadata.py`).** `list_modules(*, type, subtype, category)`
  (runtime truth via `list_modules`; the three axes are lowercase `Literal` strings —
  `ModuleType`/`ModuleSubtype`/`ModuleCategory`, e.g. `category="sink"` — **not** the discovery-tree
  identifier enums, which are a separate axis) + `describe_module` (`ModuleDefinition | None`;
  graceful, no raise). Both on the stable surface.
- **CLI.** `manage codegen` + `gen-names` script (`riko.cli.gen_names:main`), idempotent, parallels
  `gen-config`. Drift guard `test_generated_names_match`.

**Import-cycle note:** `riko.ext` depends on `riko.modules` (`operator`/`processor`/`splitter` +
types), so `riko.modules._names` (→ `riko.ext.names` → `riko.ext.__init__`) can only be imported
*after* `riko.modules` is fully initialized. That, plus the `Module` name collision, is why the
discovery tree is re-exported from the stable surface (late `# noqa: E402` block in `riko/__init__`)
rather than from `riko.modules`.

**Tests:** `tests/internal/test_codegen_names.py` (taxonomy golden, member normalization, collision
diagnostic, byte-stability, drift guard); `TestModuleNameEnum` + `TestExportTargets`
(`tests/public/test_collections.py`, enum≡string resolution via ctor/`|`/`.pipe()`, export targets);
`list_modules` filtering in `tests/public/test_modules.py`; surface-export presence
(`Modules`/`Sources`/`Transforms`/`Sinks`/`describe_module`) in `tests/public/test_imports.py`. (The
separate `test_fluent_discovery.py` was dropped as redundant — its coverage lives in those homes.)
**Carryover:** the non-P9A P9 work — installed-env aggregate `riko.generated.Modules` + `.pyi` stubs.

## P10 — Bounded parallelism + backpressure

**Delivered (P10.1–P10.5).** `AsyncPipe` honors `parallel` with bounded in-flight memory —
`ordered`/`prefetch` kwargs; `_resolve_lazy_source` (never `list(source)`); unordered
`async_map_stream` + ordered `async_map_ordered_stream` (`riko/bado/itertools.py`, in-flight memory
within `limit + buffer`); `AsyncCollection` bounded parallel; a sync `executor` abstraction
(`riko/concurrency.py`: `Executor` = `inline`/`thread`/`process`, `resolve_executor`, `pool_factory`;
the `threads` bool kept as a back-compat shim); and a shared-budget foundation (anyio `Semaphore`
threaded through `async_map*` as opt-in `budget=`, wrapping **leaf** I/O to cap combined concurrency
without multiplication or hold-and-wait deadlock).

**Carryovers.**
- **Pipe-level budget wiring via `Context`** — the `Semaphore` foundation is opt-in; threading one
  budget through `Context` down into the pipe/collection `async_map*` calls is deferred to a concrete
  fetch-heavy nesting site (P14). Core has no deep multiplicative nesting today (pipes/loop/subpipe
  are sequential), so the blow-up is latent.
- **Sync `prefetch` window** — sync uses `chunksize` (pool imap), not a `prefetch` buffer; deferred
  (lower value than the async seam).

(The earlier "child `count="first"` aclose" and the `async_map_stream` early-close wart both **landed**
under P7.5 — see P7 above.)

### Async pub/sub hub (as-built)

> Salvaged from the retired `FEATURES_AUDIT.md` (the "Async Pub/Sub Cleanup" pass, now shipped).
> This is the current implementation P11 will formalize behind `Publisher`/`Subscription`.

Sync and async pub/sub are two hubs under `riko/_pubsub/` (state via `contextvars`;
`reset_pubsub()` resets both for test isolation):

- **`SyncPubSubHub`** (`_sync.py`) — generator-coroutine + `deque` push adapter (PENDING items,
  DONE sentinel, identity tokens, early-close). Sync `send` is log-and-continue on a missing target
  (readiness is async-only).
- **`AsyncPubSubHub`** (`_async.py`) — one lazily created **AnyIO rendezvous channel**
  (`max_buffer_size=0`) per named receiver; `publish`/`subscribe` get-or-create the same slot, so
  concurrent startup converges with no sleep/readiness assumption. **Completion = channel closure**
  (one active publisher per receiver), not a DONE sentinel. Publish to a never-subscribed name is
  bounded by `objconf.max_wait` → `ReceiverUnavailableError`; single active subscriber per slot
  (`DuplicateReceiverError`); slots carry a `generation` + `SubscriptionState`.

Ownership migrates to `Context.resources` (P11) before concurrent independent pipelines share a
process. The eager async receiver (collect batch → `iter`) became an async generator in P7.3.

## Guiding & resolved decisions

Folded in from the retired `REFINEMENT_PLAN.md`. Cross-phase decisions that survived implementation
(per-phase decisions live in each § above):

1. **Return behavior is inferred, never declared** — annotation → generator/async-generator
   detection → narrow AST inference → actionable error. No `kind=` metadata on decorators.
2. **A pipe instance is one-shot** — a single execution, cannot restart (P5).
3. **Post-exhaustion iteration returns `[]`** (Python-iterator semantics); `PipelineStateError` is
   only for chaining/reconfiguring a `CLOSED`/`FAILED` pipe (P5).
4. **Each parser receives its explicit parsed config type**; generic framework code type-erases the
   concrete config/parser pair after preparation (`PreparedModule.invoke`) — it never enumerates
   module configs (P2). `DynamicConf` (`riko.ext`-only) is the legacy fallback; `Objconf` is gone.
5. **Inspection/execution uses `ExecutionMode`**, not boolean-flag combinations (P6).
6. **AnyIO is the native async runtime** — define streaming contracts first, migrate the runtime,
   then implement streaming on AnyIO; Twisted is not the runtime (P7). Runtime and protocols are
   orthogonal (RUNTIME_CONTRACT §23.1).
7. **Layer internally, unify externally** — `ModuleRegistry` (modules) + `PipelineResolver`
   (composed pipelines) behind one `PipeResolver` façade; invert the runtime→compiler dependency
   (P8 — see MILESTONES M2).
8. **Enums are discovery, strings are canonical** — the generated `Modules` tree is a typed layer
   over string ids; `.value` is always the id; serialization emits the string (P9A). The discovery
   `Modules` wrapper is re-exported from the **stable `riko`/`riko.api`** surface, **not**
   `riko.modules` — `riko.modules.Module` already names the decorator base (`_decorators.Module`), a
   collision the gameplan hadn't flagged (resolved by naming the wrapper `Modules`, plural); keeping
   both required the tree to live on the stable surface.
9. **A defect in an API that is being deleted is fixed by the replacement, not twice** — decided
   2026-08-24 for correctness-audit **R2** (`PyPipe.__call__` erasing omitted config). The
   `Pipeline`/`Execution` split removes the class, so the repair is immutable reconfiguration in
   the new API. The price is explicit: the defect stays live until the split lands, so the deferral
   is recorded in the register, the merge gate, and the split's DoD — a deferral that is only
   written in one place turns into a silently shipped bug. Corollary: the replacement must
   distinguish **omitted from explicit `None`** with a sentinel, or it inherits the same defect.

**Backward-compatibility contract (evergreen).** Every phase ships compat shims (moved-name
re-exports, `describe_*` properties, re-homed exceptions keep old bases); raw pipeline JSON must
work unchanged throughout — the `compile.py` path is the compatibility contract.

**Style tension (raise vs. graceful).** "No `raise` at call sites" governs **per-item processing**
(graceful via `error_key`/`on_error`); **lifecycle/definition/config boundaries** may raise stable
typed errors (`PipelineStateError`, the `RikoError` tree). Keep single-`return` bodies and route the
raise through a top guard.
