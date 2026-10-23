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
| `riko/base/` | bottom-layer primitives shared across the package: constants, path/location helpers, logging, strings/iterators/date/graph utilities, exceptions, source formatting, and the private API-surface declaration |
| `riko/types/` | static contracts: streams/items, module configs, options, compiler/pipeline/resource/I/O types, enums, wrappers, sentinels, guards |
| `riko/coercion/` | conversion and normalization: casts, `DynamicConf`, generated objconf types, mapping/objectification, date/dataclass coercion, canonical-identity helpers |
| `riko/bado/` | async backend selection plus async itertools/utilities; I/O no longer lives here |
| `riko/definitions/` | immutable/declarative contracts for modules, resources, targets, writes, and the `Workflow` graph with its loading/saving, including the `Context` (`_context.py`) and `Resource` (`_resource_definition.py`) definitions |
| `riko/io/` | sync/async URL and file I/O, serialization, and re-encoding |
| `riko/parsing/` | config parsing, `DotDict`, and document/XML/HTML parsing |
| `riko/rss/` | RSS/Atom discovery, parsing, and entry normalization |
| `riko/execution/` | the explicit execution layer: execution planning, one-shot sync/async executions, lifetime primitives, sync/async stream adaptation, execution-local resource acquisition and owned-resource teardown, event sink |
| `riko/runtime/` | executable orchestration: export, compiler, stored-workflow resolution, registry, pub/sub, the pipeline runners, and write sessions |
| `riko/modules/` | built-in pipe implementations plus decorators, preparation, metadata, inference, looping, and generated discovery names |
| `riko/ext/` | supported extension-author facade and extension codegen/name helpers; architecturally shares the `modules` layer |
| `riko/cli/` | command implementations, generators, documentation checks, and import-contract linters |
| `riko/data/` | bundled package data used by runtime helpers; not an implementation layer |

## Base

| Path | Role |
|---|---|
| `riko/base/_api_surface.py` | **private** declaration of `STABLE`, `EXTENSION`, `TYPES`, and private surface name sets; source for generated blocks in `_docs/API_SURFACE.md` |
| `riko/base/exceptions.py` | exception hierarchy rooted at `RikoError` and the warnings rooted at `RikoWarning`; stable root exceptions are re-exported from `riko` |
| `riko/base/_config.py` | static project policy (layer DAG, port/output tokens, `SINK_NAMES`, `SUBPIPE_TYPE`), `get_worker_cnt` worker-pool sizing, and the frozen `Settings` with `RIKO_*` overrides (`node_threads` from `RIKO_NODE_THREADS`, the `shipped_call_cache_size`/`parsed_date_cache_size` cache bounds among them) |
| `riko/base/_paths.py` | package/repository path constants (`ROOT_DIR`, `PACKAGE_DIR`, `TESTS_DIR`) and filesystem helpers used by runtime and CLI code |
| `riko/base/_dateutils.py` | low-level date/time conversion helpers kept below coercion/runtime code |
| `riko/base/_iterutils.py` | generic iterator helpers that do not belong to pipeline execution, including `map_values`, `multiplex` (round-robin interleave), and `sort_stably` (hash-seed-independent order, `repr` fallback for mixed types) |
| `riko/base/_graph.py` | generic graph helpers (stdlib `graphlib` for topological order, `networkx` for strongly connected components, descendants, and transitive reduction) over successor mappings: `edges_to_graph(edges, nodes=)` (keeps edge-less nodes) and `reverse_graph`; `native_topological_sort` (strict flat order) and `topological_sort` (always tuples: one-node groups when acyclic, strongly connected components on a cycle unless `strict`; `key` orders ready nodes) and `cyclic_nodes` built on it; `leaves`; `descendants`; `gen_redundant_edges` (transitive reduction); `freeze_graph`. Shared by the graph index, workflow normalization's lone-leaf default output, execution planning, and the architecture linter |
| `riko/base/_source_format.py` | shared source-formatting helper used by generators |
| `riko/base/_typing.py` | runtime type-hint helpers: `resolve_type_hints` (PEP 563 annotations with supplementary namespaces), `resolve_alias` (follows a `type` alias chain), and `gen_union_members` (flattens aliases, unions, and `Annotated` into arms), shared by return-kind inference and `require_from_form` |
| `riko/base/{_constants,_imports,_logging,_strutils}.py` | small base utilities; keep them free of upward package dependencies; `_logging` holds the one pygogo configuration (`get_logger`/`set_log_level`) |
| `riko/base/{currencies,locations}.py` | shared domain/reference helpers that sit at the bottom of the import graph |

## Types and coercion

| Path | Role |
|---|---|
| `riko/types/modules.py` | hand-maintained module configuration contracts; source input for config code generation; `ModuleMetadata` and its derived `provider` (`get_module_provider`: first dotted segment, `BUILTIN_PROVIDER` when unqualified); also the call options: the frozen `CallOptions` record `ModuleNode.options` stores (`from_raw`, `kwargs`), its keyword form `RawCallOptions` (emit/assign/field/count), and the `ContextOverrides` `TypedDict` (mode/inputs/test, mirroring `Context.replace`); plus the conf guards `require_module_conf`/`require_conf`, kept out of `__all__` |
| `riko/types/_module_ids.py` | **generated** `ModuleId`/`LoopableModuleId` literals plus the `BUILTIN_MODULE_IDS` set (module registry + attribute chaining read it); regenerate with `gen-names` or `manage codegen --names` |
| `riko/types/_streams.py` | core `Item`/`Items`/stream aliases and async stream contracts |
| `riko/types/_geo.py` | location and currency record contracts (`Region`, `CurrencyCode`, `IPAddress`, `Location`, `AnyLocation`) the `riko/base/{currencies,locations}.py` helpers return and `_streams` item typing accepts |
| `riko/types/_workflow.py` | Workflow v2 structural contracts (endpoints, port grammar, node/edge discriminants) plus `GraphEdge` and `GraphIndex`, the one topology interpretation `Workflow.index` builds and `Workflow.validate()`/execution planning both read. `GraphIndex` takes only node ids, edges, and outputs (`Endpoint`s); every other attribute is lazily derived from them using `riko/base/_graph.py` helpers, so a hand-built index is consistent and frozen |
| `riko/types/_pipedef.py` | the `PipeDef`/`PipeDefLike`/`Wire` shapes (the pipe definition `migrate_v1_to_v2` reads), the `is_pipe_id` stored-workflow name guard, `PipeDag`/`DagModule` for `Workflow.parse`, and the loop `CountValues`/`EmbedKwargs` contracts; `PipeDag`/`PipeDef`/`PipeDefLike` are re-exported on `riko.types` (TYPES tier); `riko/types/_pipeline.py` was deleted with the v1 compiler at cutover step 5 (2026-10-03) |
| `riko/types/_collections.py` | immutability (`FrozenDict`, `freeze`/`freeze_json`/`thaw`), the `require_*`/`narrow_*`/`def_from_*` narrowing family (`require_from_form` for any type form, `require_from_keys` as the key check behind the TypedDict and attrs guards) and the attrs converters built on it, and `require_binding`, which checks node resource bindings |
| `riko/types/_values.py` | the item/value type aliases pipe modules accept and return (`BasicArg`/`BasicReturn`, `RikoDict`/`RikoList`/`RikoValue`, the `Stringy*` family, `Inputs`) |
| `riko/types/_resource.py` | resource factory type contracts, the generic factory guards (a `contextmanager`/`asynccontextmanager` factory is recognized by the decorator's helper code in its `__wrapped__` chain), the `ResourcePlan` tagged union (`ExternalPlan`/`OwnedPlan`/`ValueFactoryPlan`/`SyncLifecyclePlan`/`AsyncLifecyclePlan`, exported from `riko.types`) with `build_factory_plan`/`build_lifecycle_plan`, `ResourceStrategy`, and `ResolvedValue` |
| `riko/types/_guards.py` | guards over generic shapes only (mappings, sequences, callables, protocol structural checks via `isinstance_strict`, sentinels, conf shapes); a guard narrowing a specific contract lives in that contract's module |
| `riko/types/_enums.py` | shared enums and enum-like aliases, including serialization format typing and the `DocumentShape` (`dag`/`v1`/`v2`) a workflow input is read as |
| `riko/types/_events.py` | the `EventSink` protocol a running execution reports to (exported from `riko.types`); `riko/execution/_execution.py` keeps the no-op default sink |
| `riko/types/_io.py` | path/closeable I/O contracts plus the closeable guards (`is_sync_closeable`/`is_async_closeable`/`is_closeable`), not executable I/O; the file-like aliases live in `riko/io/_filelike.py` |
| `riko/types/_wrappers.py` | decorator wrapper typing (`WrapperMeta` is the stamped discovery metadata; every `ModuleWrapper` adds a `prepare: Preparer`, i.e. `(*extras: ExtraName, conf=, **options) -> PreparedCall`), the `PreparedCall`, `Preparer`, and `Dispatcher` protocols, the `ExtraName`/`ExtraNames` aliases, the `is_wrapper_meta` guard and `require_wrapper_meta` (both narrow to `WrapperMeta`), `prepare_call`/`build_call` (which prepare a plain wrapper such as a stored-workflow pipe or a sync/async adapter), `stamp_wrapper_meta` (which attaches a default `prepare`), plus the wrapper guards `is_subpipe`/`is_splitter`/`require_single_output`; upward references needed only for typing stay behind `TYPE_CHECKING` |
| `riko/types/_target_protocols.py` | base `Target` protocol (an endpoint keyed by `backend`) plus the `SupportsRead`/`SupportsWrite`/`SupportsActions` capability protocols concrete adapters implement; `SupportsWrite.capabilities` references `WriteCapabilities` behind `TYPE_CHECKING` |
| `riko/coercion/_configs.py` | **generated** `<Name>Objconf` parse-time config classes; edit `riko/types/modules.py`, then run `gen-config` or `manage codegen --config` |
| `riko/coercion/_dynamic_conf.py` | hand-maintained `DynamicConf` base used by generated objconf classes |
| `riko/coercion/cast.py` | public coercion/casting implementation used by parsing/modules |
| `riko/coercion/{_dates,_dataclass,_canonical,_mapping,_objectify,_sequences}.py` | focused conversion/normalization helpers |

## Async and I/O

| Path | Role |
|---|---|
| `riko/bado/__init__.py` + `riko/bado/_backend.py` | optional AnyIO backend selection and guarded async runtime surface |
| `riko/bado/itertools.py` | async iterator helpers (`async_map`, streaming map/merge/reduce helpers, etc.) |
| `riko/bado/_util.py` | async utility helpers not tied to transport/file I/O |
| `riko/io/_async.py` | async URL/file I/O (`async_url_open`, `async_write`, `async_get_temp_file`); owns the async-handle lifecycle details that previously lived under `bado` |
| `riko/io/_sync.py` | synchronous URL/file open/read helpers |
| `riko/io/_serialization.py` | stream serialization/export conversion helpers; records are `thaw`ed to plain dicts first, and `json`/`jsonl` use riko's `records2json` (meza's `CustomEncoder` subclassed so sets serialize as sorted arrays, the `_reencode.py` patching pattern) |
| `riko/io/_reencode.py` | byte/text re-encoding utilities |
| `riko/io/_filelike.py` | file-like and opener aliases (`IOFileLike`, `BinaryFileLike`, `StringFileLike`, `FileLike`, `Opener`, `IOFileLikeType`); they name `riko.io` handle classes, so they live with the I/O layer rather than in `riko/types` |
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
| `riko/rss/feeds.py` | RSS/Atom feed parsing (`parse_rss`) and feed-entry normalization (`augment_entries`, `resolve_date`) |

## Definitions and execution resources

| Path | Role |
|---|---|
| `riko/definitions/_module_definition.py` | frozen attrs `ModuleDefinition` used by built-ins, registry entries, and discovery: derived `name` over `declared_name`; `from_module` reads a module's `pipe`/`async_pipe`, name, and docstring summary once |
| `riko/definitions/_nodes.py` | the closed node families (`ModuleNode`/`CallableNode`/`ReadNode`/`WriteNode`/`CacheNode`/`ActionNode`/`SubscribeNode` over `Node`) and edge families (`StreamEdge`/`PublishEdge`), their field converters, and `get_family_edges`; nodes carry declarative intent only. `CallableNode` (what `Pipeline.map` builds) holds a live `fn` compared by identity, so it is the one family with no document form: `validate_document_nodes` refuses it for serialization and re-normalization. `RunnableNode` (`ModuleNode \| CallableNode`) is what execution accepts (`require_runnable_node`) |
| `riko/definitions/_normalize.py` | the single shorthand normalization boundary: `build_workflow_fields` turns a flexible workflow mapping into the strict `WorkflowFields` a `Workflow` is built from, `build_raw_graph` reads a `Workflow` back into that mapping, and `resolve_port` owns the port shorthand; it returns data and builds no `Workflow` |
| `riko/definitions/_migrate.py` | expansion of the terser listings into a `RawWorkflow`: `parse_dag_graph` (`PipeDag`) and `migrate_pipe_def` (`PipeDef`, which warns), with the private v1 key/port/write-mode translation helpers; returns data only |
| `riko/definitions/_serialize.py` | byte-stable `serialize_graph` and shape-aware `parse_graph`; the shape guards `is_raw_workflow`/`is_pipedeflike`/`is_pipedag` and `get_document_shape` (a `DocumentShape`) detect which of the three readable shapes a JSON input holds |
| `riko/definitions/_workflow_definition.py` | the immutable `Workflow` model (converters, the cached `index`, `module_nodes`/`callable_nodes`/`runnable_nodes`, and `embeds` views, `validate`, `validate_document_nodes`, the `require_executable`/`require_runnable_only(what)` preconditions, compact repr, `get_node_id` for conflict-free `<name>-<n>` ids, and `with_node`, which appends a node, re-points the default output to it, and declares the Context resources it binds (order-stable, de-duplicated) so a binding chain validates) and its loader API: `Workflow.parse(document, shape=)` (any shape, validated), `Workflow.load(path)`, and `flow.serialize()`; also the functions `normalize_workflow` and `migrate_v1_to_v2` |
| `riko/definitions/_composition.py` | the immutable, composable `PipelineDefinition[T]` around a `Workflow`: chaining, writes, context/resources/execution settings, and source seeding each derive a new definition; running belongs to `riko/runtime/_pipeline.py`. `map[R]` appends a `CallableNode` and retypes the definition; chaining appends through `Workflow.with_node` with ids from `Workflow.get_node_id`; `|` accepts a single-module or single-callable source-less template |
| `riko/definitions/_settings.py` | frozen `ExecutionSettings` and `DEF_EXECUTION_SETTINGS`, the run settings `Pipeline.with_execution(...)` derives, with the `SyncPolicy`/`AsyncPolicy` records its cached `sync_policy`/`async_policy` resolve them into; field checks are local `require_*` guards attached with `validator_from_require` |
| `riko/definitions/_context.py` | immutable `Context` definition (frozen attrs, identity equality, converters freeze `inputs`/`resources` into `FrozenDict`); resource bindings derive new contexts rather than mutating one in place |
| `riko/definitions/_resource_definition.py` | the frozen attrs `Resource` definition (identity equality; stores `plan`/`credential`/`lazy`, with `strategy`/`async_native`/`external`/`value` derived from the plan) behind the `OneShotResource`/`ReusableResource` markers (all three on the stable `riko` surface), plus the resource-definition aliases (`ResourceDefinition`, `ReusableResources`, `ResourcesLike`, `Values`); it declares a resource and never tears one down (node bindings are checked by `require_binding` in `riko/types/_collections.py`) |
| `riko/definitions/_targets.py` | the built-in `FileTarget` write adapter (carrying `backend = Backends.FILE`) and write preparation/validation (`normalize_target`/`resolve_format`/`build_write`); the base target protocols live in `riko/types/_target_protocols.py` |
| `riko/definitions/_write.py` | `WriteMode`, `WriteResult`, `WriteOperation`, `WriteCapabilities`, `PreparedWrite`, and sync/async write-session protocols |
| `riko/execution/_execution.py` | the shared base of the private one-shot executions: `_BaseExecution[S]` (generic over `ExitStack`/`AsyncExitStack`), which holds only what runs without awaiting — context/settings, the closed guard, sync `enter_context` and `callback`, cleanup-error reporting, the resolved-resource cache, `_require_bindings`, the shutdown report, and one shared core, `_resolve_node_inputs` (port dispatch plus the seed rule, with an `as_stream` adapter turning the seed into each execution's stream kind); plus the acquisition records, the `_require_source` guard, `_asyncify_call`, `DEFAULT_SEED`, and the no-op default event sink; everything that awaits stays in each execution class, never a shared strategy/template hierarchy |
| `riko/execution/_sync_execution.py` | `SyncExecution`: the exit stack, the lazily started blocking portal for async-only components, the run's one worker pool, the exit-stack unwind followed by one shutdown report (first close only), execution-local resource `acquire` with single-flight memoization, and the node runners that build each output's sync stream |
| `riko/execution/_async_execution.py` | `AsyncExecution` (no async task group until R7 fan-out needs one): the async exit stack, the shielded exit-stack unwind within the shutdown timeout (`shutdown_timeout`, defaulted from the execution settings by `_timeout`) followed by one shutdown report, the event loop's node-thread budget (`_ThreadBudget` on a `RunVar`, sized by `RIKO_NODE_THREADS`), from which `_reserve_threads` takes every thread `ExecutionPlan.get_thread_demand` says a run may hold before it reads anything and holds it as a `_Reservation` until `_ReleasingStream` ends or closes the output stream, execution-local `aacquire` with single-flight memoization (`_WorkerContext` runs a blocking sync context manager's entry and exit on a worker thread), the node runners that build each output's async stream, and the sync-under-async bridge (`_run_sync_node`, `_bridge_inputs`) |
| `riko/execution/_adapt.py` | the sync/async boundary helpers both executions share: the `require_stream`/`require_async_stream` node-output boundary (narrowing earned by the `is_splitter` guard on the pipe's declared type, never by reading its output), `async_drain(source, call)` (an async stream re-exposed as a lazy sync iterator — the portal drain and the worker-side upstream reader differ only in `call`), `pull_stream(...)` (a sync iterator re-exposed as a lazy async stream), and the `adapt_embed`/`async_adapt_embed` sync/async loop-embed wrappers, which preserve the embed's discovery metadata so the loop machinery sees a native embed; `select_embed(embed, host_isasync=, run_sync=, drain=)` picks a loop embed's native callable or wraps the callable from the sync or async counterpart with the caller's adapters |
| `riko/execution/_prepared.py` | `ExecutionPlan` (a `Workflow` plus resolved `modules`/`embeds` keyed by node id; `index` and the runnable-node and loop-embed views are the workflow's own cached `index`/`runnable_nodes`/`embeds`, and `nodes` is a `cached_property`, so no node is narrowed or stored twice; its `validate()` is the one validation point, running the graph checks, the fan-out guard, and the runnable-node check, so a plan built by hand holds the same guarantees) and its constructor `ExecutionPlan.from_workflow(flow, dispatcher)`, which calls any `Dispatcher` (runtime's `ResolverDispatcher` satisfies it); the run-time plan guards `ExecutionPlan.require_output` (a default-port workflow output's endpoint) and `require_seed_target` (the one open input a seed feeds), with `gen_build_order`/`get_thread_demand` walking the output's ordered `index.required` nodes, and `require_default_output_port`, which refuses a non-default output port until multi-output delivery runs; `PreparedNode` (graph `ModuleNode` or `CallableNode` — the `RunnableNode` tagged union — + `ResolvedModule` + optional embed `ResolvedModule` + its `incoming` edges, from which the cached `extras` derives the keyword names — named ports, `others`, `resources`, `embed`) whose cached `sync_interface`/`async_interface` (`PreparedInterface`: pipe, prepared stream call, the per-item `item_call` the mapped paths and the process-safety check use — the same call for a module node, a never-splitting one-item call for a callable node — and whether it is native) prepare each pipe once per plan, falling back to the sync or async counterpart's pipe when one is missing; `ResolvedModule.select_sync()`/`select_async()` return the native callable, else the sync or async counterpart's, touching no registry; `ResolvedModule.is_async_pipe(pipe)` narrows it by slot identity (never the wrapper's `isasync`, which undecorated callables lack), so callers never cast |
| `riko/execution/_resource_acquisition.py` | `call_factory`/`build_context_manager`: produce a value or context manager from a passive `Resource.plan` record (the records in `riko/types/_resource.py` carry no acquisition behavior) |
| `riko/execution/_resource_teardown.py` | `close_resource`/`aclose_resource`, the owned-resource teardown the executions register; acquisition itself `match`es on `Resource.plan` (records in `riko/types/_resource.py`) |
| `riko/execution/_resource_view.py` | `ResourceView`, the resolved resources an execution passes a module as `resources=`; module wrappers pass it through untouched and never acquire anything themselves |
| `riko/execution/_pools.py` | the synchronous worker-pool mechanics: `_PoolLifetime` owns the one pool `SyncExecution` creates (closing it on success, terminating it on error or early close) and maps items through bounded `apply_async` windows instead of `Pool.imap`, which deadlocks when chained on one pool; worker sizing is `get_worker_cnt` in `riko/base/_config.py`, and the `Executor` enum lives in `riko/types/_enums.py` |
| `riko/execution/_concurrency.py` | per-item mapping both executions share: `run_item`, `build_item_call` (the process executor ships each mapped node's call pickled once, cached per worker by `run_shipped_item`), and `require_process_safe`; the `SyncPolicy`/`AsyncPolicy` records are `ExecutionSettings.sync_policy`/`async_policy` |

The definition/execution split is intentional: descriptions stay immutable and
reusable; mutable open/close/session state belongs to execution-owned objects.

## Runtime

| Path | Role |
|---|---|
| `riko/runtime/_export.py` | `Formats` (the serialization-format enum), `export()`, and `list_formats()`; the v1 `SyncPipe`/`AsyncPipe`/`SyncCollection`/`AsyncCollection` classes were deleted at v1-cutover step 4 (2026-10-02) — `Pipeline` in `riko/runtime/_pipeline.py` is the execution surface, and the pool/executor mechanics live in `riko/execution/_pools.py` |
| `riko/runtime/_pipeline.py` | the STABLE runnable `Pipeline`: subclasses `PipelineDefinition` (`riko/definitions/_composition.py`, which owns all composition) and adds only `__iter__`/`__aiter__`/`first`/`afirst`, each building a fresh execution plan and one-shot execution, plus a `map` override that narrows the return to `Pipeline[R]` (`Self` cannot change its type parameter) |
| `riko/runtime/_run.py` | `run_pipeline`/`arun_pipeline`, the sync/async pipeline runners: each builds an execution plan and runs it in a fresh one-shot execution; it imports nothing from `riko/runtime/`, so `_pipeline.py` and `_workflow_pipes.py` both use it |
| `riko/runtime/_compile.py` | the Workflow v2 code generator behind STABLE `compile_workflow` and `compile-workflow`: renders a workflow as a Python module of typed `<Name>RawConf` confs that runs through the canonical execution and whose pipe `build_workflow_pipes` tags as a stored workflow's pipe |
| `riko/runtime/_workflow_pipes.py` | the pipes that run a stored workflow: the `workflow(*, subtype, loopable, isasync)` decorator that tags a hand-written workflow module's pipe (`@workflow(subtype="source")`), `SubPipes`, and `build_workflow_pipes`, which builds a `Workflow`'s tagged sync/async pipes over the `Dispatcher` protocol; the tag is applied to a copy, never in place, so a registered module's pipe is never altered |
| `riko/runtime/_workflow_stores.py` | the stored-workflow stores: `WorkflowStore[T]` protocol, the module store (`ModuleStore`: `PackageStore` of `pipe_*` modules, `MappingStore`, `CompositeStore`) and the document store (`DocumentStore`: `DirectoryStore` whose `pipe_*.json` files are `WorkflowDocument`s (workflow documents) parsed into a `Workflow`) |
| `riko/runtime/_workflow_resolver.py` | `WorkflowResolver` + process-global `workflow_resolver`/`register_workflow_store`/`reset_workflow_resolver`; searches the module store and then the document store, building on the pipes and stores files; turns a document store's `Workflow` into a `ResolvedWorkflow` module over `build_workflow_pipes` |
| `riko/runtime/_resolver.py` | module/stored-workflow resolution orchestration |
| `riko/runtime/_registry.py` | generic `Registry[T]` base shared by the module and target registries: the three-tier runtime→entry-point→built-in lifetime + entry-point discovery/loading scaffolding; subclasses supply a `_key` hook so `register` stores one self-keying entry |
| `riko/runtime/_module_registry.py` | `ModuleRegistry` + process-global `module_registry`/`register_module`/`reset_module_registry`; keyed by `ModuleDefinition.name` (derived; the raw input is `declared_name`), built-in modules resolved lazily per name, entry points under `riko.modules` |
| `riko/runtime/_target_registry.py` | `TargetRegistry` + process-global `target_registry`/`register_target`/`reset_target_registry`; stores target classes keyed by `backend` and resolves a `Backends` to its target class (built-in `FileTarget`), entry points under `riko.targets` |
| `riko/runtime/_importutils.py` | dynamic import helpers; string-constructed imports are intentionally invisible to the static AST dependency graph |
| `riko/runtime/_write_session.py` | concrete sync/async write-session acquisition, incremental/framed delivery, finalize/abort/teardown semantics; no runtime importer today (tests only) — the write/action effect phase decides whether the `WriteNode` path reuses or replaces it |
| `riko/runtime/_pubsub/` | sync/async pub/sub hubs and message types; mutable hub state is isolated via `contextvars` |
| `riko/runtime/templates/` | source templates for workflow modules: `pyworkflow.txt`, the `Workflow` v2 generator template behind `_compile.py` |

Executions are one-shot. Each execution owns and closes the one worker pool it
opens. Every write uses the same prepared
write/session contracts.

## Modules and extension surface

| Path | Role |
|---|---|
| `riko/modules/<name>.py` | one built-in pipe implementation per module |
| `riko/modules/__init__.py` | intentionally narrow built-in module catalog facade (metadata types, `describe_module`, `get_module_metadata`); authoring contracts live on `riko.ext`; implementation internals should import their defining private modules, not round-trip through the facade |
| `riko/modules/_decorators.py` | `processor`/`operator`/`splitter` machinery and sync/async wrappers; a wrapper's `prepare` returns one of the call records `_PreparedProcessor`/`_PreparedOperator`/`_PreparedSplitter`, which share the generic attrs base `_PreparedCall[M]` (the decorator, wrapper, prepared module, and prepared options, plus `field`/`count`/`parser`) and implement the `PreparedCall` protocol |
| `riko/modules/_prepare.py` | immutable `PreparedModule` construction and call-site option/resource preparation; `PreparedModule` is a frozen record of plain values (name, merged conf, options, extras, defaults; all but the name default) whose `assign`/`emit` (read from the options), `is_conf_parsed`/`is_dynamic`/`static_conf`/`parsers`/`casters`/`static_casted` are cached derivations, so it pickles and the process executor can ship it |
| `riko/modules/_metadata.py` | the runtime module catalog and discovery: `list_modules` (filters by type/subtype/category/provider/loopability), `get_module_category`, `describe_module`, `get_module_metadata` read built-in and registered modules' decorator-set metadata |
| `riko/modules/_require.py` | `require_arg`/`require_conf_key`, the raise-on-missing guards for required pipe call arguments and conf keys; private, not on `riko.ext` |
| `riko/modules/_textops.py` | the pipe text operations: `substitute`/`multi_substitute`, `reduce_find`, `PARAMS`/`OPS`, `gen_name`, `INVALID_FILECHAR_PATTERN` |
| `riko/modules/_derive.py` + `riko/modules/_inference.py` | subtype/loopability/sequential-input/return-kind derivation kept isolated from higher extension/runtime surfaces |
| `riko/modules/_loop.py` | explicit loop module execution, distinct from processors' implicit iterable mapping |
| `riko/modules/_names.py` | **generated** `Modules`/`Sources`/`Transforms`/`Sinks` discovery enums; never hand-edit |
| `riko/ext/modules.py` | module-authoring extension point: defines `get_conf_type`; re-exports the decorators (`riko/modules/_decorators.py`), `ModuleDefinition`/`normalize_module_name` (`riko/definitions/_module_definition.py`), `ModuleRegistry`/`register_module`/`reset_module_registry` (`riko/runtime/_module_registry.py`), `DynamicConf`, `get_module_category`, module name/metadata types, and the wrapper protocols plus `PreparedCall` (`riko/types/_wrappers.py`) |
| `riko/ext/targets.py` | write-target extension point: re-exports `FileTarget` (`riko/definitions/_targets.py`), `WriteCapabilities` (`riko/definitions/_write.py`), `TargetRegistry`/`register_target`/`reset_target_registry` (`riko/runtime/_target_registry.py`), and the target protocols (`riko/types/_target_protocols.py`) |
| `riko/ext/workflows.py` | workflow extension point: re-exports the node/edge classes (`riko/definitions/_nodes.py`), `normalize_workflow`/`migrate_v1_to_v2` (`riko/definitions/_workflow_definition.py`), `register_workflow_store`/`reset_workflow_resolver` (`riko/runtime/_workflow_resolver.py`), and `Dispatcher` (`riko/types/_wrappers.py`) |
| `riko/ext/codegen.py` | the discovery-name and module-id generators: `enum_member_name`, `gen_catalog_entries`, `generate_module_names`, `generate_module_ids` |

## CLI and generators

| Path | Role |
|---|---|
| `riko/cli/manage.py` | thin Click command composer only |
| `riko/cli/_lint.py` | `manage lint`, additive selectors, `--all`, and nested `lint imports` registration; `--terms` scans the shipped-text roots in full and the as-built `_docs` files (`AS_BUILT_DOCS`) for banned phrases only |
| `riko/cli/_import_graph.py` | pure-AST import scanner; classifies module/local/type-only imports without importing riko |
| `riko/cli/_lint_import_architecture.py` | package-layer DAG, module-to-layer mapping, architecture report/validation |
| `riko/cli/_lint_canonical_imports.py` | canonical-definition import contract |
| `riko/cli/_lint_relative_imports.py` | sibling-relative import contract |
| `riko/cli/_import_commands.py` | selector-based `manage lint imports` command and shared import-check runner |
| `riko/cli/_codegen.py` | selector-based `manage codegen`; defaults to config and supports additive `--config`/`--names`/`--api`/`--tests` plus `--all` |
| `riko/cli/_gen_config.py` | generates `riko/coercion/_configs.py` from `riko/types/modules.py` |
| `riko/cli/_gen_names.py` | generates `riko/modules/_names.py` and `riko/types/_module_ids.py` |
| `riko/cli/_gen_api_surface.py` | regenerates marked name blocks in `_docs/API_SURFACE.md` from `riko/base/_api_surface.py` |
| `riko/cli/_gen_tier_index.py` | `manage codegen --tests`: generates each `tests/<tier>/__init__.py` index from its files' `Test<Subject>` classes |
| `riko/cli/_document.py` | shared JSON document front door for the console scripts: `read_document` and the `WorkflowDocument`-only `require_workflow` (the run-it-through-`build-workflow`-first guard for `run-pipe`/`compile-workflow`); `build-workflow` reads any shape through `Workflow.parse` |
| `riko/cli/{compile,build_workflow,runpipe,benchmark}.py` | standalone console-script implementations, all on `Workflow` v2: `build-workflow` is the one lenient converter, `compile-workflow` generates from `WorkflowDocument`s only, `run-pipe` runs a pipe script, a `WorkflowModule`, or a `WorkflowDocument`, `benchmark` times `Pipeline` and workflow execution |
| `riko/cli/{_build,_docs,_docstyle,_lint_basenames,_lint_bindings,_lint_deps,_lint_literals,_lint_terms,_logging,_release,_shipped_text,_test,_upgrade}.py` | private `manage` command helpers grouped by reason to change |
| `riko/cli/_lint_tests.py` | `manage lint --tests`: holds `tests/` to its layout (generated tier indexes current, every test in a `Test<Subject>` class, one owning file per subject, no private imports in `public/`, size advice) |
| `riko/cli/_coverage.py` | `manage test --ratchet`'s uncovered-line ceiling (`[tool.riko.coverage] uncovered` in `pyproject.toml`): fail above it, lower it on a gain; dev-only `manage` modules are in `[tool.coverage.run] omit`, console scripts are measured through subprocesses |

Use `_docs/gameplans/dependency-layers.md` when deciding **which package** should own
new code. Use this file when deciding **which existing module** is the closest home.
