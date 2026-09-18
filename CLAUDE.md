# riko

Python stream processing engine modeled after Yahoo! Pipes.

This file is the router: purpose, the current package hierarchy, API tiers,
cross-cutting invariants, coding style, and project quirks. Long-form detail lives
in `_docs/`:

- `_docs/KEY_PATHS.md` — per-package/per-file roles + local "don't-revert" invariants
- `_docs/INTERNALS.md` — codegen, discovery/export surfaces, import tooling, tooling gotchas
- `_docs/DOCUMENTATION_STANDARD.md` — **read before writing docstrings/doctests**
- `_docs/PHASE_CHECKLISTS.md` — live status (start here); `_docs/ROADMAP.md` — authority/router index

## Key Paths

The repository is grouped by dependency responsibility. The enforceable layer DAG
is `_docs/gameplans/dependency-layers.md`; detailed file ownership is
`_docs/KEY_PATHS.md`.

| Path | Role |
|---|---|
| `riko/__init__.py` | stable application facade; implementations live below it |
| `riko/base/` | bottom-layer constants, paths, logging, strings/iterators/date helpers, exceptions, private API declarations |
| `riko/types/` | static contracts: streams/items, configs, options, compiler/pipeline/resource/I/O types, enums/wrappers |
| `riko/coercion/` | casts, `DynamicConf`, **generated** objconf classes, objectification, graph/freeze/normalization helpers |
| `riko/bado/` | stable async backend/iterator API; transport/file I/O is in `riko/io/` |
| `riko/definitions/` | immutable/declarative module, resource, target, and write contracts |
| `riko/io/` | sync/async URL/file I/O, serialization, re-encoding |
| `riko/parsing/` | config parsing, `DotDict`, XML/HTML/document parsing |
| `riko/rss/` | feed discovery, parsing, entry normalization |
| `riko/runtime/` | executable orchestration: collections, compiler, resolver/registry, pipelines, pub/sub, write sessions; `context.py` + `_resources.py` are the explicit execution sublayer |
| `riko/modules/` | built-in pipe implementations; private decorator/preparation/metadata/looping internals; generated discovery names |
| `riko/ext/` | supported extension-author facade + extension codegen/name helpers; shares the `modules` architecture layer |
| `riko/cli/` | CLI commands, private generators, docs checks, and import-contract linters; `manage.py` stays a thin composer |

Important concrete locations:

- collections/export/write verbs: `riko/runtime/collections.py`
- compiler: `riko/runtime/_compile.py` + `_compile_repr.py`
- pub/sub: `riko/runtime/_pubsub/`
- execution context/resources: `riko/runtime/context.py` + `_resources.py`
- declarative write model: `riko/definitions/_write.py` + `_targets.py`
- async I/O: `riko/io/_async.py`
- exceptions/API declarations: `riko/base/exceptions.py` + `_api_surface.py`
- generated config objects: `riko/coercion/_configs.py`
- generated discovery/id files: `riko/modules/_names.py` + `riko/types/_module_ids.py`

## Dependency Direction

The package hierarchy is executable policy. Current layers are:

```text
base < types < {bado | coercion | definitions} < io < parsing < rss
        {bado | definitions} < execution
        {execution | parsing} < runtime
        {rss | runtime} < modules < api < cli
```

`riko.runtime.context` and `riko.runtime._resources` map to `execution`; the rest
of `riko.runtime` maps to `runtime`. `riko.ext` and `riko.modules` share the
`modules` layer. `riko.__init__` is `api`; `riko._package` is `base`.

Use `manage lint imports --architecture` to inspect the graph and
`manage lint imports --all` for all import contracts. `manage lint --all` includes
the import checks and is the standard CI lint path. Do not add an upward import or
an ad-hoc architecture exception when a shared contract can move to the lower
owning layer.

## Docs Map

| Path | Role |
|---|---|
| `_docs/KEY_PATHS.md` | current source-tree map and file-local invariants |
| `_docs/INTERNALS.md` | codegen/discovery/import-lint/tooling internals |
| `_docs/gameplans/dependency-layers.md` | authoritative human-readable package DAG + executable import-policy mapping |
| `_docs/RUNTIME_CONTRACT.md` | **stable** shipped runtime guarantees; feature/end-state topics live in gameplans |
| `_docs/IMPLEMENTED.md` | as-built companion + single source for build completeness |
| `_docs/PHASE_CHECKLISTS.md` | authoritative P-track status |
| `_docs/MILESTONES.md` | P-track history companion, not forward implementation order |
| `_docs/ROADMAP.md` | routing-only authority index for shipped contracts, active owners, status/history, and forward sequence |
| `_docs/gameplans/implementation-sequence.md` | authoritative forward dependency order among owner contracts |
| `_docs/gameplans/` | active target/implementation plans, one semantic owner per concept |
| `_docs/research/` | prior art/rationale; context only, never authoritative |
| `_docs/archive/` | superseded historical plans; history only |
| `_docs/DOCUMENTATION_STANDARD.md` | authoritative docstring/doctest/`__init__.py` standard |
| `_docs/API_SURFACE.md` | STABLE `riko` / EXTENSION `riko.ext` / private import contract; generated name blocks come from `riko/base/_api_surface.py` |
| `docs/CHANGES.rst` | user-observable changelog; no private implementation-move journaling |
| `docs/MIGRATION.rst` | consolidated supported migration guide |
| `docs/DAG_FORMAT.rst` | bare-bones DAG format + `convert-dag`/`compile-pipe` |
| `README.rst`, `docs/{FAQ,COOKBOOK,INSTALLATION}.rst`, `CONTRIBUTING.rst` | user-facing docs |

## API Tiers

- **STABLE** — application code imports from `riko`.
- **EXTENSION** — module/integration authors import from `riko.ext`.
- **TYPES** — supported typing imports live under the documented `riko.types`
  surface where explicitly exported.
- **PRIVATE** — underscore modules and non-exported implementation paths may move;
  their placement expresses internal architecture, not a SemVer promise.

The supported name sets are declared once in `riko/base/_api_surface.py`; the
marked blocks in `_docs/API_SURFACE.md` are generated from that source.

## Async Backend

`riko.bado` is the stable async backend/iterator namespace. Its private backend
facade is `riko/bado/_backend.py`; when the async extra is unavailable the package
falls back to its empty/sync-only behavior. There is no Twisted backend and no
`RIKO_ASYNC_BACKEND` environment switch.

Async transport/file operations are separate: `async_url_open`, `async_write`, and
`get_async_temp_file` live under `riko/io/` and are promoted to the stable `riko`
surface.

## Cross-cutting invariants

Non-obvious decisions that shape code across modules — **do not silently revert
them**. A one-off bug belongs in its regression test and changelog entry, not as a
new permanent bullet here.

- **`is None` over truthiness** — `0`, `False`, and `""` are valid values. Missing
  data is not the same as a present falsy value.
- **Immutable prepare** — `Module.prepare()` returns a frozen `PreparedModule` with
  no mutable call cache; call-site options cannot leak across items/concurrent
  invocations.
- **Immutable definitions, mutable execution** — `Context`, resource definitions,
  module definitions, and write intent are structural snapshots. Derive changed
  definitions; never smuggle execution-owned mutable state back onto them.
- **Definition/execution split** — declarative resource/write contracts belong in
  `riko/definitions/`; concrete lifecycle/session state belongs in the explicit
  execution/runtime layers.
- **Foreign-option guard raises at decoration/import time** — handing one decorator
  another decorator's option is an author error, not a runtime data condition.
- **Pool/pipe lifecycle** — `_owns_pool` decides who closes a pool; borrowed pools
  stay open; pipes are one-shot; exceptional termination discards buffered/partial
  output rather than silently committing it.
- **Lazy async I/O lifetime** — a lazy parser must retain its async URL/file handle
  through iteration. Do not shorten the lifetime with an `async with` that exits
  before the returned iterator is consumed.
- **Architecture is enforced** — new modules must classify into the layer DAG.
  Function-local/type-only edges may be visible in the report, but module-scope
  runtime imports may not point upward.

## Coding Style

- No comments unless the logic is genuinely non-obvious.
- Single `return` statement per function; no early-return style unless an existing
  specialized pattern explicitly requires it.
- Runtime data conditions degrade only when the data contract survives
  (`logger.warning` + carry on). Missing required call arguments are programming
  errors and raise; `require_arg` in `riko/modules/_prepare.py` owns that pattern.
- Docstrings follow `_docs/DOCUMENTATION_STANDARD.md`: annotations own types except
  the documented pipe conventions; summaries use third-person present. Public
  modules (including private files that define re-exported public APIs) keep a useful
  entry-point example; one example is a soft default, not a cap when distinct modes
  or a complete workflow need more. Public package docstrings preserve namespace
  purpose/audience/stability rather than collapsing to generic one-liners.
- New code is fully typed and documented. Prefer type narrowing over `cast`; narrow
  untyped values once at the boundary and carry the tightened type forward.
- Guard optional imports with `try/except` and set the backend/feature flag in the
  exception path.
- Use the established `noqa: E302` / `noqa: E704` overload exceptions where Ruff
  and the overload layout conflict.
- Keep package-local imports relative; canonical import and architecture rules are
  enforced by `manage lint imports`.

## Project Quirks

- **uv** — use the active environment form (`uv run --active ...`) when the current
  shell venv should win over the default `.venv`.
- **Python 3.12+** — `requires-python = ">=3.12"`; use PEP 695 type params and
  modern union syntax.
- **Doctests are tests** — configured pytest testpaths include source/docs/examples.
  Before deleting a doc example, confirm its behavior still has an executable owner;
  before adding a replacement pytest test, check function/class doctests first.
  Async/Bado doctests are skipped automatically when async support is unavailable,
  so do not add `issync` fallback branches solely for doctest collection.
- **`manage`** — `riko.cli.manage:manager` is the Click entry point. `manage.py`
  composes private command modules by reason to change. It collides with
  `mezmorize`'s console script in some install orders; use
  `python -m riko.cli.manage` if the wrong executable wins.
- **Codegen selectors** — `manage codegen` defaults to config; `--config`,
  `--names`, `--pipes`, `--api` are additive; `--all` runs all generators.
- **Generated files are never hand-edited** — `riko/coercion/_configs.py`,
  `riko/modules/_names.py`, `riko/types/_module_ids.py`, generated pipeline fixture
  trees, and the marked name blocks in `_docs/API_SURFACE.md` all have canonical
  sources and drift guards. Details: `_docs/INTERNALS.md`.
- **Lint selectors are additive** — bare `manage lint` is Ruff; `manage lint --all`
  runs the standard lint suite including import contracts. Type verification,
  pylint strict mode, and distribution checks remain explicit heavyweight checks.
- **Docs stay consistent by lint** — `manage lint --docs` guards the authoritative
  `_docs/` model; transient scratch material does not belong in authoritative root
  docs.
- **Module catalog + discovery enums are derived** — `list_modules()` /
  `describe_module()` read runtime metadata; `Modules`/`Sources`/`Transforms`/
  `Sinks` and `Formats` are re-exported from the stable `riko` surface. `Formats`
  (serialization) is not `Sinks` (pipe category).
- **meza is pinned by `pyproject.toml`**; lower-level conversion ownership remains
  with meza where the runtime contract says so.
