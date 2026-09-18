# Key Paths — per-file detail

Long-form companion to the short key-path router in `CLAUDE.md`. The source tree is
now grouped by dependency responsibility; `_docs/gameplans/dependency-layers.md`
defines the enforceable import DAG. This file answers the second question: **where
does a given kind of implementation live?**

Cross-cutting correctness rules stay in `CLAUDE.md`; codegen/discovery/tooling
internals stay in `_docs/INTERNALS.md`.

## Package map

| Path | Role |
|---|---|
| `riko/__init__.py` | stable application facade; re-exports the supported `riko` surface rather than owning implementations |
| `riko/_package.py` | package/version metadata classified with the base layer |
| `riko/base/` | bottom-layer primitives shared across the package: constants, path/location helpers, logging, strings/iterators/date utilities, exceptions, source formatting, and the private API-surface declaration |
| `riko/types/` | static contracts: streams/items, module configs, options, compiler/pipeline/resource/I/O types, enums, wrappers, sentinels, guards |
| `riko/coercion/` | conversion and normalization: casts, `DynamicConf`, generated objconf types, mapping/objectification, date/dataclass coercion, graph/freeze helpers |
| `riko/bado/` | async backend selection plus async itertools/utilities; I/O no longer lives here |
| `riko/definitions/` | immutable/declarative contracts for modules, resources, targets, and writes |
| `riko/io/` | sync/async URL and file I/O, serialization, and re-encoding |
| `riko/parsing/` | config parsing, `DotDict`, and document/XML/HTML parsing |
| `riko/rss/` | RSS/Atom discovery, parsing, and entry normalization |
| `riko/runtime/` | executable orchestration: collections, compiler, pipeline resolution, registry, pub/sub, subpipes, execution resources/context, and write sessions |
| `riko/modules/` | built-in pipe implementations plus decorators, preparation, metadata, inference, looping, and generated discovery names |
| `riko/ext/` | supported extension-author facade and extension codegen/name helpers; architecturally shares the `modules` layer |
| `riko/cli/` | command implementations, generators, documentation checks, and import-contract linters |
| `riko/data/` | bundled package data used by runtime helpers; not an implementation layer |

## Base

| Path | Role |
|---|---|
| `riko/base/_api_surface.py` | **private** declaration of `STABLE`, `EXTENSION`, `TYPES`, and private surface name sets; source for generated blocks in `_docs/API_SURFACE.md` |
| `riko/base/exceptions.py` | exception hierarchy rooted at `RikoError`; stable root exceptions are re-exported from `riko` |
| `riko/base/_paths.py` | package/repository path constants and filesystem helpers used by runtime and CLI code |
| `riko/base/_dateutils.py` | low-level date/time conversion helpers kept below coercion/runtime code |
| `riko/base/_iterutils.py` | generic iterator helpers that do not belong to pipeline execution |
| `riko/base/_source_format.py` | shared source-formatting helper used by generators |
| `riko/base/{_constants,_imports,_locations,_logging,_strutils}.py` | small base utilities; keep them free of upward package dependencies |
| `riko/base/{currencies,locations,warnings}.py` | shared domain/reference helpers that sit at the bottom of the import graph |

## Types and coercion

| Path | Role |
|---|---|
| `riko/types/modules.py` | hand-maintained module configuration contracts; source input for config code generation |
| `riko/types/_module_ids.py` | **generated** `ModuleId`/`LoopableModuleId` literals; regenerate with `gen-names` or `manage codegen --names` |
| `riko/types/_streams.py` | core `Item`/`Items`/stream aliases and async stream contracts |
| `riko/types/_compiler.py` + `riko/types/_pipeline.py` | compiler/DAG and parsed-pipeline structural contracts |
| `riko/types/_resource.py` | resource factory/kind type contracts used by definitions and execution |
| `riko/types/_enums.py` | shared enums and enum-like aliases, including serialization format typing |
| `riko/types/_io.py` | path/closeable I/O contracts, not executable I/O |
| `riko/types/_wrappers.py` | decorator wrapper typing; upward references needed only for typing stay behind `TYPE_CHECKING` |
| `riko/types/_targets.py` | base `Target` protocol (a destination keyed by `backend`) plus the `SupportsRead`/`SupportsWrite`/`SupportsActions` capability protocols concrete adapters implement; `SupportsWrite.capabilities` references `WriteCapabilities` behind `TYPE_CHECKING` |
| `riko/coercion/_configs.py` | **generated** `<Name>Objconf` parse-time config classes; edit `riko/types/modules.py`, then run `gen-config` or `manage codegen --config` |
| `riko/coercion/_dynamic_conf.py` | hand-maintained `DynamicConf` base used by generated objconf classes |
| `riko/coercion/cast.py` | public coercion/casting implementation used by parsing/modules |
| `riko/coercion/_graph.py` | generic graph helpers, including topological sorting and descendant traversal reused by the architecture linter |
| `riko/coercion/{_dates,_dataclass,_freeze,_mapping,_objectify,_sequences}.py` | focused conversion/normalization helpers |

## Async and I/O

| Path | Role |
|---|---|
| `riko/bado/__init__.py` + `riko/bado/_backend.py` | optional AnyIO backend selection and guarded async runtime surface |
| `riko/bado/itertools.py` | async iterator helpers (`async_map`, streaming map/merge/reduce helpers, etc.) |
| `riko/bado/_util.py` | async utility helpers not tied to transport/file I/O |
| `riko/io/_async.py` | async URL/file I/O (`async_url_open`, `async_write`, `get_async_temp_file`); owns the async-handle lifecycle details that previously lived under `bado` |
| `riko/io/_sync.py` | synchronous URL/file open/read helpers |
| `riko/io/_serialization.py` | stream serialization/export conversion helpers |
| `riko/io/_reencode.py` | byte/text re-encoding utilities |
| `riko/io/__init__.py` | narrow I/O facade; stable async I/O names are promoted through `riko` |

`async_url_open` remains an awaitable/async-context-manager handle. Call sites that
return lazy parsers must keep the handle alive until iteration completes; do not
replace a close-on-iteration path with an `async with` that exits before the lazy
iterator is consumed.

## Parsing and RSS

| Path | Role |
|---|---|
| `riko/parsing/_dotdict.py` | `DotDict`, the case-insensitive nested mapping used for pipe items |
| `riko/parsing/config.py` | parse-time module configuration normalization and casting |
| `riko/parsing/documents.py` | XML/HTML/document parsing (`xml2etree`, `LinkParser`, etc.) |
| `riko/rss/discovery.py` | feed discovery helpers |
| `riko/rss/parsing.py` | RSS/Atom parser coordination |
| `riko/rss/entries.py` | feed-entry normalization |

## Definitions and execution resources

| Path | Role |
|---|---|
| `riko/definitions/modules.py` | immutable `ModuleDefinition` contract used by built-ins, registry entries, and discovery |
| `riko/definitions/_resource_types.py` | resource-definition aliases shared by declarative binding code; any runtime references here are type-only |
| `riko/definitions/_resources.py` | resource binding normalization, factory classification, `ResourceView`, and definition-side binding helpers |
| `riko/definitions/_targets.py` | the built-in `FileTarget` write adapter (carrying `backend = Backends.FILE`) and write preparation/validation (`resolve_target`/`resolve_format`/`build_write`); the base target protocols live in `riko/types/_targets.py` |
| `riko/definitions/_write.py` | `WriteMode`, `WriteResult`, `WriteOperation`, `WriteCapabilities`, `PreparedWrite`, and sync/async write-session protocols |
| `riko/runtime/context.py` | immutable execution `Context`; resource bindings derive new contexts rather than mutating one in place |
| `riko/runtime/_resources.py` | concrete `Resource` hierarchy and one-shot/reusable lifecycle execution; this file and `context.py` form the architecture's explicit `execution` sublayer |

The definition/execution split is intentional: descriptions stay immutable and
reusable; mutable open/close/session state belongs to execution-owned objects.

## Runtime

| Path | Role |
|---|---|
| `riko/runtime/collections.py` | `SyncPipe`/`AsyncPipe`/`SyncCollection`/`AsyncCollection`; `Formats`, `export()`, `list_formats()`, `write`/`sink`, pipeline lifecycle and pool ownership |
| `riko/runtime/_compile.py` | DAG/JSON parsing and compilation (`build_pipeline`, `compile_pipe`, `build_pipe_def`, dependency extraction) |
| `riko/runtime/_compile_repr.py` | Python-source representation helpers used by compiler/codegen paths |
| `riko/runtime/_pipelines.py` | pipeline lookup/loading support |
| `riko/runtime/_resolver.py` | module/pipeline resolution orchestration |
| `riko/runtime/_registry.py` | generic `Registry[T]` base shared by the module and target registries: the three-tier runtime→entry-point→built-in lifetime + entry-point discovery/loading scaffolding; subclasses supply a `_key` hook so `register` stores one self-keying entry |
| `riko/runtime/_module_registry.py` | `ModuleRegistry` + process-global `module_registry`/`register_module`/`reset_module_registry`; keyed by `ModuleDefinition.resolved_name`, built-in modules resolved lazily per name, entry points under `riko.modules` |
| `riko/runtime/_target_registry.py` | private `TargetRegistry` + `target_registry`/`register_target`/`reset_target_registry`; stores adapter classes keyed by `backend` and resolves a `Backends` to its adapter class (built-in `FileTarget`), entry points under `riko.targets` |
| `riko/runtime/_importutils.py` | dynamic import helpers; string-constructed imports are intentionally invisible to the static AST dependency graph |
| `riko/runtime/_subpipe.py` | nested/sub-pipeline execution helpers |
| `riko/runtime/_write_session.py` | concrete sync/async write-session acquisition, incremental/framed delivery, finalize/abort/teardown semantics |
| `riko/runtime/_pubsub/` | sync/async pub/sub hubs and message types; mutable hub state is isolated via `contextvars` |
| `riko/runtime/templates/` | compiler templates for generated sync/async Python pipelines |

Pipes are one-shot execution objects. Pool ownership remains explicit: borrowed
pools stay open, while a pipeline-created pool is closed by its owner. Write and
sink execution use the same prepared write/session contracts; terminality is a
collection-consumption concern, not a second write model.

## Modules and extension surface

| Path | Role |
|---|---|
| `riko/modules/<name>.py` | one built-in pipe implementation per module |
| `riko/modules/__init__.py` | intentionally narrow module-development facade; implementation internals should import their defining private modules, not round-trip through the facade |
| `riko/modules/_decorators.py` | `processor`/`operator`/`splitter` machinery and sync/async wrappers |
| `riko/modules/_prepare.py` | immutable `PreparedModule` construction and call-site option/resource preparation |
| `riko/modules/_metadata.py` | runtime module catalog/metadata discovery |
| `riko/modules/_derive.py` + `riko/modules/_inference.py` | subtype/loopability/return-kind derivation kept isolated from higher extension/runtime surfaces |
| `riko/modules/_loop.py` | explicit loop module execution, distinct from processors' implicit iterable mapping |
| `riko/modules/_names.py` | **generated** `Modules`/`Sources`/`Transforms`/`Sinks` discovery enums; never hand-edit |
| `riko/ext/decorators.py` + `riko/ext/protocols.py` | supported module-author decorator/protocol surface |
| `riko/ext/registry.py` | supported registration surface (`register_module`/`reset_module_registry`/`ModuleRegistry`) re-exported over the private runtime module registry |
| `riko/ext/_names.py` | `ModuleName`, normalization, category derivation, and sink-name criteria |
| `riko/ext/codegen.py` | shared module-catalog codegen helpers |
| `riko/ext/config.py` | supported extension configuration helpers |

## CLI and generators

| Path | Role |
|---|---|
| `riko/cli/manage.py` | thin Click command composer only |
| `riko/cli/_lint.py` | `manage lint`, additive selectors, `--all`, and nested `lint imports` registration |
| `riko/cli/_import_graph.py` | pure-AST import scanner; classifies module/local/type-only imports without importing riko |
| `riko/cli/_lint_import_architecture.py` | package-layer DAG, module-to-layer mapping, architecture report/validation |
| `riko/cli/_lint_canonical_imports.py` | canonical-definition import contract |
| `riko/cli/_lint_relative_imports.py` | sibling-relative import contract |
| `riko/cli/_import_commands.py` | selector-based `manage lint imports` command and shared import-check runner |
| `riko/cli/_codegen.py` | selector-based `manage codegen`; defaults to config and supports additive `--config`/`--names`/`--pipes`/`--api` plus `--all` |
| `riko/cli/_gen_config.py` | generates `riko/coercion/_configs.py` from `riko/types/modules.py` |
| `riko/cli/_gen_names.py` | generates `riko/modules/_names.py` and `riko/types/_module_ids.py` |
| `riko/cli/_gen_pipelines.py` | regenerates compiled pipeline fixture trees |
| `riko/cli/_gen_api_surface.py` | regenerates marked name blocks in `_docs/API_SURFACE.md` from `riko/base/_api_surface.py` |
| `riko/cli/{compile,convert_dag,runpipe,benchmark}.py` | standalone console-script implementations |
| `riko/cli/{_build,_docs,_docstyle,_release,_test}.py` | private `manage` command helpers grouped by reason to change |

Use `_docs/gameplans/dependency-layers.md` when deciding **which package** should own
new code. Use this file when deciding **which existing module** is the closest home.
