# riko API Surface

This document defines riko's supported import boundaries.

The import path determines the compatibility contract for an object. Implementation
location does not.

A name listed in a public module's `__all__` is part of Riko's supported
compatibility surface. Importable names not listed in `__all__` are
implementation-accessible but carry no compatibility guarantee.

The examples in this document mirror the declarations in
`riko.base._api_surface`. They are illustrative; the enforced public-boundary
coverage lives in `tests/public/test_imports.py`.

## Contract declarations

The API contract is declared in `riko.base._api_surface`. This module is private
because the declarations describe the public API; they are not themselves part of
it.

Implementation code is now grouped below that facade (`base`, `types`, `coercion`,
`definitions`, `io`, `parsing`, `rss`, `runtime`, and `modules`). Those physical
packages do not create new compatibility tiers by themselves.

## Stable application API

Application code should import stable APIs from `riko`.

Breaking changes to this surface follow riko's normal SemVer policy.

**Collections** — pipe/collection runtime and export helpers
(`riko.runtime.collections`):

<!-- api-surface:collections -->
```python
>>> sorted(COLLECTIONS)
['AsyncCollection', 'AsyncPipe', 'Formats', 'PipeState', 'SyncCollection', 'SyncPipe', 'export', 'list_formats']
```
<!-- /api-surface:collections -->

**Compilation** — DAG/JSON compilation entry points implemented in
`riko.runtime._compile`:

<!-- api-surface:compile -->
```python
>>> sorted(COMPILE)
['build_pipe_def', 'build_pipeline', 'compile_pipe', 'get_pipeline_dependencies', 'parse_pipe_def']
```
<!-- /api-surface:compile -->

**Async runtime** — async helpers promoted from `riko.bado` (see
[Async runtime namespace](#async-runtime-namespace)):

<!-- api-surface:bado -->
```python
>>> sorted(BADO)
['as_async', 'async_map', 'async_map_stream', 'async_read', 'async_return', 'async_sleep', 'backend', 'isasync', 'issync', 'run']
```
<!-- /api-surface:bado -->

Stable async file/URL I/O (`async_url_open`, `async_write`,
`get_async_temp_file`) is implemented under `riko.io` and promoted to `riko` via
the `IO_` contract group.

**Module discovery** — discovery enums and catalog helpers (`riko.modules`):

<!-- api-surface:modules -->
```python
>>> sorted(MODULES)
['Modules', 'Sinks', 'Sources', 'Transforms', 'describe_module', 'get_module_metadata']
```
<!-- /api-surface:modules -->

**Root exceptions** — the `RikoError` hierarchy implemented in
`riko.base.exceptions` and promoted onto the stable surface:

<!-- api-surface:root-exceptions -->
```python
>>> sorted(ROOT_EXCEPTIONS)
['PipelineStateError', 'RikoError', 'UnsupportedModuleError', 'UnsupportedPipelineError']
```
<!-- /api-surface:root-exceptions -->

**Other** — execution context and filesystem-path helpers:

<!-- api-surface:other -->
```python
>>> sorted(OTHER)
['Backends', 'Context', 'ExecutionMode', 'Pipeline', 'get_path', 'get_temp_file', 'list_modules']
```
<!-- /api-surface:other -->

The complete stable surface is the union of these groups:

<!-- api-surface:stable-union -->
```python
>>> STABLE == BADO | IO_ | COLLECTIONS | COMPILE | MODULES | OTHER | ROOT_EXCEPTIONS
True
```
<!-- /api-surface:stable-union -->

## Async runtime namespace

`riko.bado` is the supported async-runtime namespace for backend and async-iterator
helpers. File/URL transport helpers live in the separate `riko.io` package.

`BADO` is specifically the subset promoted into the stable application API:

<!-- api-surface:bado-namespace -->
```python
>>> sorted(BADO)
['as_async', 'async_map', 'async_map_stream', 'async_read', 'async_return', 'async_sleep', 'backend', 'isasync', 'issync', 'run']
>>> BADO == set(riko.bado.__all__)
True
```
<!-- /api-surface:bado-namespace -->

Promoted Bado names resolve to the same objects through their supported paths:

```python
>>> riko.run is riko.bado.run
True
```

Lower-level async iterator helpers may remain available from submodules such as
`riko.bado.itertools` without being included in `BADO`. Async transport/file
helpers are exposed from `riko.io`, not `riko.bado.io`.

## Stable typing API

`riko.types` is the supported namespace for annotations used by applications
and extension authors.

<!-- api-surface:types -->
```python
>>> sorted(TYPES)
['AsyncItems', 'AsyncPipeTuples', 'AsyncStream', 'Conf', 'EdgeAuthoring', 'EndpointAuthoring', 'Feed', 'Item', 'Items', 'NodeAuthoring', 'PipeTuples', 'Stream', 'SyncPipeTuples', 'WorkflowAuthoring', 'WorkflowSpecLike']
```
<!-- /api-surface:types -->

## Extension API

`riko.ext` is the supported API for module authors and integration packages.

This surface is SemVer-guaranteed but is intended for extension and integration
authors rather than ordinary application code.

<!-- api-surface:extension -->
```python
>>> sorted(EXTENSION)
['ActionNode', 'AsyncOperatorWrapper', 'AsyncProcessorWrapper', 'AsyncSplitterWrapper', 'CacheNode', 'DynamicConf', 'Endpoint', 'FileTarget', 'ModuleDefinition', 'ModuleMetadata', 'ModuleName', 'ModuleNameLike', 'ModuleNode', 'ModuleRegistry', 'ModuleSubtype', 'ModuleType', 'ModuleWrapper', 'PublishEdge', 'ReadNode', 'StreamEdge', 'SubscribeNode', 'SupportsActions', 'SupportsRead', 'SupportsWrite', 'SyncOperatorWrapper', 'SyncProcessorWrapper', 'SyncSplitterWrapper', 'Target', 'TargetRegistry', 'WorkflowSpec', 'WriteCapabilities', 'WriteNode', 'get_conf_type', 'get_module_category', 'normalize_module_name', 'operator', 'processor', 'register_module', 'register_target', 'splitter']
```
<!-- /api-surface:extension -->

The stable application and extension surfaces are separate contracts:

<!-- api-surface:stable-disjoint -->
```python
>>> STABLE.isdisjoint(EXTENSION)
True
```
<!-- /api-surface:stable-disjoint -->

## Private implementation

Underscore-prefixed modules and names are implementation details unless explicitly
re-exported through one of the supported namespaces above.

Private implementation paths carry no independent compatibility guarantee. For
example, compiler/resolution implementations live under private paths such as
`riko.runtime._compile` and `riko.runtime._resolver`; callers should use the stable
or extension facade appropriate to the operation rather than treating those paths
as new APIs.

## Compatibility imports

Some supported objects are also importable directly from the module that implements
them. These are re-exports of the same objects, not separate implementations.

For example:

```python
>>> riko.Context is riko.runtime.context.Context
True
```

## Contract enforcement

`riko.base._api_surface` declares the intended surface, while each namespace's
`__all__` describes what the implementation exports.

This document illustrates the key relationships between those declarations.
`tests/public/test_imports.py` provides the complete black-box coverage for
importability, private-name leakage, duplicate exports, compatibility aliases, and
other public-boundary invariants. `manage lint imports --canonical` independently
checks internal code for imports through re-export facades rather than canonical
defining modules.
