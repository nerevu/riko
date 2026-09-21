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
| `riko/definitions/` | immutable/declarative module, resource, target, write, and Workflow v2 graph contracts |
| `riko/io/` | sync/async URL/file I/O, serialization, re-encoding |
| `riko/parsing/` | config parsing, `DotDict`, XML/HTML/document parsing |
| `riko/rss/` | feed discovery, parsing, entry normalization |
| `riko/execution/` | explicit execution layer: one-shot sync/async executions, lifetime primitives, execution-local resource acquisition, event sink, execution context; `context.py` + `_resources.py` live here |
| `riko/runtime/` | executable orchestration: collections, compiler, resolver/registry, pipelines, pub/sub, write sessions |
| `riko/modules/` | built-in pipe implementations; private decorator/preparation/metadata/looping internals; generated discovery names |
| `riko/ext/` | supported extension-author facade + extension codegen/name helpers; shares the `modules` architecture layer |
| `riko/cli/` | CLI commands, private generators, docs checks, and import-contract linters; `manage.py` stays a thin composer |

Important concrete locations:

- collections/export/write verbs: `riko/runtime/collections.py`
- graph index for execution planning: `riko/runtime/_graph_index.py`
- v2 code generator behind `compile_workflow`/`compile-workflow`: `riko/runtime/_codegen.py`
- CLI workflow-document front door: `riko/cli/_workflow.py`
- pub/sub: `riko/runtime/_pubsub/`
- executions/preparation: `riko/execution/_execution.py` + `_prepared.py`; the frozen plan is `riko/runtime/_execution_plan.py`
- execution context/resources: `riko/execution/context.py` + `_resources.py`
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

`riko.execution.context` and `riko.execution._resources` map to `execution`; the rest
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
| `docs/CHANGES.rst` | user-observable changelog vs the last release; no private implementation-move journaling; an unreleased feature (`Pipeline`) is one "Added" bullet edited in place, never a stream of "gained/now" deltas (`_docs/INTERNALS.md`) |
| `docs/MIGRATION.rst` | consolidated supported migration guide |
| `docs/DAG_FORMAT.rst` | bare-bones DAG format + `build-workflow`/`compile-workflow`/`run-pipe` |
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
`async_get_temp_file` live under `riko/io/` and are promoted to the stable `riko`
surface.

## Cross-cutting invariants

Non-obvious decisions that shape code across modules — **do not silently revert
them**. A one-off bug belongs in its regression test and changelog entry, not as a
new permanent bullet here.

- **`is None` over truthiness** — `0`, `False`, and `""` are valid values. Missing
  data is not the same as a present falsy value.
- **One canonical identity system** — durable identity (checkpoints, generation,
  idempotency, fingerprints) uses the shared freezing/encoding layer in
  `riko/coercion/_freeze.py` (`freeze`/`canonical_bytes`/`digest`), never Python's
  randomized `hash()` or an ad-hoc encoder. It distinguishes types Python conflates and
  raises on unsupported/cyclic values; process-local caches may bypass instead of raising.
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
- No internal jargon in shipped text. Phase codes (`R4B`/`P10`), gameplan/section
  refs, `_docs/` paths, and ticket ids never appear in docstrings, comments, test
  names/`xfail` reasons, `docs/*.rst`, or runtime messages — say what the behavior or
  pending capability is in plain English; keep phase cross-refs in `_docs/` and here.
  Full rule: `_docs/DOCUMENTATION_STANDARD.md` (No internal jargon in shipped text).
- **A `Pipeline` variable is `pipeline`, never `flow`** — in code, tests, examples,
  docs, gameplans, and drafts alike: `pipeline = Pipeline.from_module(...)`,
  `pipeline = pipeline.with_execution(...)`, `stream = iter(pipeline)`. `flow` names
  only a bare `Workflow` (`flow = pipeline.workflow`). Don't copy `flow = ...` from
  older text; rename it.
- **Workflow forms go by their type names** — `Workflow`, `RawWorkflow`,
  `WorkflowDocument` ("workflow document" on first use), `PipeDef` ("pipe definition"
  on first use), `PipeDag`; old JSON is a "serialized `PipeDef`". Full rule and
  exemptions: `_docs/DOCUMENTATION_STANDARD.md` (No internal jargon in shipped text).
- New code is fully typed and documented. Prefer type narrowing over `cast`; narrow
  untyped values once at the boundary and carry the tightened type forward.
- Guard optional imports with `try/except` and set the backend/feature flag in the
  exception path.
- Use the established `noqa: E302` / `noqa: E704` overload exceptions where Ruff
  and the overload layout conflict.
- Keep package-local imports relative; canonical import and architecture rules are
  enforced by `manage lint imports`.
- **`StrEnum` vs `Literal`.** Use a `StrEnum` when a caller **supplies the value at a
  Python call site** (a parameter, or a field callers construct) or for a runtime
  **state** — they get named members and one import instead of magic strings; `.value`
  is canonical. Use a `Literal[...]` when the value only **arrives as a serialized/JSON
  string**, is produced internally and merely read/matched (a return tag / discriminant),
  or is a fixed `ClassVar` tag. Non-string internal markers/states use a plain `Enum`.
  **Carve-out:** the metadata axes `ModuleType`/`ModuleCategory`/`ModuleSubtype` stay
  `Literal` even though they appear as `list_modules(...)` args — their canonical form is
  the bare metadata string; the discovery *tree* is the enum layer.
- **Function-verb vocabulary.** Name a function by what it does. The eight verbs a
  developer weighs are defined in the table below; each row's hard rule is the test.
  `require` is not "`resolve` but raising": it is the general narrow-or-raise /
  prerequisite-enforcement verb, and `require(resolve(...))` is one specialization of
  it, which is why the `require_str`/`require_mapping`/`require_options` guard family
  carries it. `build` absorbs the old `prepare`/`convert`/`make`. Specialized verbs are
  not alternatives to weigh: `cast` (coercion), `compile` (compiler), `generate`/`gen_`
  (codegen / Python-generator convention), `migrate` (version migration), `serialize`,
  `register`, `read`/`write`/`open`/`close`, and `is`/`has` for predicates.

| Verb | Meaning | Raising | Idempotency | Context / lookup | Hard rule |
|---|---|---|---|---|---|
| **`get`** | Query or compute a value from explicit semantic inputs | **MAY raise** for invalid input | No requirement | **MUST NOT** acquire external/ambient state | Returns information; does not canonicalize or construct a substantial artifact |
| **`parse`** | Representation/grammar → semantic structure | Malformed input **MUST raise** | No requirement | **MUST NOT** use resolution context | Input is a representation *of* the output |
| **`normalize`** | Accepted form → canonical equivalent form | Invalid form **MUST raise** | **MUST** be idempotent | **MUST NOT** use resolution context | Canonical output must itself be an accepted form |
| **`resolve`** | Determine an effective value/object using reference, context, fallback, or precedence | **MUST NOT use "no match" as an error when absence/fallback is part of the contract**; invalid input may raise | No requirement | **MUST** involve reference/context/fallback/precedence | Chooses what applies rather than canonicalizing the input |
| **`require`** | Enforce that a required value/object/precondition exists and return it in usable form | Requirement failure **MUST raise** | No general requirement | **MAY** use lookup/context, but need not | **MUST NOT silently default, repair, or substitute** for a missing required value |
| **`load`** | Acquire through external/ambient/provider boundary | Acquisition failure normally surfaces | No requirement | **MUST** cross an acquisition boundary | Obtains data/state from somewhere outside the supplied semantic value |
| **`validate`** | Check a contract | Invalid value **MUST raise** | Observationally idempotent | May inspect explicit supporting information | **MUST NOT transform or return a replacement value** |
| **`build`** | Assemble a new semantic artifact | Construction failure may raise | No requirement | Dependencies should be explicit | Creates a new artifact from semantic components |

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
  `--names`, `--api` are additive; `--all` runs all generators.
- **Generated files are never hand-edited** — `riko/coercion/_configs.py`,
  `riko/modules/_names.py`, `riko/types/_module_ids.py`, and the marked name blocks
  in `_docs/API_SURFACE.md` all have canonical sources and drift guards. The
  `workflows`/`pyworkflows` fixture trees are not generated; they are
  `WorkflowDocument`s plus hand-maintained typed probes. Details: `_docs/INTERNALS.md`.
- **Lint selectors are additive** — bare `manage lint` is Ruff; `manage lint --all`
  runs the whole standard suite (Ruff, RST, `--docs`, `--docstrings`, actionlint,
  YAML, and all import contracts), so none of those need a separate run. Type
  verification (`--check-types`/`--verify-types`), pylint strict mode, and
  distribution checks remain explicit heavyweight checks.
- **Docs stay consistent by lint** — `manage lint --docs` guards the authoritative
  `_docs/` model; transient scratch material does not belong in authoritative root
  docs.
- **Module catalog + discovery enums are derived** — `list_modules()` /
  `describe_module()` read runtime metadata; `Modules`/`Sources`/`Transforms`/
  `Sinks` and `Formats` are re-exported from the stable `riko` surface. `Formats`
  (serialization) is not `Sinks` (pipe category).
- **meza is pinned by `pyproject.toml`**; lower-level conversion ownership remains
  with meza where the runtime contract says so.
- **Tunable knobs live in `riko/base/_config.py`** — static project policy
  (`LAYER_DEPENDENCIES`/`EXACT_LAYERS`/`PREFIX_LAYERS`, consumed and frozen by the import
  linter; `SINK_NAMES`; `SUBPIPE_TYPE`; the legacy port/output tokens
  `INPUT_PORT`/`OUTPUT_PORT`/`OTHER_PORT`/`OUTPUT_MODULE` shared by `_normalize`/
  `_migrate`) plus a frozen `Settings` with `RIKO_*` env overrides (`load_settings`; a malformed value logs a warning and falls back
  to the default). Existing names (`DEF_CONNECTION_COUNT`, `TIMEOUT`, `EXCHANGE_API`, …)
  re-source from `settings`; add operator-tunable defaults here, not as scattered literals.
