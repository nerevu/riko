# riko

Python stream processing engine modeled after Yahoo! Pipes.

This file is the router: purpose, a short key-path table, the API tiers, the
cross-cutting invariants, the coding style, and the project quirks. Long-form
detail lives in `_docs/`:

- `_docs/KEY_PATHS.md` — per-file detail + the file-local "don't-revert" invariants
- `_docs/INTERNALS.md` — codegen rules, discovery/export surfaces, tooling gotchas
- `_docs/DOCUMENTATION_STANDARD.md` — **read before writing docstrings/doctests**
- `_docs/PHASE_CHECKLISTS.md` — live status (start here); `_docs/ROADMAP.md` — authority/router index

## Key Paths

One-line roles below; per-file detail and the file-local "don't-revert"
invariants live in `_docs/KEY_PATHS.md`.

| Path | Role |
|---|---|
| `riko/collections.py` | `SyncPipe`/`AsyncPipe`/`SyncCollection`/`AsyncCollection`; `Formats` export enum, `export()`, `list_formats()`; `write`/`sink` verbs |
| `riko/modules/` | individual pipe implementations (`fetch`, `filter`, `hash`, …); `__init__.py` is a **narrow** 9-name dev facade (import everything else from its defining module); internals `_decorators` (processor/operator/splitter + auto-map), `_loop` (explicit `loop`), `_derive` (leaf type derivation), `_names` (**generated** discovery enums, `gen-names`) |
| `riko/bado/` | async backend (AnyIO or empty fallback) — file/URL I/O, async itertools, utilities; **don't** tidy `async_url_open` into `async with` (see KEY_PATHS) |
| `riko/_pubsub/` | pub/sub package (`send`/`receive`/`coroutine`); state via `contextvars` |
| `riko/parsers.py` | sync XML/HTML parsing (`xml2etree`, `LinkParser`, …) |
| `riko/dates.py` + `riko/_date_utils.py` | date helpers; `_date_utils` is the **leaf** half (no `riko` imports outside `types`) |
| `riko/dotdict.py` | `DotDict` — case-insensitive nested dict for pipe items |
| `riko/exceptions.py` | hierarchy rooted at `RikoError` (stable: `RikoError`/`PipelineStateError`/`Unsupported*`) |
| `riko/_api_surface.py` | **private** declaration of the STABLE/EXTENSION/TYPES/PRIVATE import contract |
| `riko/resources.py` | **PRIVATE** immutable `Resource`/`Context` resource contract (external resources only) |
| `riko/targets.py` + `riko/types/_write.py` + `riko/_write_session.py` | **PRIVATE** write stack — declarative model (`WriteMode`/`Formats`/`WriteCapabilities`/`PreparedWrite`), `prepare_write` target validation, lazily-acquired file sessions executing the `write`/`sink` verbs |
| `riko/cli/` | CLI entry points (`compile-pipe`/`convert-dag`/`gen-config`/`gen-names`/`gen-api-surface`/`manage`); `manage.py` only composes commands, with build/lint/docs/test/codegen/release helpers in private sibling modules |
| `riko/types/` | parse-time config types — **generated** `<Name>Objconf` (`gen-config`) + `_module_ids` (`gen-names`); hand-maintained `DynamicConf` base |
| `riko/ext/` | `ModuleName`/`normalize_module_name`/`derive_category`/`SINK_NAMES`; codegen helpers + shared `ruff_format` |
| `riko/transform.py` | column transformation helpers (shelved) |

## Docs Map

| Path | Role |
|---|---|
| `_docs/KEY_PATHS.md` | per-file detail companion to the short key-path router above |
| `_docs/INTERNALS.md` | codegen/discovery/tooling internals (extracted from this file) |
| `_docs/DEPENDENCY_LAYERS.md` | runtime layer model + dependency-boundary rules (types⇏collections, definition⇏execution, `_derive` leaf, ext resolver ⇏ module-scope compile, new runtime ⇏ compat facade) + the `definition/` regrouping sketch |
| `_docs/RUNTIME_CONTRACT.md` | the **stable** runtime contract — only guarantees that ship today (§0 direction, §1 Core, §2 item/stream types, §3 pipe behavior, §6 async/backpressure, §7 timeout, §8 union, §9 run status, §10 delivery, §12 errors, §13 filter, §23 AnyIO). Feature/end-state topics (§4, §5, §11, §14–22, §24, §25) live in gameplans. §-numbers are stable identifiers referenced from code; the full `§0–27` map is `_docs/ROADMAP.md#index` |
| `_docs/IMPLEMENTED.md` | as-built companion + single source for build-completeness; each topic tagged **Implemented**/**Partial** with remaining work linked to its owning doc. Absent ⇒ Planned |
| `_docs/PHASE_CHECKLISTS.md` | **the P-track** — authoritative phase tracker (P1–P14) + per-phase detail and done-phase summaries. Live P-track status lives only here |
| `_docs/MILESTONES.md` | P-track history companion — retained file maps and exit-test references; not the forward implementation sequence or semantic owner |
| `_docs/ROADMAP.md` | routing-only authority index for shipped contracts, active gameplan owners, status/history docs, and the forward implementation sequence |
| `_docs/gameplans/implementation-sequence.md` | authoritative forward implementation dependency order; orders owner contracts but does not redefine them |
| `_docs/gameplans/` | active target/implementation plans only; one semantic owner per concept, indexed by ROADMAP |
| `_docs/research/` | prior-art/rationale/ADR notebooks; context only, never authoritative |
| `_docs/archive/` | superseded historical plans; history only, never authoritative |
| `_docs/DOCUMENTATION_STANDARD.md` | authoritative docstring/doctest/`__init__.py` standard |
| `_docs/API_SURFACE.md` | **spec** — the three-tier import contract (STABLE `riko`, EXTENSION `riko.ext`, PRIVATE); its name lists are **generated** from `riko/_api_surface.py` (`gen-api-surface`) |
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
- **Immutable definition layer** — `Context`/`Resource` definitions are frozen snapshots; derive with `augment`/`with_resource`/`from_*`, never assign to a field or mutate an `inputs`/`resources`/`kwargs` mapping. Immutability is structural, **not** recursive: the arbitrary value a resource references (an external client, factory arg) stays mutable. Run-time state that must change lives in the private execution layer, never back on a definition.
- **Foreign-option guard raises at import** — a decorator handed another decorator's option (`_reject_foreign_opts` in `_decorators.py`) raises `TypeError`; it's a decoration-time author mistake, not a runtime condition.
- **No module-scope compiler import in `riko/ext/`** — the two `riko.runtime.compile` imports are function-local (`noqa: PLC0415`); hoisting either reintroduces the `riko.runtime.collections` import cycle, and no test guards it.
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
- **`manage`** = `riko.cli.manage:manager` click entry point; `manage.py` is the thin command composer and private `_build`/`_lint`/`_docs`/`_test`/`_codegen`/`_release` modules own implementation by reason to change. `run-pipe`, `benchmark`, `compile-pipe`, `convert-dag`, `gen-config`, `gen-names`, `gen-pipelines`, `gen-api-surface` also live in `[project.scripts]`. It **collides with mezmorize's `manage`** — use `python -m riko.cli.manage` if it breaks (`_docs/INTERNALS.md`)
- **Generated files are never hand-edited** — `riko/types/configs.py` (`gen-config`), `riko/modules/_names.py` + `riko/types/_module_ids.py` (`gen-names`), and the name lists in `_docs/API_SURFACE.md` (`gen-api-surface` / `manage codegen -m api`, rendered from `riko/_api_surface.py` between `<!-- api-surface:KEY -->` markers — surrounding prose stays hand-written); byte-drift guards in `tests/internal/`. Details: `_docs/INTERNALS.md` § Codegen. The `tests/pypipelines/pipe_*.py` + `examples/pypipelines/pipe_*.py` compiled pipes are also generated — from sibling `pipelines/pipe_*.json` via `compile-pipe`; regenerate both trees at once with `gen-pipelines` (`manage codegen -m pipes`), drift-guarded by `test_compile.py::test_codegen_matches_expected_file` (tests) + `test_example_pipes.py` (examples). To recreate a JSON for a compiled pipe see `_docs/COMPILING_EXAMPLE_PIPES.md`
- **Docs stay consistent by lint** — `manage lint --docs` guards the `_docs/` model: complete `§0–27` index, active gameplan indexing, version/completion consistency, phase-status ownership, and R-phase `ADD`/`MIGRATE`/`DELETE` closure. Documentation-authority namespaces are also static policy and belong in this linter, not pytest.
- **Don't cite transient scratch docs from stable docs** — the lowercase, **untracked** top-level `_docs/*.md` (`polish.md`, `autopilot.md`, `reddit.md`, `reporting.md`, `scripting.md`) are throwaway scratch; stable docs (UPPERCASE `_docs/*.md` like `INTERNALS.md`/`RUNTIME_CONTRACT.md`/`DEPENDENCY_LAYERS.md`, plus `CLAUDE.md`) must not reference them — inline the idea self-contained so nothing breaks when the scratch doc is deleted. Active `_docs/gameplans/*.md` are committed authoritative plans and ROADMAP-indexed; `_docs/research/` and `_docs/archive/` are committed but non-authoritative and never satisfy active ownership.
- **Module catalog + discovery enums are derived** — `list_modules()`/`describe_module()` read decorator-set metadata via `pkgutil`; `Modules`/`Sources`/`Transforms`/`Sinks` and `Formats` are re-exported from the **stable `riko`** surface (import cycle), not `riko.modules`. `Formats` (serialization/export formats) ≠ `Sinks` (sink pipes). Details: `_docs/INTERNALS.md`
- **`meza` pinned to git**; **`mezmorize`** memoizes `riko/_io.py::get_opener`. Removal of that legacy cache is not assigned to the reconciled RDP roadmap.
