# Gameplan: P8 — Module Registry + Resolution Seam

> **Shipped (P8).** The registry, pipeline store, resolver façade, entry-point discovery, and
> catalog integration are live: an external package adds modules without editing core, and runtime
> pipe resolution no longer imports the compiler. As-built detail:
> [IMPLEMENTED.md — Module registry & pipe resolution](../IMPLEMENTED.md); delivery slices + status:
> [PHASE_CHECKLISTS.md § P8](../PHASE_CHECKLISTS.md). This gameplan keeps the durable design and the
> remaining deltas only.

## Architecture — three layers

- **`ModuleRegistry`** (`riko/ext/registry.py`) — resolves named **module implementations** only.
  `ModuleDefinition` + `register(defn, *, replace=False)` / `resolve(name, interface)` / `names()`.
  Populated from built-ins + entry points + runtime registrations. **Never loads JSON, never invokes
  the compiler.**
- **`PipelineResolver`** (`riko/ext/pipelines.py`) — resolves named **composed pipelines** (`pipe_*`,
  JSON defs, generated py) via an injected `ModuleStore(Protocol).load`, with
  `Directory`/`Package`/`Mapping`/`Composite` stores. Core ships **no `tests.*` reference** — the
  test suite injects its own stores via `conftest.py`.
- **`PipeResolver`** (`riko/ext/resolver.py`) — the single façade.
  Precedence **runtime registration → entry-point → built-in → named pipeline** (`register` needs
  `replace=True` to shadow).

**Lazy-import invariant (load-bearing).** Modules import **on demand**. Built-in population
enumerates *names* (pkgutil / entry-point metadata) but only imports `riko.modules.{name}` when
`resolve(name)` is first called, caching the `ModuleDefinition`. Eagerly importing every module at
registry init would pull heavy optional deps (e.g. `csv2ofx`) and regress startup. Entry-point
modules resolve the same way.

**Interface subtlety.** `PipeResolver.resolve(name, interface)` where
`interface ∈ {"pipe", "async_pipe"}` returns the callable for that interface. `ModuleDefinition`
holds both `sync_pipe`/`async_pipe` wrappers; the façade selects by `interface`. `SyncPipe.__init__`
calls `resolve(self.name, "pipe")`, `AsyncPipe` calls `"async_pipe"`.

## Durable decisions

1. **Registry lifetime — hybrid.** Split by mutability, tracking the pub/sub P11 trajectory:
   - **Built-ins + entry points → global singleton.** Module *definitions* are immutable,
     process-global static facts; two concurrent pipelines sharing them is correct and safe. They
     carry none of the pub/sub cross-pipeline-state hazard, so Context-injecting them everywhere is
     churn with no isolation benefit. Lazy-imported (per the invariant above).
   - **Runtime `register()` shadows → global with `reset()`, Context-scopable later.** The one
     mutable, per-application tier (top precedence). Shipped global with a `reset()` for test
     isolation (the `reset_pubsub()` pattern) — the transitional stage, with a seam to move just this
     tier onto `Context.resources` when a concurrency hazard actually justifies it.
2. **Entry-point group name — `"riko.modules"`.** One narrow group; every entry is unconditionally a
   `ModuleDefinition` (no discriminator branch in `PipeResolver`). Other extension kinds get sibling
   groups later (`riko.stores`, `riko.events`, `riko.converters`) rather than overloading this one.
   This string is a **public contract** the moment an external package declares it.

## Remaining deltas

- **R18 — `pipe_`/`pipe:` prefix collision.** `riko/ext/resolver.py` routes any `pipe_`/`pipe:`
  prefix to the pipeline resolver unconditionally, so a registered **leaf** extension named
  `pipe_transform` can never resolve through `ModuleRegistry`. Either reserve the prefixes at
  registration time or try registered modules first. See
  [extensibility.md §24](extensibility.md#24-module-registry-and-plugins) and
  [correctness-audit **R18**](correctness-audit.md#8-open-defect-register--features-branch-audit).
- **P8.6 — compiler adopts the façade (deferred, low value).** `build_pipeline`/`_gen_steps` still
  resolve sub-pipelines through `compile.resolve_module` (now a one-line delegate to the façade)
  rather than an injected resolver; `pipe_*` resolution overloads the 2nd arg as the pipeline's own
  name, which complicates the swap. The compiler already routes modules through the registry via the
  delegate, so this is cleanup, not a capability gap.
- **CI gate** — a live `pip install -e` of `examples/riko-example-ext/` exercised in CI (proves the
  entry-point seam end-to-end against an installed distribution, not just an in-repo path).
