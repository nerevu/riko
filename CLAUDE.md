# riko

Python stream processing engine modeled after Yahoo! Pipes.

## Key Paths

| Path | Role |
|---|---|
| `riko/collections.py` | `SyncPipe`, `AsyncPipe`, `SyncCollection`, `AsyncCollection` |
| `riko/modules/` | individual pipe implementations (`fetch`, `filter`, `hash`, etc.) |
| `riko/modules/__init__.py` | `@processor` / `@operator` decorators; `Module` singleton |
| `riko/parsers.py` | sync XML/HTML parsing (`xml2etree`, `LinkParser`, etc.) |
| `riko/bado/__init__.py` | async backend detection (Twisted or empty fallback) |
| `riko/bado/io.py` | async file/URL I/O (`async_url_read`, `async_url_open`) |
| `riko/bado/itertools.py` | async itertools (`async_map`, `coop_reduce`, `async_broadcast`) |
| `riko/bado/util.py` | async utilities (`async_sleep`, `defer_to_process`) |
| `riko/bado/mock.py` | `FakeReactor` for tests |
| `riko/utils.py` | sync utilities; pub/sub state via `contextvars` |
| `riko/exceptions.py` | `UnsupportedModuleError` (unresolved leaf module) / `UnsupportedPipelineError` (unresolved `pipe_*` sub-pipeline) — both raised in `_resolve_module` in `compile.py` |
| `riko/dotdict.py` | `DotDict` — case-insensitive nested dict for pipe items (dotted keys = nested paths; see `docs/DOTDICT_FOOTGUN.md` for the data-derived-key footgun) |
| `riko/cli/compile.py` | `compile` script — JSON pipeline → generated Python module (wraps `compile.compile`) |
| `riko/cli/convert_dag.py` | `convert-dag` script — bare-bones DAG → full JSON pipeline (`convert-dag`) |
| `riko/cli/gen_config.py` | `gen-config` script — regenerates `riko/types/configs.py` from the nonraw `<Name>Conf` TypedDicts in `riko/types/modules.py` (+`ruff format`) |
| `riko/types/configs.py` | generated per-module `<Name>Objconf(DynamicConf)` parse-time config types (edit `modules.py` contracts, run `gen-config` — never hand-edit) |
| `riko/transform.py` | column transformation helpers (shelved — see `docs/Shelf.md`) |
| `docs/DAG_FORMAT.md` | bare-bones DAG format + `convert-dag`/`compile` commands |
| `optional-requirements.txt` | Twisted, treq, lxml, speedparser3 |
| `docs/ROADMAP.md` | authoritative roadmap and runtime contract (HigherGov-first critical path + RDP/Connect end state + async Feed) |
| `docs/Shelf.md` | tabled ideas (extra source pipes, protocol/orchestration/DB integrations) not on the critical path |
| `docs/ANYIO_NO_SNIFFIO.md` | manual anyio support guide (without sniffio/Twisted integration) |

## Async Backend

- Default backend: `twisted` (when installed), else `empty` (sync fallback)
- Backend selected via `RIKO_ASYNC_BACKEND` env var: `twisted` | `anyio`
- async/await conversion doc: `docs/ASYNC_AWAIT_CONVERSION.md` (prerequisite for anyio)
- anyio support design doc: `docs/ANYIO_SUPPORT.md`
- improvement roadmap: `docs/ROADMAP.md`
- modernization & optimization guide: `docs/optimize.md`

## Correctness Fixes (audit remediation)
- anyio is the canonical target runtime for new concurrency features — see `docs/ROADMAP.md` §23
- `bado/__init__.py` detects `treq`/`twisted` at import time; no env var override exists yet
- `coroutine` is **not** an async decorator — it marks pub/sub generator pipelines (`send`/`receive`)
- `return_value` has been removed entirely

- **Immutable modules (#2/#3)** — `Module.prepare()` returns a frozen `PreparedModule` (conf/opts/parsers/casters/assign/emit/static_casted); the decorator object holds only immutable config. The old `(module_name, repr(conf))` cache was removed so call-site options never leak across items or concurrent invocations.
- **Pool lifecycle (#7)** — `SyncPipe`/`SyncCollection` track `_owns_pool`; borrowed pools are never closed by child stages. Both expose `close()`/`terminate()` and context-manager support (`terminate` on exceptional exit).
- **Chaining (#8)** — one `SyncPipe._chain()` helper propagates all runtime settings (context, inputs, ordered, chunksize, error_key, on_error, worker_init). `Context` is authoritative for `inputs` (`pipe.inputs is context.inputs`).
- **Pub/sub safety (#11)** — `close()`/`send()` remove generator + queue atomically and tolerate an exhausted generator; receive-queue overflow is logged; user `func` only receives kwargs it declares.
- **Timeout (#15)** — sync `TimeoutIterator` wraps the upstream read (producer thread + `queue.get(timeout=...)`) so a blocked read can't overrun the deadline; async `timeout=0` now means "no timeout" (consistent with sync). Full async `anext` cancellation awaits the anyio migration (4.2).
- **XML hardening (#31)** — `parsers.XML_PARSER` disables entity resolution, DTD loading, and network access under lxml (XXE/entity-expansion guard).
- **Compiler JSON path** — `build_pipeline`/`_gen_steps` accept a `resolver` (`PipelineResolver`) for sub-pipelines (tests resolve from `tests.pypipelines`); the terminal `output` node is a compiler passthrough (its step is its input stream — there is no `output` module); `gen_modules(embedded=True)` now yields only loop submodules (was: every module); sub-pipelines are called with only their declared kwargs; `_OTHERn` wires aggregate into an `others` list; unresolved leaf modules raise `UnsupportedModuleError` and unresolved `pipe_*` sub-pipelines raise `UnsupportedPipelineError` (import failure, or missing/unreadable JSON under `compile_missing`). Still incomplete: fetch URL-list iteration, loop/regex-ref handling (blocks `test_filtered_multiple_sources`, `test_submodule_loop`).
- **Other** — date arithmetic via `relativedelta` + call-time `now` (#16); `cast()` dispatches by destination type (#26); PEP 604 unions in `fromdict` (#27); `repr_cache` bypasses unrepresentable args (#28); `Chainable` uses signature binding, not exception retry (#29); async temp-file cleanup in `finally` (#30); multi-key sort applies first rule as primary (#19); joins don't match on both-missing keys (#20); metadata/README fixes (#32); fcntl guarded for Windows (#18); assorted small defects (#33).

## Coding Style

- No comments unless the logic is genuinely non-obvious
- Single `return` statement per function — no early returns
- Return-based error handling; graceful degradation (no `raise` at call sites)
- Guard optional imports with `try/except`; set a `backend` or flag variable in the `except` block
- `noqa: E302` / `noqa: E704` for overloads — ruff/flake8 conflict on blank lines around them

## Project Quirks

- **Python 3.12+** — `requires-python = ">=3.12"`; use PEP 695 type params (`def f[T](...)`), `X | Y` unions, etc.
- **`meza` pinned to git** — `pyproject.toml` sources meza from `github.com/reubano/meza` at a specific commit; meza owns conversion work (`docs/ROADMAP.md` §25)
- **Doctests are tests** — `pytest --doctest-modules` runs all `>>>` blocks in source; keep them passing
- **Codegen regression tests** (`tests/test_compile.py`) — `test_codegen_matches_expected_file` compiles every `tests/pipelines/*.json` with a matching `tests/pypipelines/*.py` and asserts `stringify_pipe` output is byte-identical to the expected file (hand-maintained splitter pipes `pipe_QMrlL_FS3BGlpwryODY80A`/`pipe_zKJifuNS3BGLRQK_GsevXg` are excluded via `HAND_MAINTAINED`); `test_malformed_pipeline_syntax` asserts unknown modules raise `UnsupportedModuleError` and structurally-broken defs raise `KeyError`/`IndexError`. `S102` (exec) is per-file-ignored for `tests/**` (codegen tests exec generated modules).
- **`manage`** = `riko.cli.manage:manager` click entry point; `runpipe`, `benchmark`, `compile`, `convert-dag` and `gen-config` also available (`[project.scripts]`)
- **`gen-config`** = `riko.cli.gen_config:main` — regenerates `riko/types/configs.py` (the per-module `<Name>Objconf(DynamicConf)` parse-time types) from the nonraw `<Name>Conf` TypedDict contracts in `riko/types/modules.py` (strips `Required`/`NotRequired` + `= default` doc-hints, dereferences forward-refs, rebases `FetchTableConf(CsvConf)` → `FetchTableObjconf(CsvObjconf)`), then runs `ruff format`. Idempotent. `tests/internal/test_gen_config.py` is a structural drift guard (fails if the two layers diverge). Edit the contracts in `modules.py`, never `configs.py` by hand.
- **Bare-bones DAG** — `convert_dag(dag)` in `riko/compile.py` expands a minimal DAG (`modules` + *optional* `[src, tgt]` wire pairs, opaque `conf`) into a full `PipeDef`: chains modules linearly when `wires` is omitted, auto-assigns `sw-{n}` ids when absent, appends the terminal `output` node, and wires every sink to `_OUTPUT`. Type is `PipeDag`/`DagModule` in `riko/types/compile.py`; fixture `tests/dags/pipe_forever.json`; see `docs/DAG_FORMAT.md`
- **`compile.compile(pipe_def, pipe_name)`** — one-call wrapper over `parse_pipe_def` + `stringify_pipe` (JSON pipe def → Python source); parallels `convert-dag` and backs the `compile` CLI. (Shadows the builtin only inside `riko/compile.py`, which doesn't use it.)
- **`mezmorize`** — used for memoization (`utils.py`); Flask dependency slated for removal (`docs/ROADMAP.md` §26 Milestone 10)
- **`conftest.py` at root and `tests/`** — both reset `_registry` and `_receive_queue` via `contextvars` fixture
- **Parallel pipes** use `listpipe_safe` 5-tuple `(source, pipeline, error_key, on_error, worker_local)`
- **`DotDict` fast paths** — single-segment keys, plain-dict `update`, and non-dotted `_parse_key` all bypass slow paths; see `memory/MEMORY.md` for details
- **`Module.prepare()` is pure** — returns a frozen `PreparedModule`; the earlier `_prepare_key` cache was removed (it dropped call-site options and was unsafe under concurrency)
- **Module catalog is derived, not declared** — `list_modules()`/`list_modules(show_metadata=True)` (in `riko/modules/__init__.py`) discover pipes via `pkgutil` and read `ModuleMetadata` off the decorator-set wrapper attrs (`type`, `subtype`, `supported_subtypes`, `pollable`). Subtype is derived from decorator type + `ftype`/`emit` + return annotation (see `_derive_subtypes`); there are no `__aggregators__`/`__sources__` dunders. `type`/`subtype` filters are mutually exclusive; `primary=True` matches only the default subtype. `list_targets()` (in `collections.py`) lists registered export converters.
