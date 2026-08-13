# Gameplan: P8 — Module Registry + Resolution Seam

Scoping for **P8** (the `⏳ next` phase). Translates the M2 design
([MILESTONES.md](../MILESTONES.md) § P8) into concrete, code-grounded tasks. **DoD:** (1) an external
package adds modules without editing core; (2) runtime stage resolution no longer imports the
compiler.

## Current state (verified against the tree)

`resolve_module(module_name, pipe_name, compile_missing=False, file_path=None)` —
`riko/compile.py:751-824` — conflates **four** concerns:
1. **Subpipe python import** — `import_module(f"tests.pypipelines.{module_name}")` for `pipe_*`
   names (`:783`). **Hardcoded `tests.*` path inside `riko/`.**
2. **JSON compile fallback** — `compile_missing=True` reads `ROOT_DIR/"tests"/"pipelines"/{pipe_name}.json`
   (`:790`), returns a `tuple[Pipeline|None, ParsedPipeDef|None]` (the `compile_missing` polymorphism).
3. **Built-in import** — `import_module(f"riko.modules.{module_name}")` (`:803`).
4. **Attribute extraction + subpipe marking** — `getattr(module, pipe_name)` (`:813`; `pipe_name` is
   the **interface** `"pipe"`/`"async_pipe"`, not a file), then `mark_subpipe(...)` (`:818-822`).

Coupling & discovery:
- **Runtime→compiler dep:** `riko/collections.py:135` `from riko.compile import resolve_module`;
  called at `:588` (`SyncPipe.__init__` → `resolve_module(self.name, "pipe")`) and `:1168`
  (`AsyncPipe.__init__` → `"async_pipe"`). This is the backwards dependency P8 inverts.
- **Catalog:** `riko/modules/_metadata.py` is pure `pkgutil` discovery over `_PACKAGE="riko.modules"`
  (`:35,140`): `gen_module_catalog`/`get_module_metadata`/`list_modules`. No registry.
- **No entry points** anywhere (`pyproject.toml`, no `importlib.metadata.entry_points()` use).
- **Exceptions** (`riko/exceptions.py`): `UnsupportedModuleError(ImportError)` (`:7`),
  `UnsupportedPipelineError(ValueError)` (`:13`).
- **Subpipe marking** (`riko/modules/_subpipe.py`): `SUBPIPE_TYPE="pipe"`, `is_subpipe`, `mark_subpipe`
  (mutates the resolved pipeline object's attrs — the "don't mutate callables" target).

Tests that must stay green:
- `tests/internal/test_compile.py` — `test_unresolved_subpipeline_raises` (`pipe_missing` →
  `UnsupportedPipelineError`, both `compile_missing` modes); `test_codegen_matches_expected_file`
  (byte-identical `stringify_pipe`); `test_malformed_pipeline_syntax`.
- `tests/functional/test_basics.py` — `_get_pipeline` uses `resolve_module(pipe, pipe, True,
  file_path=...)` (the `compile_missing` + `tests.pypipelines`/`tests/pipelines` fallback).

## Architecture — three layers (M2, unchanged)

- **`ModuleRegistry`** (`riko/ext/registry.py`) — resolves named **module implementations** only.
  `ModuleDefinition` + `register(defn, *, replace=False)` / `resolve(name, interface)` / `names()`.
  Populated from built-ins + entry points + runtime registrations. **Never loads JSON, never invokes
  the compiler.** Carries the discovery fields already agreed in
  [module-enums.md § P8-Δ1](module-enums.md#phase-p8--registry--resolution-seam-prerequisite)
  (`provider`/`enum_name`/`user_type`/`docs_url`) so P9A is pure read.
- **`PipelineResolver`** (`riko/ext/pipelines.py`) — resolves named **composed pipelines** (`pipe_*`,
  JSON defs, generated py) via an injected `PipelineStore(Protocol).load`, with
  `Directory`/`Package`/`Mapping`/`Composite` stores. **Replaces the hardcoded `tests.*` paths** — the
  test suite injects a `Directory("tests/pipelines")` + `Package("tests.pypipelines")` store; core
  ships no `tests.*` reference.
- **`StageResolver`** (`riko/ext/resolver.py`) — the single façade returning a `ResolvedStage`.
  Precedence **runtime registration → entry-point → built-in → named pipeline** (`register` needs
  `replace=True` to shadow).

**Lazy-import invariant (critical, not in the M2 text):** modules must still import **on demand**.
Built-in population enumerates *names* (pkgutil / entry-point metadata) but only imports
`riko.modules.{name}` when `resolve(name)` is first called, caching the `ModuleDefinition`. Eagerly
importing every module at registry init would pull heavy optional deps (e.g. `csv2ofx` in
`collections`/`modules`) and regress startup. Entry-point modules resolve the same way (import the
declared target lazily).

## Interface subtlety

`StageResolver.resolve(name, interface)` where `interface ∈ {"pipe", "async_pipe"}` returns the
callable for that interface (today `resolve_module`'s 2nd arg). `ModuleDefinition` holds both
`sync`/`async_` wrappers; the façade selects by `interface`. `SyncPipe.__init__` calls
`resolve(self.name, "pipe")`, `AsyncPipe` calls `"async_pipe"`.

## Task order (P8.1–P8.11, code-grounded)

- [ ] **P8.1 `ModuleRegistry` + `ModuleDefinition`** (`riko/ext/registry.py`). Lazy per-name
  built-in population that wraps today's `get_module_metadata` + module import into a
  `ModuleDefinition`; `register`/`resolve`/`names`. **Hybrid lifetime** (see
  [open decisions](#open-decisions)): built-ins/entry points as an immutable global; runtime
  `register()` shadows global-with-`reset()` now, Context-scopable later. Add `reset()` +
  `conftest` wiring alongside the existing `reset_pubsub` fixture.
- [ ] **P8.2 Move built-in discovery out of `compile.py`.** The `riko.modules.{name}` import branch
  (`compile.py:803,813`) becomes `registry.resolve` internals; `_metadata.py` discovery feeds the
  registry's name list.
- [ ] **P8.3 `PipelineStore` + stores + `PipelineResolver`** (`riko/ext/pipelines.py`). Extract the
  `tests.pypipelines` import (`:783`) → `Package` store, the `tests/pipelines/*.json` compile
  (`:790`) → `Directory` store (compile-from-JSON lives **behind the store**, compiler-side).
- [ ] **P8.4 `StageResolver` façade** (`riko/ext/resolver.py`) — precedence + `ResolvedStage`; the
  single entry point.
- [ ] **P8.5 Pipes use the façade.** `collections.py:135,588,1168` → `StageResolver.resolve(name,
  interface)`; drop `from riko.compile import resolve_module`. **This alone satisfies DoD #2.**
- [ ] **P8.6 Compiler uses the façade.** `build_pipeline`/`_gen_steps` (`compile.py:172,854`) take the
  injected resolver for sub-pipelines.
- [ ] **P8.7 Keep `output` compiler-local** — check `== "output"` before resolving (don't route the
  terminal passthrough through the registry).
- [ ] **P8.8 Drop `compile_missing` polymorphism** — the tuple return goes away; JSON compilation is a
  store concern. Update `test_basics.py::_get_pipeline` to build a store instead.
- [ ] **P8.9 Stop mutating resolved callables** — replace `mark_subpipe`'s in-place attr writes with a
  `functools.wraps`/`bind_embedded` wrapper so resolved pipelines aren't mutated (M2 correction).
- [ ] **P8.10 Preserve transitive `ModuleNotFoundError`** — only convert to `UnsupportedModuleError`
  when the *requested* module is genuinely absent; a module that imports a missing dep must surface
  the original `ModuleNotFoundError` (guard on the missing module name, as `compile.py:811` does today).
- [ ] **P8.11 Deprecated forwarding shim** — keep `compile.resolve_module` forwarding to the façade for
  one release (back-compat; `test_compile.py` imports it directly).
- [ ] **Entry points** — add `[project.entry-points."riko.modules"]`; registry enumerates them via
  `importlib.metadata.entry_points(group="riko.modules")`. Catalog (`_metadata.py`) reads the registry.

## Risks / watch-items

- **Lazy import** (above) — the single biggest correctness/perf constraint. Resolve-on-demand + cache.
- **Import cycles** — `collections` → `ext.resolver` must not transitively import `compile` at module
  load. The module `ModuleRegistry` path has no compiler dep; the `PipelineResolver`'s JSON store does
  import the compiler, but that store is only wired on the compiler/pipeline path, not on
  `SyncPipe.__init__`. Verify `ext.resolver` import graph stays compiler-free.
- **Codegen byte-match** — `test_codegen_matches_expected_file` asserts byte-identical output; the
  compiler-side changes (P8.6-P8.9) must not alter `stringify_pipe` output.
- **`_subpipe` marking → wrapping** — P8.9 changes an object-identity behavior; `is_subpipe` checks an
  attr, so the wrapper must carry it. Confirm loop/map detection (`_loop.py`) still sees it.

## Delivery slices (DECIDED — 3 slices, suite green each step)

1. **Modules-only seam — ✅ LANDED.** `riko/ext/registry.py` (`ModuleDefinition`, `ModuleRegistry`
   lazy built-in resolution + runtime `register`/`reset` + transitive-`ModuleNotFoundError` guard),
   `riko/ext/resolver.py` (`StageResolver` + global `stage_resolver`; `pipe_*` delegated to the
   compiler via a **lazy** import), `collections.py` resolves through `stage_resolver` (dropped
   `from riko.compile import resolve_module`). Exported `ModuleDefinition`/`ModuleRegistry`/`register`
   from `riko.ext`. Tests: `tests/internal/test_resolver.py` (9). Suite **667**; pyright/ruff clean.
   **DoD #2 (precise):** the *resolution path* is compiler-free (the seam's only `riko.compile`
   import is the lazy `pipe_*` delegate; resolving a module imports no compiler) and `collections`
   no longer imports the private `resolve_module`. NB: `riko.compile` still loads **package-wide**
   because `riko.api` publicly re-exports compile helpers (v0.74.0) — orthogonal to the seam.
   **Deferred to slice 2 (not P8.2 as sliced):** `compile.resolve_module`'s own module branch still
   duplicates the registry's lazy import — left intact so its transitive-error doctest (which patches
   `riko.compile.import_module`) stays valid; reconciled when the compiler adopts the façade (P8.6).
2. **Pipeline store** — P8.3/P8.6/P8.8/P8.9. Extract `tests.*` into injected stores; compiler uses the
   resolver; drop `compile_missing`; stop mutating callables. Removes hardcoded `tests.*` from `riko/`.
3. **Extensibility** — entry points + `_metadata` reads registry + **one external example extension**
   proving P8/P14 (**DoD #1 done**). This is also what unblocks P9A codegen.

## Exit tests (M2)

- `internal/test_resolver.py` — precedence (runtime→entry-point→built-in→pipeline); runtime lookup
  imports no compiler; transitive `ModuleNotFoundError` preserved; genuinely-absent →
  `UnsupportedModuleError`.
- `internal/test_pipeline_store.py` — Directory/Mapping/Composite; **no `tests.*` paths in `riko/`**.
- `public/test_registry.py` — `output` stays compiler-local; resolved callables unmutated; raw JSON
  unchanged.
- `public/test_module_extension.py` — entry-point module resolves + metadata inferred +
  missing-extra message — **no core edit**.

## Open decisions

1. **Registry lifetime — hybrid (recommended).** Split by mutability, mirroring the pub/sub P11
   trajectory (which migrates ownership to `Context.resources` with a *global compat adapter
   initially*, then drops the global "before concurrent independent pipelines share a process" —
   [MILESTONES.md § P11](../MILESTONES.md), [PHASE_CHECKLISTS.md pub/sub as-built](../PHASE_CHECKLISTS.md)):
   - **Built-ins + entry points → global singleton.** Module *definitions* are immutable, process-
     global static facts (which callable implements `fetch`); two concurrent pipelines sharing them
     is correct and safe. They carry **none** of the pub/sub cross-pipeline-state hazard, so
     Context-injecting them everywhere is churn with no isolation benefit. Lazy-imported (per the
     lazy-import invariant above).
   - **Runtime `register()` shadows → global now + `reset()`, Context-scopable later.** This is the
     one mutable, per-application tier (the top precedence level), and it has the *same* leak hazard
     pub/sub had if two pipelines want different registrations. Ship it global with a `reset()` for
     test isolation (the `reset_pubsub()` pattern) — this matches pub/sub's **transitional** stage,
     not its end-state — and leave a seam to move just this tier onto `Context.resources` when a
     concurrency hazard actually justifies it.

   The alternative — pre-committing to fully `Context`-injected registry state now — buys the P11
   end-state early but threads `Context` through every pipe/compiler construction site before any
   hazard exists; deferred unless you want that end-state up front.
2. **Delivery slicing — DECIDED: 3 slices** (modules → pipelines → extensibility; see
   [Delivery slices](#delivery-slices-decided--3-slices-suite-green-each-step)). DoD #2 lands first
   and standalone; each slice has a suite-green checkpoint; cost is the one-cycle `resolve_module`
   forwarding shim (P8.11).
3. **Entry-point group name — DECIDED: `"riko.modules"`.** One narrow group; every entry is
   unconditionally a `ModuleDefinition` (no discriminator branch in `StageResolver`). Other extension
   kinds get sibling groups later (`riko.stores`, `riko.events`, `riko.converters`) rather than
   overloading this one — matching the layered design (registry ≠ pipeline store ≠ event sink). This
   string is a **public contract** the moment an external package declares it; fixed before
   `riko-microsoft`/`riko-ai` ship.
