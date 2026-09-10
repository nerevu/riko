# riko

Python stream processing engine modeled after Yahoo! Pipes.

This file holds the index plus the cross-cutting correctness invariants. Long-form detail lives in `_docs/`:

- `_docs/INTERNALS.md` — codegen rules, discovery/export surfaces, tooling gotchas
- `_docs/DOCUMENTATION_STANDARD.md` — **read before writing docstrings/doctests**
- `_docs/PHASE_CHECKLISTS.md` — live status (start here); `_docs/ROADMAP.md` — gameplan index

## Key Paths

| Path | Role |
|---|---|
| `riko/collections.py` | `SyncPipe`, `AsyncPipe`, `SyncCollection`, `AsyncCollection`; `Targets` export enum, `export()`, `list_targets()` |
| `riko/modules/` | individual pipe implementations (`fetch`, `filter`, `hash`, etc.) |
| `riko/modules/__init__.py` | **narrow** module-dev facade — `__all__` is exactly 9 names: `processor`/`operator`/`splitter`, `list_modules`/`get_module_metadata`/`describe_module`, `ModuleMetadata`/`ModuleSubtype`/`ModuleType`. Everything else (`PreparedModule`, `parse_and_cast`, `get_casters`, `broadcast`, `objectify`, the `types.general` aliases, …) is **private — import from its defining module** (`from riko.modules._prepare import PreparedModule`), never through this package |
| `riko/modules/_decorators.py` | `Module` base + `processor`/`operator`/`splitter` decorators; sync/async wrappers, incl. implicit-looping auto-map: a processor maps over any non-mapping/non-primitive iterable (`list`/`tuple`/`range`/generator/iterator, gated by `_iterutils.is_listlike`); a mapping/primitive/`None` stays one item so `None` still invokes source pipes |
| `riko/modules/_loop.py` | loop execution — `_run_loop_sync`/`_run_loop_async`, `loop_embed_sync`/`loop_embed_async`, per-parent `_fold_parent`/`_take`/`_take_first`. `LoopRawConf`/`LoopConf` (`count`/`assign`/`field` + compact `embed`) belong to the **explicit** `loop` module — kept, not vestigial, distinct from implicit looping. The legacy nested `conf.embed.value` form is gone |
| `riko/modules/_derive.py` | init-time type/subtype derivation (`derive_loopable`/`derive_subtypes`) — a **leaf** (no `riko.ext` imports) split out of `_metadata` so decorators can pull it during `riko.modules` init |
| `riko/modules/_names.py` | **generated** discovery surface: flat `Modules` + `Sources`/`Transforms`/`Sinks` bucket `StrEnum`s (`Modules.FILTER is Transforms.FILTER`); re-exported from `riko`. Never hand-edit (run `gen-names`) |
| `riko/parsers.py` | sync XML/HTML parsing (`xml2etree`, `LinkParser`, etc.) |
| `riko/dates.py` + `riko/_date_utils.py` | date helpers. `_date_utils` is the **leaf** half (`parse_date_string`, `ensure_tzinfo`, `date_to_datetime`, `tt_to_datetime`, `date_to_tt`, tz lookup) — imports nothing from `riko` outside `types`, so `_iterutils` can use it for sort keys without a cycle; `dates.py` keeps the `riko`-aware half (`NOW`/`TODAY`, `get_date`, `tt_to_datedict`) |
| `riko/bado/__init__.py` | async backend detection (AnyIO or empty fallback) |
| `riko/bado/io.py` | async file/URL I/O (`async_url_read`, `async_url_open`, `async_write`, `get_async_temp_file`). `async_write` is the anyio-native counterpart of `meza.io.write` (chunk/mode/encoding parity, no sync fallback); `get_async_temp_file` is a plain `def` returning anyio's `NamedTemporaryFile` CM, so `async with` needs no `await`. `async_url_open` is likewise a plain `def` returning an `_AsyncURLStream` handle that is **both** awaitable (`await async_url_open(url)` → open stream, caller closes) and an async CM (`async with async_url_open(url) as f` → auto-closes on exit). It is **eager-read, lazy-parse** — the full body is buffered via `response.content`/`Path.read_bytes` (no read-time backpressure), only parsing stays lazy. The fetch parsers pair `await async_url_open` with `_io.auto_close` (close-on-iteration); **never** "tidy" them into `async with`, which closes the handle before the returned lazy iterator is read. True `httpx.stream()` body reads + `AsyncClient` reuse are unimplemented (`_docs/IMPLEMENTED.md` §2) |
| `riko/bado/itertools.py` | async itertools: `async_map` + streaming `async_map_stream`/`async_map_ordered_stream`, `async_merge`, `coop_reduce`/`async_reduce`, `async_iter` |
| `riko/bado/_util.py` | async utilities (`async_sleep`, `defer_to_process`) |
| `riko/_pubsub/` | pub/sub package (`send`/`receive`/`coroutine`, `reset_pubsub`) — state via `contextvars`; `_sync.py`/`_async.py`. (`riko/utils.py`/`helpers.py` are gone — decomposed into `_io`/`_iterutils`/`_serialize`/`_strutils`/`_logging`, graph→`compile.py`, `parse_context`→`context.py`, pub/sub→`_pubsub`) |
| `riko/exceptions.py` | hierarchy rooted at `RikoError` (`ModuleError`/`PipelineError`/`PubSubError` bases): `UnsupportedModuleError` (unresolved leaf module) / `UnsupportedPipelineError` (unresolved `pipe_*` sub-pipeline) — both from `resolve_module` in `compile.py`; `PipelineStateError`; pub/sub `ReceiverUnavailableError`/`DuplicateReceiverError`. Only `RikoError`/`PipelineStateError`/`Unsupported*` are stable (`ROOT_EXCEPTIONS` in `riko/_api_surface.py`) — bases + pub/sub errors are not |
| `riko/_api_surface.py` | **private** declaration of the supported import contract — `STABLE` (= `BADO`/`COLLECTIONS`/`COMPILE`/`MODULES`/`OTHER`/`ROOT_EXCEPTIONS`), `EXTENSION`, `TYPES`, `PRIVATE_RESOLUTION` frozensets. Source of truth for `_docs/API_SURFACE.md` + `tests/public/test_imports.py`; not itself public |
| `riko/dotdict.py` | `DotDict` — case-insensitive nested dict for pipe items (dotted keys = nested paths; see `_docs/gameplans/dotdict-parsing.md` for the data-derived-key footgun) |
| `riko/resources.py` | **PRIVATE** thin-slice of the `execution-semantics.md` resource contract (foundation for `monthly-dashboard.md`): immutable generic `Resource[H, C]` (`H`=handle type, `C`=cleanup return; `spec`/`handle` were collapsed since they're the same object — the factory case where they differ is deferred to `from_factory`) — owned via `Resource(handle)`, external via `Resource.from_external(handle)` (a distinct `ExternalResource` subclass that resolves to the handle and never closes, so **external-ness is a type, not a runtime flag**); `credential` ref; sync/async `open`/`aopen` + `close`/`aclose` returning `C | None` (the `cleanup` override's result, else `None` — you **can't overload on the `_cleanup` instance flag**, so it's encoded in the return union). Execution-bound `ResourceView` (`view.db`/`view["db"]`), `normalize_resources`/`coerce_binding`/`ResourcesLike`, and `bind_resources` (resolve a node's declared binding against `Context.resources`). `Context` carries an immutable `resources` mapping + `with_resource()` (populated only via `with_resource`, never the constructor, so `**kwargs` splats can't collide); `__getstate__/__setstate__` keep the `mappingproxy` picklable for the process pool. **Wired into the preparation seam**: a `@processor`/`@operator(resources="x")` decoration is normalized in `Module.prepare` onto `PreparedModule.resources` and delivered to the parser as a `ResourceView` in `kwargs["resources"]`; missing binding raises. **External resources only** — owned-resource lifecycle (open-once/close-at-teardown) + lazy/`from_factory`/rollback still deferred to the Execution layer (owned bindings raise `NotImplementedError`) |
| `riko/sinks.py` | **PRIVATE** sink write-mode contract (core half of `connectors.md`/`monthly-dashboard.md` §5): `SinkMode` (`append`/`merge`/`replace`/`delete`, with `.keyed`/`.destructive` classification), frozen `SinkWrite`, and `sink_write(mode, keys=, idempotency_key=)` validator — keyed modes require `keys` + forbid `idempotency_key`; `append` is the reverse. Shared vocabulary external provider sinks consume (transports live outside core); a **distinct axis** from `write.py`'s file-open `mode`. Consumed by `riko/targets.py`'s `build_write` + the `sink` verb |
| `riko/targets.py` | **PRIVATE** sink target adapters + the `write`/`sink` verb machinery (`monthly-dashboard.md` §5): `SinkTarget` Protocol (`capabilities`/`deliver`/`adeliver`), `SinkCapabilities`/`SinkResult`, built-in `File`, `resolve_target`, `resolve_format` (ext→fmt incl. `jsonl`), `build_write` (capability-aware: a serializing `File` forbids `keys` and builds `SinkWrite` directly, a keyed record store routes through `sink_write`), `file_writer`→`_FileWriter` (streamable `csv`/`jsonl` write per-item, else buffer + flush on `complete()`). Collection verbs in `collections.py`: `sink` (terminal → `SinkResult`, sync+async), `write` (passthrough — **desugars to `subscribe(on_receive=…)`**, sync only; async raises `NotImplementedError`) |
| `riko/cli/` | `compile.py` (`compile-pipe`), `convert_dag.py` (`convert-dag`), `gen_config.py` (`gen-config`), `gen_names.py` (`gen-names`), `manage.py` (`manage`). `compile-pipe` reads stdin when its path is `-`/omitted (pipe name `anonymous`) so it chains off `convert-dag`; `-v` reports deps + bytes to **stderr**, keeping stdout a clean source stream. The legacy `bin/compile` is **gone** — it had been dead since `riko.utils` was decomposed, and its `-p`/`-o`/`-s` options scraped Yahoo! Pipes (retired 2015). Don't resurrect it |
| `riko/types/configs.py` | **fully generated** per-module `<Name>Objconf(DynamicConf)` parse-time types; imports + re-exports `DynamicConf` from `riko/types/base.py` (edit `modules.py` contracts, run `gen-config` — never hand-edit) |
| `riko/types/base.py` | hand-maintained `DynamicConf(Objectify[Any])` base, kept out of generated `configs.py` so it can regenerate safely |
| `riko/types/_module_ids.py` | **generated** `ModuleId` (every built-in id) + `LoopableModuleId` (loopable subset); pure `typing`-only leaf. Never hand-edit (run `gen-names`) |
| `riko/ext/names.py` | `ModuleName(StrEnum)` base + `ModuleNameLike`/`normalize_module_name`; `derive_category`/`SINK_NAMES` |
| `riko/ext/codegen.py` | codegen — `enum_member_name`, `catalog_entries`, `generate_module_names`, plus `ruff_format(str)->str`, the **shared** formatter for all three generators |
| `riko/transform.py` | column transformation helpers (shelved; ideas folded into `_docs/gameplans/`) |

## Docs Map

| Path | Role |
|---|---|
| `_docs/INTERNALS.md` | codegen/discovery/tooling internals (extracted from this file) |
| `_docs/RUNTIME_CONTRACT.md` | the **stable** runtime contract — only guarantees that ship today (§0 direction, §1 Core, §2 item/stream types, §3 pipe behavior, §6 async/backpressure, §7 timeout, §8 union, §9 run status, §10 delivery, §12 errors, §13 filter, §23 AnyIO). Feature/end-state topics (§4, §5, §11, §14–22, §24, §25) live in gameplans. §-numbers are stable identifiers referenced from code; the full `§0–27` map is `_docs/ROADMAP.md#index` |
| `_docs/IMPLEMENTED.md` | as-built companion + single source for build-completeness; each topic tagged **Implemented**/**Partial** with remaining work linked to its owning doc. Absent ⇒ Planned |
| `_docs/PHASE_CHECKLISTS.md` | **the P-track** — authoritative phase tracker (P1–P14) + per-phase detail and done-phase summaries. Live P-track status lives only here |
| `_docs/MILESTONES.md` | P-track history companion — retained file maps and exit-test references; not the forward implementation sequence or semantic owner |
| `_docs/ROADMAP.md` | routing index for shipped contracts, active gameplan owners, P-track status/history, and the forward implementation sequence |
| `_docs/gameplans/implementation-sequence.md` | authoritative forward implementation dependency order; orders owner contracts but does not redefine them |
| `_docs/gameplans/` | detailed target/implementation plans (index = ROADMAP's Gameplans grouped tables). `productionizing.md` and `repo-refinement.md` are retired redirect stubs |
| `_docs/DOCUMENTATION_STANDARD.md` | authoritative docstring/doctest/`__init__.py` standard |
| `_docs/API_SURFACE.md` | **spec** — the three-tier import contract (STABLE `riko`, EXTENSION `riko.ext`, PRIVATE) |
| `docs/CHANGES.rst` | changelog; git tags = milestones (2026 refinement work = `v0.67.0`–`v0.72.0`). Entries are **1–2 lines, no code blocks, no implementation detail** — house style in `_docs/INTERNALS.md` § Tooling |
| `docs/MIGRATION.rst` | consolidated user migration guide: Part 1 = verified `legacy`-branch → current diffs, Part 2 = milestone notes. **No Twisted anywhere; `bado` is AnyIO and NOT deprecated** |
| `docs/DAG_FORMAT.rst` | bare-bones DAG format + `convert-dag`/`compile-pipe` |
| `README.rst`, `docs/{FAQ,COOKBOOK,INSTALLATION}.rst`, `CONTRIBUTING.rst` | user-facing docs (house style → `_docs/INTERNALS.md`) |
| `pyproject.toml` extras | `perf` (fastfeedparser, ijson, lxml), `async` (anyio, httpx), `finance` (csv2ofx) |

## Async Backend

Backend is `anyio` when the `async` extra (`anyio` + `httpx`) is installed, else `empty` (sync-only).
There is **no Twisted** and **no `RIKO_ASYNC_BACKEND` env var** — selection is purely "does `anyio`
import?" in `bado/__init__.py` (`backend = "empty" if run is None else "anyio"`).

## Cross-cutting invariants

Non-obvious decisions that shape code across modules — **don't silently revert them**. General rule:
**prefer `is None`/`is not None` over truthiness** wherever `0`/`False`/`""` are valid values.
`coroutine` marks pub/sub generator pipelines (`send`/`receive`), **not** async; `return_value` is removed.

**A bug fix is recorded by its regression test, not by prose here.** The test is executable, can't drift
from the code, and fails loudly on revert; a doc bullet does none of that. So don't journal fixes in
CLAUDE.md or a sibling doc — write the test (its docstring carries the "don't revert, because X" rationale),
add a `docs/CHANGES.rst` line, done. Only **cross-cutting rules that shape new code** (override a default
across modules) belong in the short list below:

- **`is None` over truthiness** — `0`/`False`/`""` are valid values; absent field ≠ present-`None` (`_MISSING` sentinel, not truthiness). A missing required arg **raises** (`require_arg`); a runtime data condition **degrades** (`logger.warning` + carry on).
- **Immutable prepare** — `Module.prepare()` returns a frozen `PreparedModule` with no cache, so call-site options never leak across items or concurrent invocations.
- **Foreign-option guard raises at import** — a decorator handed another decorator's option (`_reject_foreign_opts` in `_decorators.py`) raises `TypeError`; it's a decoration-time author mistake, not a runtime condition.
- **No module-scope compiler import in `riko/ext/`** — the two `riko.compile` imports are function-local (`noqa: PLC0415`); hoisting either reintroduces the `riko.collections` import cycle, and no test guards it.
- **Pool/pipe lifecycle** — `_owns_pool` gates who closes a pool (borrowed pools stay open); pipes are one-shot; only chaining onto a CLOSED/FAILED pipe raises; `terminate()` on exceptional exit discards buffered/partial output.

## Coding Style

- No comments unless the logic is genuinely non-obvious
- Single `return` statement per function — no early returns
- Return-based error handling; graceful degradation (no `raise` at call sites) for **runtime conditions** (unfetchable url, missing rate, malformed rule): `logger.warning` + carry on, and only when the data contract survives. A **missing required argument** is a call-site programming error and must raise: `require_arg` (`riko/modules/_prepare.py`) → `TypeError: the 'aggregate' pipe requires the 'func' keyword argument`. Each operand argument is an explicit keyword-only parser parameter typed `T | None = None` (optional to Python so Riko owns the error, required to Riko); `require_arg(value, name, pipe)` narrows `T | None` to `T` with no `cast`. Operand args that must raise: `aggregate`/`udf` `func`, `join` `other`, `send` `others`
- Docstrings follow `_docs/DOCUMENTATION_STANDARD.md` (annotations own types, except `pipe`/`async_pipe` which keep type labels + `conf` nesting and use `Yields:`; STABLE/EXTENSION/PRIVATE tiers; third-person-present summaries; module docstrings keep a `Basic usage::` example; an empty `>>>` after the doctest imports and before each `def`; direct-value doctests; no Twisted/Deferred boilerplate). Run `ruff check --fix` after editing docstrings — it normalizes D213/D413
- **New code is fully typed and documented** — every new module/class/function/method/property carries complete annotations (params + return; no implicit `Any`) and a docstring per the standard: module `Basic usage::`, class/dataclass/enum `Attributes:`, and a public-named function's full `Args:`/`Returns:`/`Raises:`/`Yields:` sections (a public-named function in a PRIVATE module is documented as completely as a STABLE one). **Every public function and behavior-bearing class also carries an `Examples:` doctest** — extract the example *from* an existing unit test and delete that now-redundant test rather than duplicating coverage (keep exception/edge/non-deterministic/integration cases as tests). Straightforward dunders and `__init__` are documented via the class docstring; an underscore-prefixed helper may stay bare only when obvious, but once it has a docstring it carries the sections its signature warrants. **The summary names the action/purpose — never lead it with `Returns`/`Yields`, and never restate the `Returns:`/`Yields:` section** (the value description belongs there, not the summary): write `"""Formats the default user agent as name/version."""`, not `"""Returns the default user agent string."""` (`_docs/DOCUMENTATION_STANDARD.md` §"do not lead with Returns/Yields")
- Guard optional imports with `try/except`; set a `backend` or flag variable in the `except` block
- `noqa: E302` / `noqa: E704` for overloads — ruff/flake8 conflict on blank lines around them
- **Prefer type narrowing over `cast`** — reach for `isinstance` narrowing, a typed field, or a small narrowing helper before `cast`; a `cast` only silences the checker, it does not verify. When a value enters untyped (an `opts.get(...)` → `object`, a pickled `state.get(...)`), narrow it once at that boundary and carry the tightened type forward (e.g. `resources.coerce_binding(object) -> ResourcesLike | None` feeds `PreparedModule.resources`, so the parser-wiring sites need no `cast`). **Leave it better typed than you found it** — when editing a file, opportunistically retire existing casts a narrow/typed-field makes unnecessary, but keep the legitimate ones (generic-parser plumbing like `cast(Casted[T, E], …)`, `TypedDict` splats like `cast(Opts, kwargs)`)

## Project Quirks

- **uv** — prefix all `uv` commands with `--active` to use the currently active venv vs the default `.venv` folder
- **Python 3.12+** — `requires-python = ">=3.12"`; use PEP 695 type params (`def f[T](...)`), `X | Y` unions, etc.
- **Doctests are tests** — `pytest --doctest-modules` runs all `>>>` blocks in source; keep them passing. `testpaths` = `tests`/`riko`/`examples`/`README.rst`/`docs`, so `examples/*.py` are import- and doctest-collected too; don't duplicate README doctests into `examples/usage.py`/`demo.py` (their flows are covered by `README.rst` + `tests/functional/test_examples.py`)
- **`manage`** = `riko.cli.manage:manager` click entry point; `run-pipe`, `benchmark`, `compile-pipe`, `convert-dag`, `gen-config`, `gen-names` also in `[project.scripts]`. It **collides with mezmorize's `manage`** — use `python -m riko.cli.manage` if it breaks (`_docs/INTERNALS.md`)
- **Generated files are never hand-edited** — `riko/types/configs.py` (`gen-config`), `riko/modules/_names.py` + `riko/types/_module_ids.py` (`gen-names`); byte-drift guards in `tests/internal/`. Details: `_docs/INTERNALS.md` § Codegen. The `tests/pypipelines/pipe_*.py` + `examples/pypipelines/pipe_*.py` compiled pipes are also generated — from sibling `pipelines/pipe_*.json` via `compile-pipe`; regenerate both trees at once with `gen-pipelines` (`manage codegen -m pipes`), drift-guarded by `test_compile.py::test_codegen_matches_expected_file` (tests) + `test_example_pipes.py` (examples). To recreate a JSON for a compiled pipe see `_docs/COMPILING_EXAMPLE_PIPES.md`
- **Docs stay consistent by test** — `tests/internal/test_docs_consistency.py` guards the `_docs/` model (all hard asserts): complete `§0–27` index, every active gameplan indexed in `ROADMAP.md`, retired gameplans flagged, no completion claim above the `pyproject.toml` version, and no `**Status:**` banners in gameplans (phase status lives only in `PHASE_CHECKLISTS.md` — gameplans use `Current gap:`/`Shipped:`/`Scope:`/`Dependencies:` instead)
- **Module catalog + discovery enums are derived** — `list_modules()`/`describe_module()` read decorator-set metadata via `pkgutil`; `Modules`/`Sources`/`Transforms`/`Sinks` and `Targets` are re-exported from the **stable `riko`** surface (import cycle), not `riko.modules`. `Targets` (export formats) ≠ `Sinks` (sink pipes). Details: `_docs/INTERNALS.md`
- **`meza` pinned to git**; **`mezmorize`** memoizes `riko/_io.py::get_opener`. Removal of that legacy cache is not assigned to the reconciled RDP roadmap.
