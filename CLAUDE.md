# riko

Python stream processing engine modeled after Yahoo! Pipes.

## Key Paths

| Path | Role |
|---|---|
| `riko/collections.py` | `SyncPipe`, `AsyncPipe`, `SyncCollection`, `AsyncCollection` |
| `riko/modules/` | individual pipe implementations (`fetch`, `filter`, `hash`, etc.) |
| `riko/modules/__init__.py` | re-exports the module-dev surface (`processor`/`operator`/`splitter`/`Module`, all defined in `modules/_decorators.py`); derived module catalog (`list_modules`) |
| `riko/modules/_decorators.py` | `Module` base + `processor`/`operator`/`splitter` decorators; sync/async wrappers (incl. implicit-looping auto-map over iterator sources) |
| `riko/modules/_loop.py` | loop execution — `_run_loop_sync`/`_run_loop_async`, `loop_embed_sync`/`loop_embed_async`, per-parent `_fold_parent`/`_take`/`_take_first` (see `_docs/PHASE_CHECKLISTS.md` § P7 → "Loop restructure & implicit looping") |
| `riko/parsers.py` | sync XML/HTML parsing (`xml2etree`, `LinkParser`, etc.) |
| `riko/bado/__init__.py` | async backend detection (AnyIO or empty fallback) |
| `riko/bado/io.py` | async file/URL I/O (`async_url_read`, `async_url_open`) |
| `riko/bado/itertools.py` | async itertools: `async_map` + bounded/streaming variants `async_map_stream`/`async_map_ordered_stream`, `async_merge` (bounded arrival-order feed merge), `coop_reduce`/`async_reduce`, `async_iter` |
| `riko/bado/_util.py` | async utilities (`async_sleep`, `defer_to_process`) |
| `riko/_pubsub/` | pub/sub package (`send`/`receive`/`coroutine`, `reset_pubsub`) — state via `contextvars`; `_sync.py`/`_async.py`. (`riko/utils.py`/`helpers.py` are gone — decomposed into `_io`/`_iterutils`/`_serialize`/`_strutils`/`_logging`, graph→`compile.py`, `parse_context`→`context.py`, pub/sub→`_pubsub`.) |
| `riko/exceptions.py` | `UnsupportedModuleError` (unresolved leaf module) / `UnsupportedPipelineError` (unresolved `pipe_*` sub-pipeline) — both raised in `resolve_module` in `compile.py` |
| `riko/dotdict.py` | `DotDict` — case-insensitive nested dict for pipe items (dotted keys = nested paths; see `_docs/gameplans/dotdict-parsing.md` for the data-derived-key footgun) |
| `riko/cli/compile.py` | `compile-pipe` script (`[project.scripts]` name; entry `riko.cli.compile:run`) — JSON pipeline → generated Python module (wraps `compile.compile`) |
| `riko/cli/convert_dag.py` | `convert-dag` script — bare-bones DAG → full JSON pipeline (`convert-dag`) |
| `riko/cli/gen_config.py` | `gen-config` script — regenerates `riko/types/configs.py` from the nonraw `<Name>Conf` TypedDicts in `riko/types/modules.py` (+`ruff format`) |
| `riko/types/configs.py` | generated per-module `<Name>Objconf(DynamicConf)` parse-time config types (edit `modules.py` contracts, run `gen-config` — never hand-edit) |
| `riko/transform.py` | column transformation helpers (shelved; ideas now incorporated into the `_docs/gameplans/`) |
| `docs/DAG_FORMAT.rst` | bare-bones DAG format + `convert-dag`/`compile-pipe` commands |
| `docs/MIGRATION.rst` | **consolidated** user migration guide, two parts: Part 1 = **verified** `legacy` branch → current diffs (examples run on both branches, `# LEGACY`/`# CURRENT`); Part 2 = milestone notes expanded from `CHANGES.rst`. `legacy` branch = ancestor of HEAD (last commit before legacy-removal), NOT a pre-refactor snapshot — both are v0.72.0 (AnyIO, three-tier API, ExecutionMode). Real legacy→current diffs: `Context` describe kwargs ignored, `Objconf` removed, legacy JSON loop/output forms removed, `get_path` into `__all__`. **No Twisted anywhere; `bado` is AnyIO and NOT deprecated.** |
| `docs/CHANGES.rst` | changelog; git tags = milestones (2026 refinement work = `v0.67.0`–`v0.72.0`) |
| `README.rst` + `docs/{FAQ,COOKBOOK,INSTALLATION}.rst` + `CONTRIBUTING.rst` | user-facing docs. House style: wrap riko terms in ``double backticks``; **horizontal simple/grid tables only, never `.. list-table::`**; manual `Index` line with explicit `.. _Label: #github-anchor` targets (not `.. contents::`); `√`/blank in capability matrices. Every `>>>` block is a doctest — validate with `uv run --active --no-sync manage test --no-cov --where <file>` and lint RST with docutils (grid tables/anchors). README keeps both the Huginn/Flink/Spark/Storm comparison **and** a "Choosing riko" grid (Pandas/Polars/Beam/RxPY/itertools/Luigi/Prefect). Content was incorporated from the (untracked, removable) `docs/riko-docs-complete-package/` scaffold. |
| `pyproject.toml` `[project.optional-dependencies]` | extras: `perf` (fastfeedparser, ijson, lxml), `async` (anyio, httpx), `finance` (csv2ofx) |
| `_docs/ROADMAP.md` | **the map (pure index).** ~40 lines: intro + a `## Gameplans` table (the single authoritative index of every gameplan) + a pointer to the P-track. It links out; it holds no contract. |
| `_docs/RUNTIME_CONTRACT.md` | **the bare-bones, stable runtime contract** — only the core guarantees that ship today: §0 direction, §1 Core, §2 item/stream types, §3 pipe behavior, §6 async/backpressure, §7 timeout, §8 union, §9 run status, §10 delivery, §12 errors, §13 filter, §23 AnyIO. Each is a terse current-state guarantee; it changes rarely. **Feature/end-state topics are NOT here** (§4,5,11,14–22,24,25 → gameplans). The §-numbers are stable identifiers referenced across the codebase (incl. `riko/collections.py`); the complete `§0–27` map is `_docs/ROADMAP.md#index`. As-built detail + completeness tags → `_docs/IMPLEMENTED.md`. |
| `_docs/gameplans/` | detailed implementation gameplans — the deep plans extracted from ROADMAP plus the Shelf-derived plans. **Roadmap-extracted (ROADMAP keeps a heading+status stub that links here; `§N`/anchor refs stay valid):** Parts III–V → `highergov-feed.md` (HigherGov critical path HG-0…HG-9 + async Feed), `extensibility.md` (E0–E8); contract section bodies → `callable-stages.md` (§4), `execution-semantics.md` (§5–§8, §11–§13, §16), `rdp-connect.md` (§14, §17–§21, §26). **Others:** `connectors.md`, `cli.md`, `mcp.md`, `orchestration.md`, `database-transforms.md`, `enrichment-modules.md`, `riko-site.md`, `twisted-protocol-servers.md`, etc. **Retired to redirect stubs** (superseded by the P-track — `PHASE_CHECKLISTS.md`/`MILESTONES.md`): `productionizing.md` (its RDP-spec draft → `rdp-connect.md`, schema-drift impl → `highergov-feed.md`) and `repo-refinement.md` (18-item order = P1–P14; extension families §15–18 → topical gameplans). The authoritative gameplan index is the `## Gameplans` table in `_docs/ROADMAP.md` |
| `_docs/IMPLEMENTED.md` | **as-built companion + single source for build-completeness** — everything that ships today (core-contract sections *and* the shipped parts of feature topics like §24 discovery / §25 converters), each tagged **Implemented**/**Partial** with its remaining work linked to the owning doc (contract or gameplan). A topic absent here is Planned. No longer 1:1 with the contract (it also covers shipped features) |
| `_docs/PHASE_CHECKLISTS.md` | **the P-track — authoritative phase tracker + per-phase detail** (start here for status). Progress table (P1–P14), done-phase summaries (what landed/decisions/carryovers), the async pub/sub hub as-built, guiding decisions, and a "landing a phase" update checklist. **Live status (which phases are done / next / suite count) lives only in that tracker — read it there, don't restate here.** Former `REFINEMENT_PLAN.md` folded in here (tracker + decisions); its pending-phase design → `MILESTONES.md`; former `FEATURES_AUDIT.md` (completed P7 pub/sub audit) folded into § P7 — both removed |
| `_docs/MILESTONES.md` | P-track companion — **file maps + exit tests + the M2 (P8–P14) design & sequencing**. M1 (P1–P7) landed record; M2 new/modified files, dependency order, and pending-phase exit tests |
| ~~`_docs/Shelf.md`~~ | removed — its tabled ideas (extra source pipes, protocol/orchestration/DB integrations) are now incorporated into the `_docs/gameplans/` |

## Async Backend

- Backend: `anyio` when the `async` extra (`anyio` + `httpx`) is installed, else `empty` (sync-only). There is **no Twisted** and **no `RIKO_ASYNC_BACKEND` env var** — selection is purely "does `anyio` import?" in `bado/__init__.py` (`backend = "empty" if run is None else "anyio"`)
- improvement roadmap: `_docs/ROADMAP.md`

## Correctness invariants (audit remediation)

Non-obvious decisions from an audit + source review — don't silently revert them. General rule:
**prefer `is None`/`is not None` over truthiness** wherever `0`/`False`/`""` are valid values.
`coroutine` marks pub/sub generator pipelines (`send`/`receive`), **not** async; `return_value` is removed.

- **Immutable modules** — `Module.prepare()` returns a frozen `PreparedModule`; there is no prepare cache, so call-site options never leak across items or concurrent invocations.
- **Pool lifecycle** — `SyncPipe`/`SyncCollection` track `_owns_pool`; borrowed pools are never closed by child stages; both support `close()`/`terminate()` + context managers (`terminate` on exceptional exit).
- **Chaining** — `SyncPipe._chain()` propagates all runtime settings (context, inputs, ordered, chunksize, error_key, on_error, worker_init); `Context` is authoritative for `inputs`.
- **Pub/sub safety** — `close()`/`send()` remove generator + queue atomically and tolerate exhaustion; receive-queue overflow is logged; user `func` only receives kwargs it declares.
- **Timeout** — sync `TimeoutIterator` wraps the upstream read so a blocked read can't overrun the deadline; async `timeout=0` = "no timeout" (matches sync). Full async `anext` cancellation is still `Partial` (ROADMAP §6/§7).
- **XML hardening** — `parsers.XML_PARSER` disables entity resolution, DTD loading, and network access under lxml (XXE guard).
- **HTTP backend (`_io.py`)** — one backend: all `http(s)` URLs go through `requests` + `raise_for_status()`; `Fetch.__init__` degrades on `requests.RequestException`/`URLError`; memoized paths buffer then close `r`; `r.raw.decode_content = True` always (transparent gzip).
- **Compiler JSON path** — `build_pipeline`/`_gen_steps` take a `resolver` (`PipelineResolver`) for sub-pipelines; the terminal `output` node is a passthrough (no `output` module); `gen_modules(embedded=True)` yields only loop submodules; sub-pipelines are called with only their declared kwargs; `_OTHERn` wires aggregate into an `others` list; unresolved leaf modules → `UnsupportedModuleError`, unresolved `pipe_*` → `UnsupportedPipelineError`.
- **None-vs-falsy specifics** — `listize`: only `None`→`[]` (so `listize(0)==[0]`). Typed-sort default (`_iterutils._resolve_default`) preserves falsy defaults (`0`/`False`), not `""`. DotDict nested assignment guards `existing is not None` (falsy scalars keep working); a missing index/key returns the supplied `default`, not `IndexError`/`KeyError` (NB: `{"value": X}` is a type-value sentinel — avoid `value` as a nested key). `modules/filter.py` validates each rule's `op` once at prep, then treats missing operands as `None` and skips the comparison.
- **Cast/date/tz** — `cast()` dispatches by destination type; `cast_datetime("now")` returns a `datetime` (`today`/`tomorrow`/`yesterday` stay dates); `CAST_SWITCH["url"]["default"]` is `""`; `dates.ensure_tzinfo` honors `try_local_tz` for zone-less `struct_time`; date arithmetic via `relativedelta` + call-time `now`.
- **Serialization (`_serialize.py`)** — `repr_cache`: `list`/`tuple` get distinct tags; unhashable args bypass the cache (`_UNSUPPORTED` sentinel) rather than colliding. `fromdict` unwraps a union only when exactly one non-`None` member remains (`T | None`); true unions stay un-narrowed. PEP 604 unions handled.
- **Misc** — multi-key sort applies the first rule as primary; joins don't match on both-missing keys; `Chainable` uses signature binding (not exception retry); async temp-file cleanup in `finally`; `fcntl` guarded for Windows.
- **`async_map`** — preserves legitimate `None` results (`_missing` sentinel); `connections=0`=unlimited; eager materialization is by-design (streaming variants: `async_map_stream`/`async_map_ordered_stream`).

## Coding Style

- No comments unless the logic is genuinely non-obvious
- Single `return` statement per function — no early returns
- Return-based error handling; graceful degradation (no `raise` at call sites)
- Guard optional imports with `try/except`; set a `backend` or flag variable in the `except` block
- `noqa: E302` / `noqa: E704` for overloads — ruff/flake8 conflict on blank lines around them

## Project Quirks

- **uv** - prefix all `uv` commands with `--active` to use the currently active venv vs the default .venv folder
- **Python 3.12+** — `requires-python = ">=3.12"`; use PEP 695 type params (`def f[T](...)`), `X | Y` unions, etc.
- **`meza` pinned to git** — `pyproject.toml` sources meza from `github.com/reubano/meza` at a specific commit; meza owns conversion work (`_docs/RUNTIME_CONTRACT.md` §25)
- **Doctests are tests** — `pytest --doctest-modules` runs all `>>>` blocks in source; keep them passing
- **Codegen regression tests** (`tests/internal/test_compile.py`) — `test_codegen_matches_expected_file` compiles every `tests/pipelines/*.json` with a matching `tests/pypipelines/*.py` and asserts `stringify_pipe` output is byte-identical to the expected file (**all** pairs now round-trip byte-identically — the old `HAND_MAINTAINED` splitter-pipe exclusion is gone); `test_codegen_matches_executor` runs the generated modules; `test_malformed_pipeline_syntax` asserts unknown modules raise `UnsupportedModuleError` and structurally-broken defs raise `KeyError`/`IndexError`. `S102` (exec) is per-file-ignored for `tests/**` (codegen tests exec generated modules).
- **`manage`** = `riko.cli.manage:manager` click entry point; `run-pipe`, `benchmark`, `compile-pipe`, `convert-dag` and `gen-config` also available (`[project.scripts]`)
- **`manage` console-script collision** — `mezmorize` also declares `manage = manage:manager` (its own old CLI: `--cover`/`--cov=mezmorize`, no `--no-cov`). Both write `bin/manage`; whichever installs last wins, so `manage` may resolve to mezmorize's CLI and fail with e.g. `No such option '--no-cov'`. tox sidesteps this by invoking `python -m riko.cli.manage ...` (never the `manage` script); `riko/cli/manage.py` has an `if __name__ == "__main__": manager()` guard for this. Dev `uv run --active manage` works only when riko wins install order — use `python -m riko.cli.manage` if it ever breaks. Root cure = removing mezmorize (§26 M10).
- **`gen-config`** = `riko.cli.gen_config:main` — regenerates `riko/types/configs.py` (the per-module `<Name>Objconf(DynamicConf)` parse-time types) from the nonraw `<Name>Conf` TypedDict contracts in `riko/types/modules.py` (strips `Required`/`NotRequired` + `= default` doc-hints, dereferences forward-refs, rebases `FetchTableConf(CsvConf)` → `FetchTableObjconf(CsvObjconf)`), then runs `ruff format`. Idempotent. `tests/internal/test_gen_config.py` is a structural drift guard (fails if the two layers diverge). Edit the contracts in `modules.py`, never `configs.py` by hand.
- **Bare-bones DAG** — `convert_dag(dag)` in `riko/compile.py` expands a minimal DAG (`modules` + *optional* `[src, tgt]` wire pairs, opaque `conf`) into a full `PipeDef`: chains modules linearly when `wires` is omitted, auto-assigns `sw-{n}` ids when absent, appends the terminal `output` node, and wires every sink to `_OUTPUT`. Type is `PipeDag`/`DagModule` in `riko/types/compile.py`; fixture `tests/dags/pipe_forever.json`; see `docs/DAG_FORMAT.rst`
- **`compile.compile(pipe_def, pipe_name)`** — one-call wrapper over `parse_pipe_def` + `stringify_pipe` (JSON pipe def → Python source); parallels `convert-dag` and backs the `compile-pipe` CLI (`[project.scripts]` name; the CLI is `compile-pipe`, not `compile`). (Shadows the builtin only inside `riko/compile.py`, which doesn't use it.)
- **`mezmorize`** — memoization in `riko/_io.py::get_opener`; the Flask concern is moot (it depends on `cachelib`, not Flask). Optional dependency swap tracked in `_docs/gameplans/rdp-connect.md` §26 Milestone 10
- **`conftest.py` at root and `tests/`** — both reset pub/sub state via `reset_pubsub` (from `riko._pubsub`) in a `contextvars` fixture
- **Parallel pipes** use `listpipe_safe` 5-tuple `(source, pipeline, error_key, on_error, worker_local)`
- **`DotDict` fast paths** — single-segment keys, plain-dict `update`, and non-dotted `_parse_key` all bypass slow paths; see `memory/MEMORY.md` for details
- **`Module.prepare()` is pure** — returns a frozen `PreparedModule`; the earlier `_prepare_key` cache was removed (it dropped call-site options and was unsafe under concurrency)
- **Module catalog is derived, not declared** — `list_modules()`/`list_modules(show_metadata=True)` (in `riko/modules/__init__.py`) discover pipes via `pkgutil` and read `ModuleMetadata` off the decorator-set wrapper attrs (`type`, `subtype`, `supported_subtypes`, `pollable`). Subtype is derived from decorator type + `ftype`/`emit` + return annotation (see `_derive_subtypes`); there are no `__aggregators__`/`__sources__` dunders. `type`/`subtype` filters are mutually exclusive; `primary=True` matches only the default subtype. `list_targets()` (in `collections.py`) lists registered export converters.
