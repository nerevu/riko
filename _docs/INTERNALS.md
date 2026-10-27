# Internals

Long-form implementation notes extracted from `CLAUDE.md`. The short repo router
lives there; `_docs/KEY_PATHS.md` maps concrete source locations; and
`gameplans/dependency-layers.md` defines the package dependency DAG.

## Index

- [Codegen & generated files](#codegen--generated-files)
- [Pipeline fixtures](#pipeline-fixtures)
- [Discovery enums & export formats](#discovery-enums--export-formats)
- [Import contract tooling](#import-contract-tooling)
- [Tooling & environment notes](#tooling--environment-notes)

## Codegen & generated files

The `manage codegen` command is selector-based. With no selector it regenerates
config types; selectors are additive, and `--all` runs every generator:

```text
manage codegen
manage codegen --config
manage codegen --names --api
manage codegen --tests
manage codegen --all
```

The private command implementation is `riko/cli/_codegen.py`; individual generators
live beside it as `_gen_*.py`. Standalone `gen-*` console scripts remain available.
All Python-source generators format through the shared
`riko.base._strutils.ruff_format(str) -> str` helper rather than shelling out
at call sites.

- **Config** — `riko/cli/_gen_config.py` derives `<Name>Objconf` classes from the
  `<Name>Conf` TypedDict contracts in `riko/types/modules.py` and writes
  `riko/coercion/_configs.py`. `DynamicConf` lives in
  `riko/coercion/_dynamic_conf.py`. Edit the hand-maintained config contracts, not
  the generated objconf file.
- **Names** — `riko/cli/_gen_names.py` derives both
  `riko/modules/_names.py` (`Modules`/`Sources`/`Transforms`/`Sinks`) and
  `riko/types/_module_ids.py` (`ModuleId`/`LoopableModuleId`/`BUILTIN_MODULE_IDS`) from the runtime
  module catalog. Both artifacts are deterministic and generated; never hand-edit
  them.
- **API surface** — `riko/cli/_gen_api_surface.py` rewrites only the marked name
  blocks in `_docs/API_SURFACE.md` from the private declarations in
  `riko/base/_api_surface.py`. Surrounding prose stays hand-maintained.
- **Verb tables** — `riko/cli/_gen_verbs.py` (`manage codegen --verbs`) rewrites the
  marked `verbs`/`verb-pairs` blocks in `CLAUDE.md` (Markdown) and `CONTRIBUTING.rst`
  (grid tables) from `riko/base/_verbs.py`, which `manage lint --docstrings` also
  reads to match each summary's verb to its function name; `manage lint --docs`
  flags stale blocks. Surrounding prose stays hand-maintained.
- **Test index** — `riko/cli/_gen_tier_index.py` (`manage codegen --tests`) rewrites the
  `Index (file, ...)` block ending each `tests/<tier>/__init__.py` docstring from the
  tier files' `Test<Subject>` classes.

Tests under `tests/internal/` byte/structure-check generated outputs so source and
generated artifacts cannot drift silently.

## Pipeline fixtures

`tests/workflows/*.json` and `examples/workflows/*.json` are workflow documents
(`WorkflowDocument`s) — exactly what `Workflow.serialize` emits by default: indented, with sorted
keys and a trailing newline — and the v2 runtime executes them directly. They are hand-maintained
sources, not generated output. `tests/internal/test_codegen.py` reparses
and reserializes each file, so a committed fixture that drifts from canonical form
fails there.

The `tests/pyworkflows/pipe_*.py` and `examples/pyworkflows/pipe_*.py` modules are a
reduced covering set of hand-maintained typed probes. Their job is to put the
`<Name>RawConf`/`<Name>Conf`/`<Name>ConfRule` shapes in real call position so pyright
surfaces a config-contract error; the same test asserts each probe yields the items
its JSON sibling does. There is no generator behind them — edit them by hand, and add
one only for a config shape the surviving probes do not already reach.

The compiler implementation lives under `riko/runtime/`; workflow loading lives under
`riko/definitions/`:

- `riko/runtime/_compile.py` — the Workflow v2 generator behind `compile_workflow`.
- `riko/definitions/_workflow_definition.py` — `Workflow.parse`/`load`/`serialize`, plus `migrate_v1_to_v2` (`PipeDef`, a pipe definition), over the data-returning `_normalize.py`/`_migrate.py`/`_serialize.py`.
- `GraphIndex` (`riko/types/_workflow.py`) — derives the topology from node ids, edges, and outputs; `Workflow.index` builds it, and validation and execution planning both read it.
- `riko/runtime/templates/` — `pyworkflow.txt`, the v2 generator template.
- `riko/types/_pipedef.py` — `PipeDef`/`PipeDefLike` and `PipeDag` type contracts;
  all three are exported on `riko.types`.

The console scripts are v2-native. `riko/cli/_document.py` is their one document front
door (`read_document`, `require_workflow`). `build-workflow` reads through `Workflow.parse`,
which detects whether a document is a serialized `PipeDag`, a serialized `PipeDef`, or a
`WorkflowDocument` (`get_document_shape`) unless `--format` pins the `DocumentShape`.
`build-workflow` is the only lenient reader — it accepts all three
and always emits a `WorkflowDocument`; `compile-workflow` and `run-pipe` go through
`require_workflow`, which refuses anything older. The v1 compiler was deleted at
cutover step 5 (2026-10-03).

## Discovery enums & export formats

- **Module catalog is derived, not declared.** `riko/modules/_metadata.py` discovers
  built-ins and reads decorator-set metadata. `list_modules()` and
  `describe_module()` expose that truth through supported facades.
- **Discovery enums are generated.** `riko/modules/_names.py` owns the flat
  `Modules` namespace and the `Sources`/`Transforms`/`Sinks` buckets. The stable
  `riko` facade re-exports them; do not hand-maintain parallel lists.
- **Name normalization lives in `riko/definitions/_module_definition.py`; discovery in
  `riko/modules/_metadata.py`.** Public name-accepting discovery APIs
  (`get_module_metadata`, `describe_module`) normalize a string or
  discovery member to the canonical module id before constructing metadata.
- **Formats are not sinks.** `Formats` is the serialization/export enum used by
  `riko/runtime/_export.py` and the write stack. `Sinks` is a generated bucket
  of pipe modules. These are separate axes even when a write module ultimately writes
  a serialized format.
- **Write contracts live below execution.** Declarative write intent and protocols
  are in `riko/definitions/_write.py`; target validation is in
  `riko/definitions/_targets.py`; live session state is in
  `riko/runtime/_write_session.py`; export helpers are in
  `riko/runtime/_export.py`.
- **Async I/O moved out of Bado.** Backend/iterator helpers remain under
  `riko/bado/`, while `async_url_open`, `async_write`, and async temp-file support
  live under `riko/io/` and are promoted through the stable `riko` surface.

The chainable `write` verb and terminal `sink` verb use the same prepared write and
session contracts. `sink` returns `WriteResult`; terminality is a collection
consumption choice rather than a distinct `Sink*` object hierarchy.

## Import contract tooling

Package boundaries are executable policy rather than documentation-only convention.
The relevant CLI is:

```text
manage lint imports                 # canonical check (default)
manage lint imports --relative
manage lint imports --architecture
manage lint imports --all
manage lint --all                   # includes all import checks
```

The implementation is split by responsibility:

- `riko/cli/_import_graph.py` — pure AST discovery and module/local/type-only import
  classification.
- `riko/cli/_lint_canonical_imports.py` — rejects internal imports through re-export
  facades when a canonical defining module exists.
- `riko/cli/_lint_relative_imports.py` — requires relative sibling imports within a
  package.
- `riko/cli/_lint_import_architecture.py` — maps modules to the declared layer DAG,
  renders observed dependencies, and rejects forbidden package direction.
- `riko/cli/_import_commands.py` — shared selector command and exit-code handling.

The current layer/package mapping is documented in
`gameplans/dependency-layers.md`. Keep that document and the executable mapping in
sync when source is moved between package groups.

## Tooling & environment notes

- **`manage` is a thin composer.** `riko/cli/manage.py` registers commands; private
  `_build`, `_lint`, `_docs`, `_test`, `_upgrade`, `_codegen`, `_release`, and
  import-lint modules own implementation by reason to change.
- **`manage` console-script collision.** `mezmorize` also declares a `manage`
  script. If install order selects the wrong executable, invoke
  `python -m riko.cli.manage`. Tox uses the module form to avoid that ambiguity.
- **`uv`.** Use `uv run --active ...` when the current shell environment should win
  over the default `.venv`.
- **`uv.lock` is the only tool-version source.** CI installs with `uv sync --locked`
  and runs ruff through `uv run --no-sync`; tox uses the lock runner. The pre-commit
  ruff hooks are `language: python` local hooks pinning `ruff==<locked>` in pre-commit's
  own environment, so they need neither `uv` on the Git client's `PATH` nor an active
  venv (`uv run --active` without `VIRTUAL_ENV` silently falls back to a stale
  `.venv`). That pin is the one copy of a locked version outside `uv.lock`:
  `manage upgrade` rewrites it and `manage lint --deps` fails when it drifts. Upgrades
  happen locally: `manage upgrade` runs `uv lock --upgrade` (or `--upgrade-package`
  per `--package`) and syncs the active environment with every group and extra. Both hold
  to `[tool.uv] exclude-newer = "1 week"`: no release younger than a week resolves, a
  security fix included, so an urgent one needs uv's `exclude-newer-package` override
  for that package. `--daily` skips when
  `.cache/last-upgrade` holds today's date, which only a successful full upgrade and
  sync writes. `PYRIGHT_PYTHON_FORCE_VERSION` never reaches tox (not in `pass_env`)
  and must not be added; `[tool.pyright] pythonPlatform = "Linux"` keeps local type
  checks on CI's platform.
- **Test layout lint.** Each tier index in `tests/<tier>/__init__.py` is generated by
  `manage codegen --tests` (`riko/cli/_gen_tier_index.py`) from the files' `Test<Subject>`
  classes and runs from its `Index (file, ...)` header to the docstring's end, so it stays
  last. `manage lint --tests` fails when it is stale. An `Async<Subject>` class is left out
  when its `<Subject>` or `Sync<Subject>` is in the same file, so a twin pair takes one
  index entry. A bare section keyword (`Examples`, `Returns`) on its
  own index line reads as a docstring section to pydocstyle, so name such subjects longer.
- **Basename lint.** `manage lint --basenames` fails when two modules under `riko/`
  (`__init__.py` aside) share a file name. Deliberate pairs are allowlisted in
  `DUPLICATE_BASENAMES` in `riko/base/_config.py`; an allowlisted name that is no longer
  shared also fails, so the allowlist is pruned when a pair is renamed away.
- **Escape ratchet.** `manage lint --escapes` counts `typing.Any` references and
  `typing.cast` calls under `riko/` by import binding (an unrelated `cast`, such as a
  coercion function, is not counted), including quoted annotations, quoted `cast` targets,
  and quoted subscripts. The counts ratchet against `[tool.riko.typing]` `any`/`cast` in
  `pyproject.toml` through `riko/cli/_ratchet.py`, the same ratchet as the coverage
  ceiling: above fails, below lowers the ceiling (keep the `pyproject.toml` diff).
- **Docstring example lint.** `manage lint --docstrings` also flags a doctest that
  imports a public name through a private `riko` module path, and a module example in an
  underscore-prefixed module that defines no public name. Both read the public names
  from `riko/base/_api_surface.py`: `STABLE` maps to `riko`, `EXTENSION` to `riko.ext`,
  `EXT_CODEGEN` to `riko.ext.codegen`, and `TYPES` to `riko.types`, first match winning
  (`resolve_public_path` in `riko/cli/_docstyle.py`).
- **Stale citation lint.** `manage lint --docs` fails on a backticked `tests/<tier>/test_*.py`
  citation (in the tracked `_docs/` root docs, gameplans, `CONTRIBUTING.rst`, `CLAUDE.md`, or
  `docs/*.rst`) or `riko/*.py` citation (in the tracked `_docs/` root docs, `CLAUDE.md`,
  `README.rst`, or `CONTRIBUTING.rst`; gameplans, `MILESTONES.md`, and `docs/` keep history) that names no
  current file. A line saying the file was deleted, retired, removed, dropped, merged, or
  superseded is exempt (`gen_stale_test_citations`/`gen_stale_path_citations` in `riko/cli/_docs.py`).
- **Coverage ratchet.** `manage test --ratchet` counts `missing_lines` from a JSON report
  written to a fresh temp folder. That folder also holds the run's coverage data
  (`COVERAGE_FILE`), so another pytest run in the checkout cannot erase or combine it.
  Coverage runs on the `sysmon` core (Python 3.12 `sys.monitoring`; about the cost of a
  no-coverage run) and measures the console scripts
  through `patch = ["subprocess"]`. Dev-only `manage` modules are listed in
  `[tool.coverage.run] omit`, so a new `manage` helper module must join that list. The
  ceiling is specific to the full dev environment on Python 3.12; other environments run
  `--no-cov`.
- **Python 3.12+.** Prefer PEP 695 type parameters and modern union syntax.
- **Doctests are tests.** Source/docs examples under the configured pytest testpaths
  are collected; avoid copying the same happy-path example into multiple files.
- **Pub/sub state.** Runtime pub/sub lives under `riko/runtime/_pubsub/`; tests reset
  that context-local hub state between cases.
- **`DotDict`.** The implementation lives in `riko/parsing/_dotdict.py`; fast paths
  for simple keys should remain simple rather than routing everything through
  dotted-path parsing. A nested write (`d["a.b"] = v`, a dotted `update`, `delete`)
  walks the item in place and copies only the mappings on the key's path
  (`detach_nested`), so it never edits the caller's nested dicts or re-reads sibling
  fields, and its cost grows with the sizes of the mappings on that path rather than
  with the item's top-level keys. The single-key set and the plain-dict `update`
  loop call `CaseInsensitiveDict.__setitem__` directly: routing them through
  `raw_set` doubles their cost.
- **`meza` is pinned to the project source declared in `pyproject.toml`.** Meza owns
  the lower-level conversion semantics referenced by the runtime contract.
- **Changelog style.** `docs/CHANGES.rst` records user-observable behavior in the
  shortest useful form; implementation moves and private helper names do not belong
  there unless they change a supported import or command surface.
- **Unreleased features get one entry, not a history.** The changelog describes the
  delta against the *last release*, so a feature that has never shipped (today:
  `Pipeline` and the workflow model) is one "Added …" bullet under **New** that
  states what the feature does when it ships. Each change to it on `next`/`features`
  edits that bullet in place; never append "`Pipeline` gained …", "`Pipeline.write`
  now …", or similar deltas against a state no user has seen. A placeholder verb that
  raises `NotImplementedError` is not user-observable behavior and is not mentioned at
  all; the bullet is written against the capability that will actually ship. Deltas
  are written only against names that appear in a released version.
- **Changelog order.** A release's sections run **New**, **Changes**, **Removed**,
  **Fixes**, **Dev**, so everything that breaks an upgrade sits together. Every section
  follows one subject order: core model (`Pipeline`, `Workflow`, `Context`); workflow
  formats and CLI; module authoring (decorators, `ModuleDefinition`, registry,
  `riko.ext`); types (`riko.types`); I/O and async (`riko.io`, `riko.bado`); individual
  modules' behavior; settings. Within a subject the most user-impacting bullet leads,
  and a bullet that depends on another comes after it.
- **Define once, in reading order.** A term the release introduces gets its gloss (and
  its `riko.` prefix) at its first mention anywhere in the release section, and the bare
  ``name`` after that. The leading bullet is written so it needs no term defined later.
- **A rename is a lookup, not a definition.** The rename bullet under **Changes** alone
  maps old to new names. Other bullets, **New** included, use the new name bare, with no
  "(formerly …)", so **New** preceding **Changes** needs no forward reference.
- **No cross-section pointers.** Never write "see above/below". A bullet that only makes
  sense alongside a rename or removal folds into that bullet instead (e.g., an attribute
  added to a renamed exception, or the new behavior of a removed argument's
  replacement).

The source hierarchy itself is not a compatibility promise for private modules.
It is an internal architecture promise: code belongs in the lowest package layer
that owns its responsibility, and `manage lint imports --architecture` enforces the
runtime direction between those layers.
