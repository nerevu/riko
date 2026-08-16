# riko Milestones — file maps & exit tests

Consolidates the former `MILESTONE1_FILEMAP/TESTS.md` and `MILESTONE2_FILEMAP/TESTS.md`.
Breadth-first companion to [PHASE_CHECKLISTS.md](PHASE_CHECKLISTS.md) (the P-track tracker +
done-phase summaries). This doc owns the **M2 (P8–P14) design, file maps, sequencing, and exit
tests**.

**Phase status lives in the [PHASE_CHECKLISTS tracker](PHASE_CHECKLISTS.md)** — this doc doesn't
restate it. Here: the M1 record (exit-test tree) and the actionable M2 plan — design, file
inventory, sequencing, and exit tests for the P8–P14 work.

Legend: **NEW** create · **MOD** edit in place · **SHIM** temporary back-compat · **EXT** separate
distribution, not core.

---

## Milestone 1 (Phases 1–7)

Everything the M1 filemap/tests specced shipped. **Where each piece lives** →
[IMPLEMENTED.md](IMPLEMENTED.md) (as-built file locations) and
[PHASE_CHECKLISTS.md](PHASE_CHECKLISTS.md) (per-phase what-landed / decisions / carryovers). The
one artifact unique to this doc — the M1 **exit-test tree** that now exists (all green):
- `tests/public/test_imports.py` (P1 tiers), `test_config_public.py` (P2)
- `tests/internal/test_config_dynamic.py` / `test_preparation.py` (P2/P3), `test_inference.py` (P4),
  `test_assignment.py` (P3)
- `tests/public/test_pipe_lifecycle.py` (P5), `test_context_modes.py` (P6),
  `test_sync_async_parity.py` (P7)
- `tests/typing/{valid,invalid}/` — Pyright gate on the public surface

---

## Milestone 2 (Phases 8–14)

**P8 is the seam** everything plugs into — the `compile._resolve_module` runtime→compiler coupling
still stands; P9/P11/P12/P13/P14 build on it. (P10's bounded-parallelism work — `riko/concurrency.py`
+ async streaming/budget in `riko/bado/itertools.py` — is already in place; see
[PHASE_CHECKLISTS.md](PHASE_CHECKLISTS.md) § P10.) **Which phases are done vs. pending → the
[tracker](PHASE_CHECKLISTS.md).**

### Design & rationale (P8–P14)

Folded in from the retired `REFINEMENT_PLAN.md`.

**P8 — registry + resolution (layer internally, unify externally).** The registry must **not**
absorb `compile.py`'s pipeline-loading — they resolve different things: a `ModuleRegistry` resolves
named *module implementations* (`fetch`, `graph`); a `PipelineResolver` resolves named *composed
pipelines* (`pipe_abc123`, JSON defs, generated py). Today `_resolve_module()` conflates four
concerns (`output` handling, importing `tests.pypipelines.*`, loading `tests/pipelines/*.json`,
importing `riko.modules.*`) and `collections.py` imports that **private compiler** function to
resolve ordinary runtime pipes — a backwards runtime→compiler dependency. Invert it behind three
layers: **`ModuleRegistry`** (module definitions only; built-ins + entry points + runtime
registrations; never loads JSON/invokes the compiler), **`PipelineResolver`** (composed-pipeline
lookup via an injected `PipelineStore(Protocol).load` — `Directory`/`Package`/`Mapping`/`Composite`
— replacing the hardcoded `tests.*` paths), and **`PipeResolver`** (the single façade). Precedence:
**runtime registration → entry-point → built-in → named pipeline** (`register` needs `replace=True`
to shadow). Corrections folded in: keep `output` compiler-local (check `== "output"` before
resolving); don't mutate resolved callables (wrap via `bind_embedded`/`functools.wraps`); drop
`compile_missing` polymorphism; preserve transitive `ModuleNotFoundError` (only convert when the
*requested* module is missing). Order P8.1–P8.11: registry → move discovery out of `compile.py` →
store/resolver → façade → pipes use it → compiler uses it → `output` stays local → drop polymorphism
→ stop mutating callables → preserve transitive import error → keep deprecated `_resolve_module`
forwarding one cycle. **DoD:** an external package adds modules without editing core; runtime pipe
resolution no longer imports the compiler.

**P9 — fluent discoverability.** Keep dynamic `pipe.tokenizer(...)`; add explicit
`pipe.then("tokenizer", ...)`; generate dev-time `.pyi` stubs from the registry; add
`list_modules()`, `describe_module(name)`, `__dir__`, and did-you-mean suggestions. **DoD:**
IDE/Pyright see built-in fluent methods without losing runtime extensibility.

**P11 — pub/sub + poll protocols.** `Publisher`/`Subscription` protocols over the current
[async pub/sub hub](PHASE_CHECKLISTS.md#async-pubsub-hub-as-built); `.poll` with
`interval`/`event`/`hybrid` (hybrid recommended); resources in `Context.resources` with a global
compat adapter initially. **DoD:** one poll operator works across in-process, Service Bus, Event
Grid, Redis, webhook.

**P12 — stable errors + observability.** `RikoError` tree (`ConfigurationError`,
`ModuleDefinitionError`, `ModuleExecutionError`, `UnsupportedModuleError(ModuleDefinitionError,
ImportError)`, `PipelineStateError`, `PollTimeoutError`, `PublishError`, `SubscriptionError`);
`ModuleExecutionError` preserves module/pipe/correlation-id/original; `EventSink` protocol +
`RuntimeEvent`s. **DoD:** integrations get diagnostics without printing or a vendor telemetry dep.

**P13 — public/typing/internal test split.** `tests/public/`, `tests/typing/{valid,invalid}/`,
`tests/internal/`; pin exact public imports; assert no accidental internal exports. **DoD:** public
API compat evaluated independently of refactors.

**P14 — extensions outside core.** Only after P8/P11/P12. Core provides registration, typed parsed
config, execution, polling, pub/sub protocols, retry, context/resources, events; **no core change
per integration**.

### New files (core)

| File | Phase | Symbols / purpose |
|---|---|---|
| `riko/ext/registry.py` | P8 | `ModuleDefinition`, `ModuleRegistry` (`register(def,*,replace=False)`, `resolve(name, interface)`, `names()`); built-in + entry-point + runtime population |
| `riko/ext/resolver.py` | P8 | `PipeResolver` façade — the single resolution entry point |
| `riko/ext/pipelines.py` | P8 | `PipelineResolver`, `PipelineStore(Protocol)` + `Directory/Package/Mapping/Composite` stores (replaces hardcoded `tests.pypipelines` / `tests/pipelines`) |
| `riko/ext/stubs.py` + `riko/modules/__init__.pyi` | P9 | generated `.pyi` fluent stubs from the registry |
| `riko/ext/pubsub.py` | P11 | `Publisher`/`Subscription` protocols + in-process impl over today's `send`/`receive` |
| `riko/modules/poll.py` | P11 | `poll` operator (`interval`/`event`/`hybrid`, hybrid default) over a `Subscription` |
| `riko/ext/events.py` | P12 | `EventSink` protocol, `RuntimeEvent` (+ kinds), no-op default sink |
| `riko/resources.py` | P11/P12 | `Context.resources` container (broker/subscription/connection handles) + global compat adapter |
| `riko/concurrency.py`, async streaming in `bado/itertools.py` | **P10** | landed — sync `executor`, async bounded/ordered streaming, shared-budget foundation |

### Modified-in-place (core)

- `riko/exceptions.py` (P12) — `RikoError` base; re-home `UnsupportedModuleError` under
  `ModuleDefinitionError(RikoError, ImportError)`; add `ConfigurationError`,
  `ModuleExecutionError` (carries module/pipe/correlation-id/original), `PollTimeoutError(TimeoutError)`,
  `PublishError`, `SubscriptionError`; `PipelineStateError` already exists (P5).
- `riko/compile.py` (P8) — replace `_resolve_module` internals with `PipeResolver`; keep `output`
  local; drop `compile_missing` polymorphism; stop mutating `pipeline.__name__` (use `bind_embedded`);
  preserve transitive `ModuleNotFoundError`; SHIM-forward `_resolve_module` one cycle.
- `riko/collections.py` (P8/P12) — use `PipeResolver` (stop importing the compiler private); wrap
  per-pipe failures in `ModuleExecutionError` + emit `pipe.*` events.
- `riko/context.py` (P11/P12) — add `resources` + `events`/`event_sink` fields.
- pub/sub (`riko/_pubsub/`, `modules/{receive,send}.py`) (P11) — re-express over
  `Publisher`/`Subscription`; keep the global compat adapter + conftest resets.
- module catalog (`modules/__init__.py` / `_metadata.py`) (P8) — `list_modules`/`gen_module_catalog`
  read from `ModuleRegistry` instead of pkgutil-only discovery.
- `pyproject.toml` — `[project.entry-points."riko.modules"]` (P8), package `*.pyi` (P9),
  `[tool.pyright]` + typing CI (P13), P14 extra naming.
- `riko/api.py` / `riko/ext/__init__.py` — export the new stable/EXT surface (`ModuleRegistry`,
  `register`, `Publisher`, `Subscription`, `EventSink`, the new exception tree); keep `__all__` deliberate.

### External distributions (P14 — not in core)

| Package | Contents (EXT) |
|---|---|
| `riko-microsoft` | `graph`/`arm`/`powershell` modules; auth; Service Bus / Event Grid `Subscription` impls; desired-state tools |
| `riko-ai` | `infer` provider modules; tools; agent loop; embedding/retrieval adapters |

Core provides only registration, typed parsed config, execution, polling, pub/sub protocols, retry,
context/resources, events. **No core change per integration** is the DoD.

### Sequencing (dependency order)

1. **P8 first** — the resolution seam (`PipeResolver`/`ModuleRegistry`); removes the runtime→compiler
   dependency P10/P11 would otherwise inherit.
2. **P12 early-ish** — the `RikoError` tree + `EventSink` are cross-cutting; land them before P10/P11
   raise/emit the stable types (avoids a later sweep). `PipelineStateError` already exists.
3. **P10 / P11** — largely independent, both on the AnyIO runtime. P11 needs `Context.resources`
   (small) and touches pub/sub.
4. **P9** after P8 (stubs are generated from the registry).
5. **P13 continuous** — formalize the test split; the typing job gates the public surface.
6. **P14 last + external** — only after P8 (entry points) + P11 (pub/sub) + P12 (errors/events). No
   core edit per package.

### Exit tests (pending phases)

- **P8** — `internal/test_resolver.py` (precedence runtime → entry-point → built-in → pipeline; runtime
  lookup imports no compiler; transitive `ModuleNotFoundError` preserved; genuinely-absent →
  `UnsupportedModuleError`), `internal/test_pipeline_store.py` (Directory/Mapping/Composite; no
  `tests.*` paths in `riko/`), `public/test_registry.py` (`output` stays compiler-local; resolved
  callables unmutated; raw JSON unchanged), `public/test_module_extension.py` (entry-point module
  resolves + metadata inferred + missing-extra message — **no core edit**).
- **P9** — **P9A landed** across `internal/test_codegen_names.py` (codegen/taxonomy/drift),
  `public/test_collections.py` (`TestModuleNameEnum`/`TestExportTargets`), `public/test_modules.py`
  (`list_modules` filters), `public/test_imports.py` (surface exports) — the standalone
  `test_fluent_discovery.py` was dropped as redundant. **Remaining (non-P9A):** `describe_module`
  edges, `__dir__`/did-you-mean, generated-stub typing.
- **P10** — `public/test_parallel.py`, `public/test_backpressure.py`,
  `internal/test_concurrency.py`, `internal/test_streams.py`.
- **P11** — `public/test_pubsub_protocols.py` (protocol conformance; resources hold subscriptions;
  global compat adapter; idempotent close), `public/test_poll.py` (interval/event/hybrid;
  `PollTimeoutError`; adapter-agnostic over a fake `Subscription`).
- **P12** — `public/test_errors.py` (hierarchy + back-compat bases; `ModuleExecutionError` context),
  `public/test_events.py` (lifecycle/pipe/poll/publish events; no-op default sink).
- **P13** — `public/test_imports.py` (extended public/EXT `__all__`; no accidental internal exports),
  `tests/typing/`.

**M2 exit** = all of the above green **plus** the M1 suite unregressed, `pyright` clean on the public
surface, and one **external example extension** proving P8/P14 end-to-end.
