# Workflow v1 cutover gameplan

> **Provenance.** Detailed execution checklist for the R4B clean-break cutover that retires the
> v1 pipe/compiler surface once the v2 `Pipeline` executes. The forward dependency order and the
> paired-deletion table remain owned by
> [implementation-sequence.md](implementation-sequence.md); this file sequences the cutover's
> concrete steps, per-step dependencies, and drift guards without changing that authority.
>
> **Status vocabulary.** Everything below is planned deletion/migration work. Nothing here is
> shipped until the owning step lands; each step is a separate commit gated by the full lint/test
> suite.

## Mission

Delete the v1 runtime surface — `SyncPipe`/`AsyncPipe`/collection classes and the v1
`PipeDef` (pipe definition)/wires compiler — in an ordered sequence where every deletion is preceded by the
migration that makes it safe. Per the pre-1.0 clean-break policy there are no deprecated
compatibility wrappers.

Three deliberate divergences from the paired-deletion table's "R4B cutover" row, recorded here so
the cutover session does not rediscover them:

- **`riko.modules.write` survives until R5C.** The v2 execution raises for non-`module` node
  families, so deleting the v1 `write` module before `WriteNode` executes would remove write
  capability outright. `SINK_NAMES` and the `Sinks` discovery bucket are tied to that same commit
  (step 6).
- **Offline `migrate_v1_to_v2` is kept.** It is the rescue path for serialized `PipeDef`s and may
  survive 1.0 per the R4A exit.
- **`split` is not executable between the cutover and R7 — accepted, not bridged.**
  `SyncPipe.split`/`AsyncPipe.split`, `tests/public/test_collections.py::test_split`, and the two
  split fixtures (`pipe_QMrlL_FS3BGlpwryODY80A`, `pipe_zKJifuNS3BGLRQK_GsevXg`) are the only
  executable split paths, and they go with the v1 surface. The v2 execution refuses a splitter node
  when its plan is built (by the module's declared type, before any upstream runs). Do not bridge
  the gap with an eager positional cascade delivery in the v2 execution: that reimplements the
  whole-source copy R7 replaces with execution-owned bounded branches
  ([fanout-topology.md §7](fanout-topology.md#7-split-is-streaming-fan-out)). Done at step 2: the
  two split fixtures survive as `WorkflowDocument`s (workflow documents), and their functional expectations (7 items /
  first title `[Weight] More parents think their overweight…`; 6 items / first title `Open
  researcher open course`) are strict-xfail acceptance tests in `tests/functional/test_basics.py`
  (`test_split`, `test_simplemath_1`) plus the strict-xfail probe-equivalence case in
  `tests/internal/test_workflow_fixtures.py`; R7 un-xfails them. GitHub issue #61 (v1 split routing by traversal order) is
  closed as superseded by this cutover plus R7.

## Step 0 — Gate

Prerequisites that must be true before any deletion commit:

- The v2 fluent surface is landed and green: `Pipeline.from_module(name, conf=...)`, `.pipe()`,
  attribute chaining, `|`/`__ror__` source seeding, and end-to-end `iter`/`aiter` execution with a
  seeded source.
- The v2 execution runs linear and fan-in module graphs (covered by
  `tests/internal/test_prepare_execution.py`).
- Coverage ownership is transferred, not dropped: the string-form/template chaining behavior
  historically owned by `tests/public/test_collections.py` is owned by
  `tests/public/test_pipeline_fluent.py` going forward. Snapshot any remaining v1-only coverage
  worth porting before its file is deleted.

## Step 1 — Migrate P10 executor/bounded mechanics out of `collections.py`

**Must land first; nothing deletes before this.** R4B's exit says migrate, not reimplement.

- Move `Executor`, `_POOLS`, `_PoolHandle`, `get_worker_cnt`, `get_chunksize`, and the
  bounded-parallel map machinery from `riko/runtime/collections.py` into a private execution
  home (e.g. `riko/execution/_pools.py`) so `with_execution(executor=..., concurrency=...,
  ordered=...)` can consume them later.
- Port the pool-ownership/lifecycle characterization tests alongside the code.
- Guards: the import-contract half of `manage lint --all` (the new module classifies into the
  `execution` layer), full test gate.
- As-built: `riko/execution/_pools.py` (`Executor`, `resolve_executor`, `get_worker_cnt`/
  `get_chunksize`, `PoolHandle` with `open_pool`/`borrow_pool`/`map(ordered)`); `SyncPipe`/
  `SyncCollection` consume it, `PoolScope` chain sharing stays with them and goes at step 4, and
  `listpipe` stays because it depends on `riko.coercion`, which the `execution` layer cannot import.
  Handle-level tests: `tests/internal/test_pools.py`; the pipe-level `TestPoolLifecycle` in
  `tests/public/test_collections.py` goes with the classes at step 4.

## Step 2 — Flip the generated-pipeline mechanism off v1

Blocks step 4. Generated `tests/pypipelines/pipe_*.py` bodies are `SyncPipe` chains, and the
pipeline resolver — the v2 execution's own subpipe path — loads them.

- Decide once: (a) regenerate the tree as v2 `Pipeline` code (`riko/cli/_gen_pipelines.py` emits
  v2; `manage codegen --pipes` regenerates), or (b) delete `tests/pipelines` (JSON) +
  `tests/pypipelines` (generated tree) + the generator, deferring subpipe-by-generated-module to
  orchestration.
- Either way, retire the serialized-`PipeDef` half of the pipeline resolver: `DirectoryStore` /
  `load_definition` in `riko/runtime/_pipelines.py` are the only in-tree `parse_pipe_def`
  consumers outside the compiler — delete them or re-point them at v2 `parse_document`.
- Update conftest store wiring and `PIPELINE_DIRS` (`riko/base/_config.py`).
- Guards: `manage codegen --pipes` drift, full test gate.
- As-built (2026-09-29, `b4850983`): neither (a) nor (b) — a third path chosen at the design
  checkpoint. `tests/pipelines/*.json` and `examples/pipelines/*.json` were rewritten as
  `WorkflowDocument`s (pretty-printed, sorted keys) and are run by the v2 execution;
  `DirectoryStore`/`load_definition` parse them with `parse_document` and return a `Workflow`.
  The generator, `codegen --pipes`, `gen-pipelines`, `PIPELINE_DIRS`, and both drift guards are
  gone. A covering set of `pypipelines/pipe_*.py` files stays as hand-maintained typed probes (they
  surface `*RawConf`/`*Conf`/`*ConfRule` contract errors under pyright) guarded by
  `tests/internal/test_workflow_fixtures.py`, which also enforces canonical form. To convert the
  fixtures faithfully the model gained `ModuleNode.options` (`ModuleOptions`, formerly
  `LoopOptions`; `LoopConf` is now only `embed`), both executions forward options for every node
  and pass a loop its embed's `conf`, positional-only inputs no longer receive the default seed,
  and `migrate_v1_to_v2` routes options, nests loop embeds, and pythonises non-identifier wire
  ports. Probes still built on `SyncPipe`/`SyncCollection` (the kazeeki files, `pipe_58a5…`,
  `pipe_8NMk…`) are ported or deleted at step 4. The follow-up embed-field slice (landed
  2026-09-29 in the step 3 working tree) then moved the embed to `ModuleNode.embed: Embed | None`,
  deleted `LoopConf`, taught `Pipeline.pipe`/`from_module` `options=`/`embed=`, and pointed
  `migrate_v1_to_v2` and `_codegen.py` at the node field.

## Step 3 — Retire remaining v1 CLI consumers

Blocks step 4.

- `riko/cli/benchmark.py` uses `SyncPipe`/`AsyncPipe`: port to `Pipeline` or delete.
- `riko/cli/compile.py` / `riko/cli/build_workflow.py`: complete the R4A.5-deferred v2-emission flip
  (emit `serialize_workflow` output) or delete the commands, updating `docs/DAG_FORMAT.rst`.
- Audit `runpipe` (loads `examples/*.py`, which are still v1 `SyncPipe` scripts; the surviving
  `pypipelines` probes are hand-maintained and need no runner change).
- The strict-xfail tripwire `tests/internal/test_compile.py::test_convert_dag_empty_modules_raises`
  is **retired** (maybe in the same commit that changes `build_workflow`), per
  [testing.md](testing.md).
- As-built (2026-09-29, landed in the working tree, commit pending): the decision was **keep every
  CLI, make it v2-native** — nothing was deleted. `riko/cli/_workflow.py` is the shared front door
  (`DocumentFormat` `dag`/`v1`/`v2`, `read_document`, `get_document_format`, `normalize_document`,
  `require_workflow`); detection is `nodes`/`version` → v2, `modules` with `src`/`tgt` wires or an
  `output` module → v1, `modules` otherwise → DAG. `build-workflow [path] [-f/--format] [-c/--compact]
  [-o]` is the **one lenient converter**: it reads any of the three (path, `-`, or stdin) and emits a
  validated `WorkflowDocument`, pretty by default and byte-stable under `-c`, with errors on stderr
  and exit 1. `compile-pipe [path] [-o] [-a] [-v]` is strict v2 (a serialized `PipeDag` or `PipeDef` exits 1 naming
  `build-workflow`) and drives the new generator `riko/runtime/_codegen.py`: `compile_pipe(workflow,
  name, *, is_async=False)` keeps its STABLE name but now takes a `Workflow` or a
  `RawWorkflow` and emits a module that rebuilds the graph from typed `<Name>RawConf` classes, runs it
  through the canonical execution with the caller's `Context`, and is `mark_subpipe`-marked so it can
  serve as a `pipe:` sub-pipeline (template `riko/runtime/templates/pyworkflow.txt`; the v1 compiler
  entry point is renamed `compile_pipe_def`). `run-pipe` gained document execution (`-p flow.json`, or
  an example id resolving to `examples/pipelines/{pipeid}.json`), sync or async, alongside its
  unchanged script path. `benchmark` is ported off `SyncPipe`/`AsyncPipe`: rows `sync_pipe`/
  `async_pipe` (one `Pipeline` run per feed) and `sync_workflow`/`async_workflow` (one fan-in graph of
  every feed into `union`) replace `sync_collection`/`par_sync_collection`/`async_collection`/
  `async_pipe2`, with the parallel row dropped until the execution takes a concurrency option.
  `build_pipe_def` is **deleted** in favour of `riko/runtime/_migrate.py::parse_dag` (STABLE
  `riko.parse_dag`), which expands the same `PipeDag` straight to a validated
  `Workflow`: no terminal output node, ids default `sw-{n}`, omitted wires chain in listing order,
  and a wire's optional third entry names the target port — so fan-in (`["b", "u", "in:1"]`) is now
  expressible and the old "Limitation" section of `docs/DAG_FORMAT.rst` is gone. The R17 tripwire
  `test_convert_dag_empty_modules_raises` is **retired**, replaced by the regular test
  `tests/public/test_parse_dag.py::test_empty_modules_raise_invalid_pipeline` (empty `modules` →
  `InvalidPipelineError("workflow has no nodes")`). `tests/dags/*.json` stay as `build-workflow`
  fixtures; `tests/internal/test_codegen.py` compiles every committed fixture and proves the generated
  module item-for-item equivalent to running the document (the two split fixtures strict-xfail), and
  `tests/functional/test_script.py` covers convert→compile composition, `--format`, `-c`, the empty
  DAG, legacy rejection, and `run-pipe` on documents.

## Step 4 — Delete the v1 pipe/collection classes

Depends on steps 1–3. Deletes `SyncPipe`, `AsyncPipe`, `PyPipe`, `PyCollection`,
`SyncCollection`, `AsyncCollection` from `riko/runtime/collections.py` (most of the file).

- **As-built (landed 2026-10-02, `54b53c29`; docs `6bff9f64`/`6e7fcd37`).** The classes,
  `PipeState`, `PoolScope`, and `write_file` are gone; `collections.py` keeps `Formats`, `export`,
  `list_formats`. `tests/_lifecycle.py` and `tests/public/test_collections.py` were deleted and the
  lifecycle suites rewritten on `Pipeline`; the kazeeki/`pipe_58a5…`/`pipe_8NMk…` probes and
  `examples/*.py` run on `Pipeline`. The same commit settled the workflow vocabulary (two tiers:
  the `RawWorkflow`/`RawNode`/`RawEdge`/`RawEndpoint` TypedDicts beneath the bare `Workflow`/`Node`/
  `Edge`/`Endpoint` attrs classes, with `WorkflowLike` accepting either and `WorkflowDocument` naming
  the serialized form; graph names on STABLE) and the eight-verb table now in `CLAUDE.md` (`parse_dag`, `parse_document`,
  `normalize_document`, `build-workflow`, …). `subscribe`/`publish`/`split`/`parallel` have no
  replacement yet (recorded in `docs/CHANGES.rst` Removed). Step 5 landed 2026-10-03 (see its
  as-built note).
  Nothing was removed without a named successor: `Pipeline` carries the planned verbs as
  placeholders that raise `NotImplementedError` (`subscribe`, `publish`, `split`, `map`;
  `with_execution` shipped 2026-10-03 and replaces the `parallel`/`workers`/`threads`/`pool`
  arguments), and `write(dest, mode=, fmt=, keys=)` appends a `build_write`-validated
  `WriteNode` that plan build still refuses. The retired v1 behaviors live on as strict xfails
  written against those forms — `tests/public/test_pending_pipeline_api.py` (subscriptions,
  split, callable nodes, per-item gating), the fan-in branch-pulling cases in `test_parallel.py`
  (R7), and `TestPipelineWrite` in
  `tests/internal/test_targets.py` — so each flips to a pass when its owner lands. User docs keep the
  same sections as `Pending.` code blocks. The one capability with no designed successor is the
  `skip_if` per-item callable guard (not JSON-native, so not a node option); `examples/kazeeki.py` and
  `pipe_kazeeki_full.py` dropped it, and `callable-pipes.md` owns the gap.

- The pub/sub hub (`riko/runtime/_pubsub/`) and the `receive`/`send` modules stay; only the
  `SyncPipe.subscribe`/`publish` conveniences die (their replacement is orchestration-owned).
- Same commit: remove the class names and collection verbs from `riko/__init__.py` and the
  `COLLECTIONS` set in `riko/base/_api_surface.py` (STABLE surface change) → `manage codegen
  --api` regenerates the `_docs/API_SURFACE.md` blocks; update `tests/public/test_imports.py`.
- Delete/port `tests/public/test_collections.py` (chaining coverage already re-homed, step 0).
- Scrub docstring/doc references: `riko/modules/__init__.py`, `riko/modules/receive.py`,
  `README.rst`, `docs/FAQ.rst`, `docs/COOKBOOK.rst`, `tests/functional/test_examples.py` example
  flows → v2 `Pipeline`.
- `docs/CHANGES.rst` + `docs/MIGRATION.rst` entries (clean break, no deprecation wrappers).

## Step 5 — Delete the v1 compiler core

Depends on steps 2–3 (no remaining consumers). **Code generation survives this step** — step 3
rebuilt it on `riko/runtime/_codegen.py` over canonical v2, so `compile_pipe`/`compile-pipe` are
unaffected by everything below.

- Delete from `riko/runtime/_compile.py` the generation half: `compile_pipe_def`,
  `stringify_pipe`, `_gen_string_modules`, `_gen_pykwargs`, `_get_input_module`, and the v1
  templates `riko/runtime/templates/pypipe.txt` / `pypipe_async.txt`.
- Delete the parse/build half: `parse_pipe_def`, `_index_pipe_def` (and its inlined `GraphIndex`
  assembly — the un-deduped v1 half noted at iter.1), `_gen_steps`, `build_pipeline`,
  `abuild_pipeline`, `get_pipeline_dependencies`, and `get_pipeline_inputs`.
- Remove `build_pipeline`/`parse_pipe_def`/`get_pipeline_dependencies` from `riko/__init__.py` and
  the `COMPILE` set in `riko/base/_api_surface.py` (→ `manage codegen --api` again, or fold into
  step 4's commit). `compile_pipe` stays STABLE, now sourced from `_codegen.py`.
- Check what genuinely survives before deleting: only what `_codegen.py` and `_migrate.py` still
  need. That is the `GraphIndex`/`GraphEdge`/`OutputRef` types in `riko/types/_compiler.py` (the v2
  indexer builds on them), the `PipeDag`/`PipeDefLike` shapes `parse_dag` and
  `migrate_v1_to_v2` read. `_compile_repr.py` goes entirely: `repr_arg`/`repr_args` were deleted on
  2026-09-29 (the v1 compiler now renders through `_codegen.render_value`), leaving only the `Id`
  placeholder and `PyKwargValue`, whose sole importer is `_compile.py`. Nothing in `_codegen.py`
  depends on the v1 compiler.
  `write_file` went at step 4 with its last consumer.
- **Keep `migrate_v1_to_v2`**: it already lives in `riko/runtime/_migrate.py` with no `_compile`
  import (`lower_keys` is in `riko/coercion/_sequences.py`). Delete the then-orphaned v1 wire/pipe-def
  types from `riko/types/_compiler.py` except those migrate and `parse_dag` retain.
- Delete/port the v1 halves of `tests/internal/test_compile.py`. The `pythonise` regression test
  there is re-homed, not dropped — `pythonise` survives in `riko/base/_strutils.py` with live
  consumers. `tests/internal/test_codegen.py` is the v2 replacement and stays.
- **As-built (2026-10-03; built via `/architect`, gated green — `lint --all` 0, pyright 0, 1572
  passed / 60 xfailed; uncommitted at wrapup).** Deleted `riko/runtime/_compile.py`,
  `_compile_repr.py`, `templates/pypipe.txt`/`pypipe_async.txt`, `riko/types/_pipeline.py`, and
  `tests/internal/test_compile.py`. `COMPILE` = `{compile_pipe, parse_dag}` (`manage codegen --api`
  regenerated). `resolve_module` was **not** relocated — its two test callers use
  `dispatcher.require(name, is_async)` directly (`tests/functional/test_basics.py`, narrowed with
  `is_subpipe`). `riko/types/_compiler.py` lost only `XY` and the compiler-internal TypedDicts
  (`AbbrevStringModule`/`StringModule`/`TemplateData`/`ParsedPipeDef`/`PipelineDescription*`);
  `PipeDef` stays whole for `migrate_v1_to_v2`; `GraphEdge`/`OutputRef`/`GraphIndex` docstrings now
  describe the v2 port grammar. Tests: the `pythonise` R5 tripwire moved to
  `tests/internal/test_codegen.py`; the vacuous "imports no compiler" resolver test became
  `test_resolver.py::TestPipeResolver::test_unresolved_pipeline_name_raises` (pins
  `UnsupportedModuleError` for `pipe_missing`); `test_basics.py` gained `test_loop_subpipe_embed`
  and `test_loop_count_all_assign` pinning the exact outputs of the two loop fixtures that only the
  codegen parity test reached; `test_index_workflow_orders_and_indexes` now also asserts
  `GraphIndex.dependents`. Docs: CHANGES "Removed" bullet names `extract_dependencies` (the v0.77.3
  name) and the graph-index "Changes" bullet was folded into the `Workflow` bullet as a `validate()`
  cycle rejection; FAQ/MIGRATION/CLAUDE.md/KEY_PATHS/INTERNALS/API_SURFACE prose swept.

## Step 6 — `SINK_NAMES` + `Sinks`: defer to R5C, recorded now

The paired-deletion table ties their removal to retiring the v1 `write` module in the same
commit; since `write` survives until `WriteNode` executes (R5C), `SINK_NAMES`
(`riko/base/_config.py`) and the `Sinks` discovery bucket move to that commit:

- remove `SINK_NAMES`; regenerate discovery (`manage codegen --names` →
  `riko/modules/_names.py`, `riko/types/_module_ids.py`);
- remove `Sinks` from `riko/__init__.py` + the `MODULES` set in `_api_surface.py`
  (`manage codegen --api`);
- update `tests/internal/test_codegen_names.py`, `tests/public/test_imports.py`, README/docs
  mentions, `docs/MIGRATION.rst`.

The cutover session's only step-6 action is keeping this deferral recorded so the deletion table
row is not executed early.

## Per-step gates

Every step lands through the standard gate before its commit:

```console
uv run --active python -m riko.cli.manage prettify
uv run --active python -m riko.cli.manage lint --all
uv run --active python -m riko.cli.manage lint --check-types
uv run --active python -m riko.cli.manage test --no-cov --quiet
```

`lint --all` already covers the docs, docstring, and every import-contract check (including the
architecture graph), so none of those are rerun separately; type verification is the one explicit
extra. Steps add the codegen drift guards named per step (`--api` steps 4–5, `--names` + `--api`
step 6; step 2 deleted the `--pipes` selector it would have used). Each step also updates `_docs/IMPLEMENTED.md`, `_docs/PHASE_CHECKLISTS.md`, and
the R4B section of [implementation-sequence.md](implementation-sequence.md).
