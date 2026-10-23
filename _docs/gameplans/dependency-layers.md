# Dependency Layers

Riko's source tree is grouped by dependency direction. The package layout and the
static import-contract linter now express the same architecture; this document is
the human-readable contract for that hierarchy.

The executable source of truth is `riko/cli/_lint_import_architecture.py`. The AST
scanner that classifies imports lives in `riko/cli/_import_graph.py`, and the CLI
surface is `manage lint imports`.

## Layer DAG

An arrow points from a layer to the layers it may depend on. The compact form printed
by `manage lint imports --architecture` is:

```text
base < types < {bado | coercion | definitions} < io < parsing < rss
        {bado | definitions} < execution
        {execution | parsing} < runtime
        {rss | runtime} < modules < api < cli
```

The declaration behind that rendering is:

```text
base        -> <none>
types       -> base
coercion    -> types
bado        -> types
definitions -> types
io          -> coercion, bado, definitions
parsing     -> io
rss         -> parsing
execution   -> bado, definitions
runtime     -> execution, parsing
modules     -> runtime, rss
api         -> modules
cli         -> api
```

A layer may also import any transitive dependency reachable through that DAG. The
DAG is deliberately not flattened into one linear stack: `bado`, `coercion`, and
`definitions` are peers, while `execution` forms a separate branch that rejoins at
`runtime`.

## Package mapping

| Source path | Layer | Role |
|---|---|---|
| `riko/base/` | `base` | low-level constants, paths, logging, string/iterator/date/graph helpers, generic guards/narrowing and record helpers, sentinels, exceptions (private `_exceptions.py` behind the public `exceptions.py` facade), API declarations |
| `riko/_package.py` | `base` | package metadata kept below the public facade |
| `riko/types/` | `types` | type contracts, config TypedDicts, stream/resource/compiler types, enums, and the immutable contract records that validate themselves (see *Returning `types` to contracts*) |
| `riko/coercion/` | `coercion` | casting, dynamic config/objectification, canonical identity |
| `riko/bado/` | `bado` | async backend selection, async itertools, async utilities |
| `riko/definitions/` | `definitions` | immutable/declarative module, resource, target, and write contracts, including the `Context` (`_context.py`) and `Resource` (`_resource_definition.py`) definitions |
| `riko/io/` | `io` | sync/async I/O, serialization, re-encoding |
| `riko/parsing/` | `parsing` | config parsing, `DotDict`, HTML/XML/document parsing |
| `riko/rss/` | `rss` | feed discovery, entry normalization, RSS/Atom parsing |
| `riko/execution/` | `execution` | execution planning (`_prepared.py`), one-shot sync/async executions, lifetime primitives, execution-local resource acquisition and owned-resource teardown (`_resource_teardown.py`), the resolved-resource mapping handed to modules (`_resource_view.py`), event sink |
| `riko/runtime/` | `runtime` | collections, compiler, pipelines, the pipeline runners (`_run.py`), resolver/registry, pub/sub, write sessions |
| `riko/modules/` | `modules` | built-in pipe implementations and module metadata/decorator internals |
| `riko/ext/` | `modules` | supported extension-author facade and codegen helpers; same dependency layer as modules |
| `riko/__init__.py` | `api` | stable application facade |
| `riko/cli/` | `cli` | commands, generators, documentation checks, import-contract linters |

Every Python module under `riko` must classify into one of these layers. An
unclassified module is an architecture failure rather than an implicit new tier.

## Definition versus execution

The folder split deliberately separates immutable declarations from mutable runtime
state:

- `riko/definitions/` contains descriptions of what a module/resource/write is.
- `riko/execution/` is the `execution` layer: resource acquisition and teardown
  (`_resource_teardown.py`) and the resolved-resource view (`_resource_view.py`) live alongside the one-shot executions and lifetime primitives.
- `riko/runtime/` orchestrates streams, compilation, resolution, pub/sub, and
  write sessions around those contracts, and holds the pipeline runners (`_run.py`), which
  build the frozen `ExecutionPlan` through `ExecutionPlan.from_workflow` in
  `riko/execution/_prepared.py` (typed against the `Dispatcher` protocol, so the
  execution layer never imports the resolver).

The `execution` label maps to the `riko.execution` package by prefix, so no
per-file exception is needed; `_EXACT_LAYERS` now covers only `riko` (api) and
`riko._package` (base).

## Import kinds

The architecture scanner classifies static imports without importing the package:

- **module-scope runtime imports** are recorded in the `observed dependency frontier` and must
  point to an allowed layer in the DAG.
- **`if TYPE_CHECKING:` imports** are recorded in `typing-only dependencies`
  and do not fail the layer-direction rule.
- **function-local imports** are recorded in `local-only dependencies` and
  must point to an allowed layer in the DAG, exactly like
  module-scope imports. Deferring an import does not change which layer depends on
  which, so a function-local import is never an exemption from the layer rule.

The scanner is intentionally static. Imports assembled dynamically from strings or
loaded through plugin/entry-point mechanisms are not represented by the observed
AST graph.

## Same-layer imports

The layer rule is supplemented by a package-structure rule: a non-`__init__`
module may not runtime-import a **public** module in its own layer. Same-layer
implementation dependencies should point at underscore-private modules, while
package `__init__` files may compose the layer's supported facade.

This is why a same-layer refactor often pairs a public facade with private
implementation modules instead of growing a web of public sibling imports.

## Other import contracts

Architecture direction is only one of three import checks:

- `--canonical` rejects internal imports through re-export facades when the defining
  module is the canonical source.
- `--relative` requires sibling imports inside a package to use relative syntax.
- `--architecture` validates classification, the layer DAG, and same-layer public
  imports.

`manage lint imports` defaults to `--canonical`. The selectors are additive:

```text
manage lint imports --relative --architecture
manage lint imports --all
```

`manage lint --all` includes all three import-contract checks along with the normal
standard lint suite, so CI enforces the hierarchy rather than merely documenting
it.

## Reading the architecture report

`manage lint imports --architecture` renders four distinct things:

1. `layers` — the declared allowed DAG.
2. `observed dependency frontier` — the reduced runtime module-scope dependency frontier
   found in the source tree.
3. `typing-only dependencies` — type-only edges, which are exempt from the
   runtime-direction failure rule.
4. `local-only dependencies` — function-local edges, which are not exempt.

The observed rendering is a compact frontier, not an exhaustive list of every
import edge. A higher dependency can subsume lower transitive dependencies in the
printed report.

## Change rules

When moving or adding source files:

1. A module may not import, at runtime and module scope, from a layer that the
   DAG above does not allow. `cli` is the top layer, so its module-scope imports of
   `runtime` and `modules` are ordinary downward edges, not exceptions.
2. There are no upward edges, function-local or otherwise. When a lower layer seems
   to need a higher one, move the shared contract down to the owning layer, or split
   the type so the higher layer extends the lower one.

## Example: `PipelineDefinition` and `Pipeline`

A pipeline is both an immutable definition and the user's entry point for running
it. The type is split along that line rather than reaching upward:

- `PipelineDefinition` (`riko/definitions/_composition.py`) owns the fields and every
  composition method (`from_module`, `pipe`, `|`, `write`, `with_*`, …). Each
  returns the caller's own class, so composing a `Pipeline` yields a `Pipeline`.
  Definitions that embed a pipeline depend on this class.
- `Pipeline` (`riko/runtime/_pipeline.py`) subclasses it and adds only running:
  `__iter__`, `__aiter__`, `first`, and `afirst` build an execution plan and run it
  in a one-shot execution, all through ordinary downward imports.

New pipeline behavior that only composes the graph belongs on
`PipelineDefinition`; behavior that runs it belongs on `Pipeline` or in
`execution`/`runtime`.

## Folder regrouping

1. Put the implementation in the lowest layer that owns its responsibility.
2. Update `_PREFIX_LAYERS` or `_EXACT_LAYERS` only when a genuinely new mapping is
   needed; do not make an exception merely to silence an upward import.
3. Prefer moving a shared contract downward over importing a higher runtime layer
   from a lower package.
4. Keep definition objects immutable; execution-owned mutable state stays in the
   execution/runtime side of the boundary.
5. Run `manage lint imports --all` after package moves. Run `manage lint --all`
   before merging so the same contracts CI sees are exercised locally.

## Returning `types` to contracts

Decided and landed 2026-10-23 (move/consolidation audit). `types/` is for type contracts: aliases,
protocols, TypedDicts, enums, and the immutable contract records that validate themselves. Runtime
machinery that knows no contract lives in `base/`; behavior shared across higher layers lives in the
lowest layer its importers share.

- **Generic runtime helpers are in `base/`.** `_guards.py` (generic shape guards), `_require_guards.py`
  (the `require_*`/`narrow_*`/`def_from_*`/`validator_from_*` family plus `require_arg`/
  `require_conf_key`), `_recordutils.py` (`field_names`, `required_attrs_keys`, the compact serializers),
  `_sentinels.py` (moved whole: `MISSING`, `StreamState`, the `Sentinel` shape and its guards),
  and in `_typing.py` `resolve_enum` plus the runtime `isinstance` tuples (their type aliases stay
  in `types/_scalars.py`).
- **`_sentinels.py` is a deliberate exception.** `_guards.py` needs `MISSING` at runtime, so the file
  moved whole rather than splitting it or giving `_guards.py` its own placeholder object. The
  `StreamState` enum and the `Sentinel` TypedDict came along, two contracts that would otherwise
  belong in `types`. The terminal-reference helpers (`Sentinel`, `SentinelValue`, `is_sentinel`)
  leave when they move into configuration parsing (`dotdict-parsing.md`); `MISSING` and
  `StreamState` stay.
- **Exceptions sit behind a facade.** The same-layer rule bars a private `base` module from importing
  the public `exceptions.py`, so the classes live in `base/_exceptions.py`, internal code imports
  them from there, and `exceptions.py` re-exports them as the documented `riko.base.exceptions` path.
  Each class's `__module__` names that public path, so tracebacks and pickles are unchanged.
- **Contract-specific guards stay in `types`:** `is_conf_rule` in
  `_frozendict.py`, `is_type_value` in `modules.py` beside `ConfArg`. `is_conf_rule` narrows
  `AnyConfRule` from `modules.py` but cannot live there: `freeze_json` calls it at runtime, and the
  same-layer rule bars private `_frozendict.py` from importing public `modules.py`.
- **Contract records stay in `types`:** `Endpoint`/`Edge`/`GraphIndex`, `CallOptions`, the resource
  plan records, and `_frozendict.py`. `freeze_json`'s JSON-native rule accepts conf-rule dataclasses
  and rejects every other dataclass (`test_module_conf_rejects_dataclass_values`), so it is a contract,
  not a generic helper.
- **Cross-layer wrapper behavior is in `definitions/_wrapping.py`:** `prepare_call`/`build_call`/
  `stamp_wrapper_meta`, needed by both `execution` and `modules`. The wrapper protocols stay in
  `types/_wrappers.py`.

No layer was added and `LAYER_DEPENDENCIES` did not change.

The old flat top-level layout and its proposed `definition/`/`runtime/` regrouping
are historical. The current `base/`, `types/`, `coercion/`, `bado/`,
`definitions/`, `io/`, `parsing/`, `rss/`, `runtime/`, `modules/`, and `cli/`
packages are the architecture now.
