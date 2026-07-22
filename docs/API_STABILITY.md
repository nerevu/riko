# riko API Stability

riko follows semantic versioning for its public surface. What an import path is
tells you what stability guarantee it carries. The full per-symbol contract is
in [API_SURFACE.md](API_SURFACE.md).

## Tiers

- **Stable — `riko` / `riko.api`**
  Application-facing API: `SyncPipe`, `AsyncPipe`, `SyncCollection`,
  `AsyncCollection`, `Context`, `list_modules`, `list_targets`, `export`, and the
  public exceptions. Breaking changes require a major version bump. `riko.__all__`
  equals `riko.api.__all__`.

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

Names that move keep a re-export at their old import path for at least one minor
release; behavior-changing removals are listed in
[MIGRATION_SHIMS.md](MIGRATION_SHIMS.md). Symbols such as `Objectify`, `objectify`,
and `listize` remain importable from `riko` but are excluded from `riko.__all__`
(they are not part of the guaranteed surface).
