# riko API Stability

riko follows semantic versioning for its public surface. What an import path is
tells you what stability guarantee it carries.

## Tiers

- **Stable — `riko` / `riko.api`**
  Application-facing API: `AsyncCollection`, `AsyncPipe`, `Context`, `SyncCollection`,
  `SyncPipe`, `backend`, `build_pipeline`, `compile_pipe`, `convert_dag`, `ExecutionMode`,
  `export`, `extract_dependencies`, `get_module_metadata`, `get_path`, `isasync`,
  `issync`, `list_modules`, `list_targets`, `parse_pipe_def`, `PipeState`, `run`, and
  the public exceptions.
  Breaking changes require a major version bump. `riko.__all__` equals
  `riko.api.__all__`.

- **Extension — `riko.ext`**
  For module authors and integration packages: `processor`, `operator`,
  `splitter`, `ModuleMetadata`/`ModuleType`/`ModuleSubtype`, and the parser
  protocols. SemVer-guaranteed, but for a smaller audience than the stable API.

- **Private — everything else**
  Underscore-prefixed names and internal modules (AST inference, prepared-module
  internals, pool handles, pub/sub registries, compiler helpers). No stability
  guarantee; may change in any release. Do not import these from application code.

## Marker

riko ships a `py.typed` marker, so type checkers treat it as a typed dependency.

## Compatibility during refactors

After 1.0 release, names that move will keep a re-export at their old import path for at
least one minor release; behavior-changing removals will be listed in
[CHANGES.rst](CHANGES.rst).
