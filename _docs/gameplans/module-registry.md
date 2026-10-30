# Module registry & resolution seam gameplan

> **Shipped (P8).** The registry, pipeline store, resolver façade, entry-point discovery, and
> catalog integration are live: an external package adds modules without editing core, and runtime
> pipe resolution no longer imports the compiler. As-built detail:
> [IMPLEMENTED.md — Module registry & pipe resolution](../IMPLEMENTED.md); delivery slices + status:
> [PHASE_CHECKLISTS.md § P8](../PHASE_CHECKLISTS.md). This gameplan keeps the durable design and the
> remaining deltas only.

## Architecture — three layers

- **`ModuleRegistry`** (`riko/ext/modules.py`) — resolves named **module implementations** only.
  `ModuleDefinition` + `register(defn, *, replace=False)` / `resolve(name, interface)` / `names()`.
  Populated from built-ins + entry points + runtime registrations. **Never loads JSON, never invokes
  the compiler.**
- **`WorkflowResolver`** (`riko/runtime/_workflow_resolver.py`, private per `PRIVATE_RESOLUTION`) — resolves
  **stored workflows** (`pipe_*` workflow modules or `WorkflowDocument`s) via an injected
  `ModuleStore(Protocol).load`, with `Directory`/`Package`/`Mapping`/`Composite` stores. Sources are
  registered through a `register(*, module_store, document_store, replace=False)` / `reset()`
  lifecycle that mirrors `Registry`'s (a per-kind clobber guard: registering a second store of the
  same kind raises unless `replace=True`). Core ships **no `tests.*`
  reference** — the test suite registers its own sources via an autouse `conftest.py` fixture calling
  `register_workflow_store(package=…, directory=…)`. The store classes and `WorkflowResolver` stay
  private; only `register_workflow_store` (primitives) is on `riko.ext`, with `reset_workflow_resolver`
  on `riko.ext.workflows` (re-exported from `riko.ext`).
- **`PipeResolver`** (`riko/runtime/_resolver.py`) — the single façade.
  Precedence **runtime registration → entry-point → built-in → stored workflow** (`register` needs
  `replace=True` to shadow).

**Lazy-import invariant (load-bearing).** Modules import **on demand**. Built-in population
enumerates *names* (pkgutil / entry-point metadata) but only imports `riko.modules.{name}` when
`resolve(name)` is first called, caching the `ModuleDefinition`. Eagerly importing every module at
registry init would pull heavy optional deps (e.g. `csv2ofx`) and regress startup. Entry-point
modules resolve the same way.

**Interface subtlety.** `PipeResolver.resolve(name, interface)` where
`interface ∈ {"pipe", "async_pipe"}` returns the callable for that interface. `ModuleDefinition`
holds both `sync_pipe`/`async_pipe` wrappers; the façade selects by `interface`. `SyncPipe.__init__`
calls `resolve(self.name, "pipe")`, `AsyncPipe` calls `"async_pipe"`. These class-specific calls
are shipped/as-built behavior; the target `Pipeline` compiler/execution resolves the native
implementation for the selected private execution mode and adapts only when that side is absent.

## Durable decisions

1. **Registry lifetime — hybrid.** Split by mutability while preserving the target Context/module
   boundary:
   - **Built-ins + entry points → global singleton.** Module *definitions* are immutable,
     process-global static facts; two concurrent pipelines sharing them is correct and safe. They
     carry none of the pub/sub cross-pipeline-state hazard, so Context-injecting them everywhere is
     churn with no isolation benefit. Lazy-imported (per the invariant above).
   - **Runtime `register()` shadows → shipped global with `reset()`; target Context-local shadows
     use the module namespace.** The current mutable per-application tier remains global for
     compatibility/test isolation. The target immutable `Context` provides scoped module overrides
     through `with_module(...)`; child Contexts may shadow parent/default definitions. Module
     definitions never move into `Context.resources`, which is reserved for `Resource` definitions.
2. **Entry-point group name — `"riko.modules"`.** One narrow group; every entry is unconditionally a
   `ModuleDefinition` (no discriminator branch in `PipeResolver`). Other extension kinds get sibling
   groups later (`riko.stores`, `riko.events`, `riko.converters`) rather than overloading this one.
   This string is a **public contract** the moment an external package declares it.

## Remaining deltas

- **R18 — `pipe_`/`pipe:` prefix collision.** `ResolverDispatcher` (`riko/runtime/_resolver.py`) routes any `pipe_`/`pipe:`
  prefix to the workflow resolver unconditionally, so a registered **leaf** extension named
  `pipe_transform` can never resolve through `ModuleRegistry`. Either reserve the prefixes at
  registration time or try registered modules first. See
  [extensibility.md §24](extensibility.md#24-module-registry-and-plugins) and
  [correctness-audit **R18**](correctness-audit.md#8-open-defect-register--features-branch-audit).
- **P8.6 — compiler adopts the façade (moot since v1-cutover step 5, 2026-10-03).** The v1
  compiler's `build_pipeline`/`_gen_steps` resolved sub-pipelines through `compile.resolve_module`
  (a one-line delegate to the façade) rather than an injected resolver until both were deleted;
  plan build now resolves through the façade directly; `pipe_*` resolution overloads the 2nd arg as the pipeline's own
  name, which complicates the swap. The compiler already routes modules through the registry via the
  delegate, so this is cleanup, not a capability gap.
- **CI gate** — a live `pip install -e` of `examples/riko-example-ext/` exercised in CI (proves the
  entry-point seam end-to-end against an installed distribution, not just an in-repo path).

## Open ideas

- **One store kind via a document adapter (2026-10-10, unscheduled).** Today `DirectoryStore.load`
  returns a `Workflow` while the package/mapping/composite stores return a `ResolvedWorkflow`,
  so `WorkflowResolver` keeps two slots (`module_store`, `document_store`), hard-codes module-first
  precedence, and owns the document→module build and its cache (`_load_resolved`,
  `_resolved_documents`, cleared on `register_dispatcher`/`register`/`reset`). The difference is
  deliberate: building a `ResolvedWorkflow` from a graph needs the dispatcher (to look up each node's
  pipe), and the dispatcher already holds the resolver, so a `DirectoryStore` that returned modules
  would close a store → dispatcher → resolver → store cycle; `WorkflowResolver.load_workflow` also
  needs the `Workflow` itself. Option: keep `DirectoryStore` as is and add an adapter `ModuleStore` that wraps
  a `DocumentStore` (`WorkflowStore[Workflow]`) plus the dispatcher and owns the build + cache. Then the resolver holds
  one `ModuleStore` (e.g. `CompositeStore(PackageStore(...), DocumentModuleStore(...))`), precedence
  becomes composite order, and `load_workflow` reads through the wrapped document store. Cost: the
  dispatcher must reach the adapter (late registration, as `register_dispatcher` does today), and cache
  invalidation moves with it.
