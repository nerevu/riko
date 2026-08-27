# riko API Surface Manifest (breadth-first, plan only)

Status: **spec**. The three-tier import contract that Phase 1's DoD hinges on —
*"a developer can determine whether an object is stable, extension-facing, or private from its
import path alone."* Breadth-first companion to [PHASE_CHECKLISTS.md](PHASE_CHECKLISTS.md),
and [MILESTONES.md](MILESTONES.md).
Enumerates every public name, its **tier**, its **target import path**, and where it lives
**today** — so the `__all__` blocks write themselves and a moved name churns one row. No code
changed by this document.

Tiers:
- **STABLE** — SemVer-guaranteed. Breaking change ⇒ major bump. Import from `riko` / `riko.api`.
- **EXT** — extension-author contract. SemVer-guaranteed but a smaller audience. Import from
  `riko.ext`.
- **PRIVATE** — no guarantees; may change any release. Underscore module or `_name`.

Grounding note: **nothing currently declares `__all__`** except `riko.modules` (7 names) and
`riko.bado` (async backend). `riko.__init__`, `riko.exceptions`, `riko.collections` export by
accident of definition. Phase 1 makes each tier deliberate.

---

## 1. STABLE — `riko` / `riko.api`

Canonical import: `from riko import SyncPipe`. `riko.api` is the hub; `riko/__init__.py`
re-exports from it. `riko.__all__` == `riko.api.__all__` (exact-set test in
`tests/public/test_imports.py`).

| Name | Kind | Lives today | Target | Phase |
|---|---|---|---|---|
| `SyncPipe` | class | `riko/collections.py` | `riko.api` re-export | P1 |
| `AsyncPipe` | class | `riko/collections.py` | `riko.api` re-export | P1 |
| `SyncCollection` | class | `riko/collections.py` | `riko.api` re-export | P1 |
| `AsyncCollection` | class | `riko/collections.py` | `riko.api` re-export | P1 |
| `Context` | dataclass | `riko/__init__.py` (class) | `riko.context` → re-export | P1/P6 |
| `ExecutionMode` | StrEnum | — (new) | `riko.context` → re-export | P6 |
| `PipeState` | StrEnum | `riko/collections.py` | `riko` / `riko.api` re-export | P5 (export P7) |
| `list_modules` | fn | `riko/modules/__init__.py` | `riko.api` re-export | P1 |
| `list_targets` | fn | `riko/collections.py` | `riko.api` re-export | P1 |
| `export` | fn | `riko/collections.py` | `riko.api` re-export | P1 |
| `RikoError` | exc | — (new) | `riko` / `riko.exceptions` | P12 |
| `UnsupportedModuleError` | exc | `riko/exceptions.py` | `riko` / `riko.exceptions` | P1 (re-home P12) |
| `UnsupportedPipelineError` | exc | `riko/exceptions.py` | `riko` / `riko.exceptions` | P1 |
| `ConfigurationError` | exc | — (new) | `riko.exceptions` | P12 |
| `ModuleExecutionError` | exc | — (new) | `riko.exceptions` | P12 |
| `PipelineStateError` | exc | — (new, P5) | `riko` / `riko.exceptions` / `riko.api` | P5 (hub export P7) |
| `PollTimeoutError` | exc | — (new) | `riko.exceptions` | P12 |
| `PublishError`, `SubscriptionError` | exc | — (new) | `riko.exceptions` | P12 |

**Demoted from accidental-public** (were reachable via `from riko import …`, leave `riko.api`
`__all__`): `Objectify`, `Objconf`, `objectify`, `listize`, `get_path`, `get_abspath`,
`replacer`, `PACKAGE_INFO`. Keep importable from `riko.__init__` for one deprecation cycle
(not in `__all__`); `Objconf` handled specially in §4.

## 2. EXT — `riko.ext`

Canonical import: `from riko.ext import processor, DynamicConf`. Audience: module authors and
integration packages (`riko-microsoft`, `riko-ai`).

| Name | Kind | Lives today | Target | Phase |
|---|---|---|---|---|
| `processor` | decorator | `riko/modules/__init__.py` | `riko.ext` (impl `modules/_decorators.py`) | P1/P3 |
| `operator` | decorator | `riko/modules/__init__.py` | `riko.ext` | P1/P3 |
| `splitter` | decorator | `riko/modules/__init__.py` | `riko.ext` | P1/P3 |
| `ModuleMetadata` | dataclass | `riko/modules/__init__.py` | `riko.ext` | P1 |
| `ModuleType`, `ModuleSubtype` | enum/type | `riko/modules/__init__.py` | `riko.ext` | P1 |
| `DynamicConf` | Objectify subclass/Mapping | `riko.ext.config` | `riko.ext.config` | P2 |
| `get_conf_type` | fn | — (new) | `riko.ext.config` | P2 |
| parser `Protocol`s (`SyncProcessorParser`, `AsyncOperatorParser`, …) | Protocol | `riko/types/general.py` | `riko.ext.protocols` re-export | P1/P7 |
| `register` | fn | — (new) | `riko.ext` (impl `ext/registry.py`) | P8 |
| `ModuleDefinition`, `ModuleRegistry` | class | — (new) | `riko.ext.registry` | P8 |
| `Publisher`, `Subscription` | Protocol | — (new) | `riko.ext.pubsub` | P11 |
| `EventSink`, `RuntimeEvent` | Protocol/type | — (new) | `riko.ext.events` | P12 |

## 3. PRIVATE — underscore modules / names

Never in any `__all__`. Import path signals instability. Enforced by
`test_imports.py::test_no_accidental_internal_exports`.

| Area | Symbols | Home | Phase |
|---|---|---|---|
| AST inference | `_infer_*`, `_gen_members`, `_unwrap_alias`, `_matches_abc`, `_expression_path`, `ReturnInference`, `_gen_operator_return_kinds` | `riko/modules/_inference.py` | P3/P4 |
| preparation | `PreparedModule`, `prepare_parser`, `get_parsers`, `get_casters`, `_dispatch` | `riko/modules/_prepare.py` | P2/P3 |
| assignment | `get_assignment`, `gen_assignments`, `_get_subpipe`, `_gen_subpipe_loop` | `riko/modules/_assignment.py` | P3 |
| metadata derivation | `_derive_subtypes`, `_derive_operator_subtypes`, `_derive_loopable`, `gen_module_catalog`, `SUBTYPES` | `riko/modules/_metadata.py` | P3 |
| wrappers | sync/async exec wrappers, lifecycle hooks | `riko/modules/_wrappers.py` | P3/P5 |
| decorator impl | `Module`, `processor`/`operator`/`splitter` classes | `riko/modules/_decorators.py` | P3 |
| resolution | `PipeResolver`, `PipelineResolver`, `PipelineStore`, stores | `riko/ext/_resolver.py`, `riko/ext/_pipelines.py` | P8 |
| concurrency | executor abstraction, `prefetch`/budget helpers, `async_map_stream` | `riko/concurrency.py`, `riko/bado/streams.py` | P10 |
| pub/sub state | `_registry`, `_receive_queue`, `send`/`receive` impl, `coroutine` | `riko/utils.py`, `riko/resources.py` | P11 |
| pool handles | `_PoolHandle`, `_owns_pool` | `riko/collections.py` | — |
| compiler helpers | `build_pipeline`, `_gen_steps`, `_resolve_module` | `riko/compile.py` | P6/P8 |

## 4. Special-case: `Objconf`

Current: `class Objconf(Objectify)` at `riko/__init__.py:190` — a dynamic Objectify bag with ~45
annotated attrs (the "global list of every possible config attribute" P2 kills).

- **P2 end state**: deleted as a class. Replaced by per-module `<Name>Objconf(DynamicConf)`
  types (in `riko.types.configs`) + `DynamicConf` fallback. `DynamicConf` is the single
  parsed-config base (a named subclass of `Objectify`); the earlier `ParsedConf` marker was
  collapsed away since every config is a dynamic bag and `get_conf_type` tests `DynamicConf`.
- **Codegen**: `riko.types.configs` is **generated** from the nonraw `<Name>Conf` TypedDict
  contracts in `riko.types.modules` by `riko/cli/gen_config.py` (the `gen-config` command).
  Edit a contract, run `gen-config`; the structural drift test `tests/internal/test_gen_config.py`
  fails if the two layers diverge. Never hand-edit `configs.py`.
- **Shim**: `def Objconf(values, *a, **k) -> DynamicConf` deprecated factory in
  `riko.ext.config`, emitting `DeprecationWarning`. **Not** re-exported from `riko.__all__`
  (was never intended public; kept importable from `riko.ext.config` only during the window).
- **Access model**: `DynamicConf` supports both attribute (`conf.wait`) and mapping
  (`conf["wait"]`) access — `riko.ext`-only. Built-in modules use their typed `<Name>Conf`.

## 5. Sub-namespace `__all__` targets

| Module | `__all__` today | Target `__all__` | Phase |
|---|---|---|---|
| `riko` | *(none)* | STABLE set (§1) | P1 |
| `riko.api` | *(new)* | == `riko.__all__` | P1 |
| `riko.exceptions` | *(none)* | full `RikoError` tree (§1) | P1/P12 |
| `riko.context` | *(new)* | `Context`, `ExecutionMode` | P1/P6 |
| `riko.ext` | *(new)* | EXT set (§2) | P1 (grows P8/P11/P12) |
| `riko.modules` | 7 names | module-dev surface only (`processor/operator/splitter`, `list_modules`, `ModuleMetadata`, `ModuleType`, `ModuleSubtype`) | P3 |
| `riko.collections` | *(none)* | pipe/collection classes + `export`/`list_targets`; internals stay bare | P1 |
| `riko.bado` | async backend set | unchanged (M1) → reconcile w/ AnyIO | P7 |

## 6. DoD checks (map to tests)

- Every STABLE name importable from `riko` **and** `riko.api`; sets equal —
  `test_imports.py::test_stable_all_matches_api`, `::test_stable_all_is_expected_set`,
  `::test_stable_names_importable`.
- Every EXT name importable from `riko.ext`; no STABLE-only name leaks into `riko.ext` and vice
  versa — `test_imports.py::test_extension_all_is_expected_set`,
  `::test_extension_names_importable`, `::test_stable_and_extension_are_disjoint`.
- No PRIVATE symbol in any `__all__` — `test_imports.py::test_no_private_names_in_public_all`,
  `::test_no_accidental_internal_exports`, `::test_no_leaked_public_functions`. Resolution
  internals additionally have no public import path —
  `::test_resolution_internals_have_no_public_path`. A Pyright-based check that flags
  underscore-module imports from user code is still planned.
- Moved names (`Context`, decorators, `ModuleMetadata`) importable from **both** old and new
  paths during the window — `test_imports.py::test_context_shim_is_same_object`.

## Churn-isolation note

Rows are shallow and keyed by symbol. If a name's target tier or module changes (e.g.
`list_targets` moves under `riko.ext`, or `DynamicConf` becomes STABLE), only that **one row**
changes — the tier definitions, `__all__` targets, and DoD checks stay valid.
