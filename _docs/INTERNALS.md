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
manage codegen --all
```

The private command implementation is `riko/cli/_codegen.py`; individual generators
live beside it as `_gen_*.py`. Standalone `gen-*` console scripts remain available.
All Python-source generators format through the shared
`riko.base._source_format.ruff_format(str) -> str` helper rather than shelling out
at call sites.

- **Config** — `riko/cli/_gen_config.py` derives `<Name>Objconf` classes from the
  `<Name>Conf` TypedDict contracts in `riko/types/modules.py` and writes
  `riko/coercion/_configs.py`. `DynamicConf` lives in
  `riko/coercion/_dynamic_conf.py`. Edit the hand-maintained config contracts, not
  the generated objconf file.
- **Names** — `riko/cli/_gen_names.py` derives both
  `riko/modules/_names.py` (`Modules`/`Sources`/`Transforms`/`Sinks`) and
  `riko/types/_module_ids.py` (`ModuleId`/`LoopableModuleId`) from the runtime
  module catalog. Both artifacts are deterministic and generated; never hand-edit
  them.
- **API surface** — `riko/cli/_gen_api_surface.py` rewrites only the marked name
  blocks in `_docs/API_SURFACE.md` from the private declarations in
  `riko/base/_api_surface.py`. Surrounding prose stays hand-maintained.

Tests under `tests/internal/` byte/structure-check generated outputs so source and
generated artifacts cannot drift silently.

## Pipeline fixtures

`tests/pipelines/*.json` and `examples/pipelines/*.json` are canonical Workflow v2
documents — exactly what `serialize_workflow` emits by default: indented, with sorted
keys and a trailing newline — and the v2 runtime executes them directly. They are hand-maintained
sources, not generated output. `tests/internal/test_workflow_fixtures.py` reparses
and reserializes each file, so a committed fixture that drifts from canonical form
fails there.

The `tests/pypipelines/pipe_*.py` and `examples/pypipelines/pipe_*.py` modules are a
reduced covering set of hand-maintained typed probes. Their job is to put the
`<Name>RawConf`/`<Name>Conf`/`<Name>ConfRule` shapes in real call position so pyright
surfaces a config-contract error; the same test asserts each probe yields the items
its JSON sibling does. There is no generator behind them — edit them by hand, and add
one only for a config shape the surviving probes do not already reach.

The compiler implementation lives under `riko/runtime/`:

- `riko/runtime/_codegen.py` — the Workflow v2 generator behind `compile_pipe`.
- `riko/runtime/_migrate.py` — `parse_dag` (bare-bones DAG) and `migrate_v1_to_v2`.
- `riko/runtime/_compile.py` — the v1 parse/build/compile operations.
- `riko/runtime/_compile_repr.py` — the `Id` placeholder the v1 compiler renders unquoted; literal
  rendering lives in `_codegen.render_value`.
- `riko/runtime/templates/` — `pyworkflow.txt` (v2) plus the v1 `pypipe*.txt` templates.
- `riko/types/_compiler.py` — compiler/DAG type contracts.

The console scripts are v2-native. `riko/cli/_workflow.py` is their one document front
door: it detects whether a document is a bare-bones DAG, a released pipe definition, or
a canonical workflow, and hands it to `parse_dag`, `migrate_v1_to_v2`, or
`normalize_workflow`. `build-workflow` is the only lenient reader — it accepts all three
and always emits canonical v2; `compile-pipe` and `run-pipe` go through
`require_workflow`, which refuses anything older. The v1 compiler (`_compile.py`,
`pypipe*.txt`) survives only until the cutover's compiler-deletion step; nothing in the
CLI reads it, and none of it is part of maintaining the fixtures above.

## Discovery enums & export formats

- **Module catalog is derived, not declared.** `riko/modules/_metadata.py` discovers
  built-ins and reads decorator-set metadata. `list_modules()` and
  `describe_module()` expose that truth through supported facades.
- **Discovery enums are generated.** `riko/modules/_names.py` owns the flat
  `Modules` namespace and the `Sources`/`Transforms`/`Sinks` buckets. The stable
  `riko` facade re-exports them; do not hand-maintain parallel lists.
- **Name normalization lives in `riko/ext/_names.py`.** Public name-accepting
  discovery APIs normalize a string or discovery member to the canonical module id
  before constructing metadata.
- **Formats are not sinks.** `Formats` is the serialization/export enum used by
  `riko/runtime/collections.py` and the write stack. `Sinks` is a generated bucket
  of pipe modules. These are separate axes even when a sink pipe ultimately writes
  a serialized format.
- **Write contracts live below execution.** Declarative write intent and protocols
  are in `riko/definitions/_write.py`; target validation is in
  `riko/definitions/_targets.py`; live session state is in
  `riko/runtime/_write_session.py`; collection verbs are in
  `riko/runtime/collections.py`.
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
  `_build`, `_lint`, `_docs`, `_test`, `_codegen`, `_release`, and import-lint
  modules own implementation by reason to change.
- **`manage` console-script collision.** `mezmorize` also declares a `manage`
  script. If install order selects the wrong executable, invoke
  `python -m riko.cli.manage`. Tox uses the module form to avoid that ambiguity.
- **`uv`.** Use `uv run --active ...` when the current shell environment should win
  over the default `.venv`.
- **Python 3.12+.** Prefer PEP 695 type parameters and modern union syntax.
- **Doctests are tests.** Source/docs examples under the configured pytest testpaths
  are collected; avoid copying the same happy-path example into multiple files.
- **Pub/sub state.** Runtime pub/sub lives under `riko/runtime/_pubsub/`; tests reset
  that context-local hub state between cases.
- **`DotDict`.** The implementation lives in `riko/parsing/_dotdict.py`; fast paths
  for simple keys should remain simple rather than routing everything through
  dotted-path parsing.
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

The source hierarchy itself is not a compatibility promise for private modules.
It is an internal architecture promise: code belongs in the lowest package layer
that owns its responsibility, and `manage lint imports --architecture` enforces the
runtime direction between those layers.
