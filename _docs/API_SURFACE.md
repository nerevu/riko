# riko API Surface

This document defines riko's supported import boundaries.

The import path determines the compatibility contract for an object. Implementation location does not.

A name listed in a public module's `__all__` is part of Riko's supported compatibility surface. Importable names not listed in `__all__` are implementation-accessible but carry no compatibility guarantee.

The examples in this document mirror the declarations in `riko.base._api_surface`. They are illustrative; the enforced public-boundary coverage lives in `tests/public/test_imports.py`.

## Contract declarations

The API contract is declared in `riko.base._api_surface`. This module is private because the declarations describe the public API; they are not themselves part of it.

## Stable application API

Application code should import stable APIs from `riko`.

Breaking changes to this surface follow riko's normal SemVer policy.

**Collections** — pipe/collection runtime and export helpers (`riko.runtime.collections`):

<!-- api-surface:collections -->
```python
>>> sorted(COLLECTIONS)
['AsyncCollection', 'AsyncPipe', 'Formats', 'PipeState', 'SyncCollection', 'SyncPipe', 'export', 'list_formats']
```
<!-- /api-surface:collections -->

**Compilation** — DAG/JSON compilation entry points (`riko.runtime.compile`):

<!-- api-surface:compile -->
```python
>>> sorted(COMPILE)
['build_pipeline', 'compile_pipe', 'convert_dag', 'extract_dependencies', 'parse_pipe_def']
```
<!-- /api-surface:compile -->

**Async runtime** — async helpers promoted from `riko.bado` (see [Async runtime namespace](#async-runtime-namespace)):

<!-- api-surface:bado -->
```python
>>> sorted(BADO)
['as_async', 'async_map', 'async_map_stream', 'async_read', 'async_return', 'async_sleep', 'async_url_open', 'async_write', 'backend', 'get_async_temp_file', 'isasync', 'issync', 'run']
```
<!-- /api-surface:bado -->

**Module discovery** — discovery enums and catalog helpers (`riko.modules`):

<!-- api-surface:modules -->
```python
>>> sorted(MODULES)
['Modules', 'Sinks', 'Sources', 'Transforms', 'describe_module', 'get_module_metadata', 'list_modules']
```
<!-- /api-surface:modules -->

**Root exceptions** — the `RikoError` hierarchy promoted onto the surface (`riko.exceptions`):

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
['Context', 'ExecutionMode', 'get_path', 'get_temp_file']
```
<!-- /api-surface:other -->

The complete stable surface is the union of these groups:

<!-- api-surface:stable-union -->
```python
>>> STABLE == BADO | COLLECTIONS | COMPILE | MODULES | OTHER | ROOT_EXCEPTIONS
True
```
<!-- /api-surface:stable-union -->

## Async runtime namespace

`riko.bado` is the supported async-runtime namespace.

It owns riko's async helpers and provides a guarded import surface for selected backend primitives used throughout riko.

`BADO` is specifically the subset promoted into the stable application API:

<!-- api-surface:bado-namespace -->
```python
>>> sorted(BADO)
['as_async', 'async_map', 'async_map_stream', 'async_read', 'async_return', 'async_sleep', 'async_url_open', 'async_write', 'backend', 'get_async_temp_file', 'isasync', 'issync', 'run']
>>> BADO == set(riko.bado.__all__)
True
```
<!-- /api-surface:bado-namespace -->

Promoted Bado names resolve to the same objects through all three supported paths:

```python
>>> riko.run is riko.bado.run
True
```

Lower-level helpers may also remain available from submodules such as `riko.bado.itertools` and `riko.bado.io` without being included in `BADO`.

## Extension API

`riko.ext` is the supported API for module authors and integration packages.

This surface is SemVer-guaranteed but is intended for extension and integration authors rather than ordinary application code.

<!-- api-surface:extension -->
```python
>>> sorted(EXTENSION)
['AsyncOperatorWrapper', 'AsyncProcessorWrapper', 'AsyncSplitterWrapper', 'DynamicConf', 'ModuleDefinition', 'ModuleMetadata', 'ModuleName', 'ModuleNameLike', 'ModuleRegistry', 'ModuleSubtype', 'ModuleType', 'ModuleWrapper', 'SyncOperatorWrapper', 'SyncProcessorWrapper', 'SyncSplitterWrapper', 'derive_category', 'get_conf_type', 'normalize_module_name', 'operator', 'processor', 'register', 'splitter']
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

Underscore-prefixed modules and names are implementation details unless explicitly re-exported through one of the supported namespaces above.

Private implementation paths carry no independent compatibility guarantee.

For example, resolution implementations remain behind private module paths; `riko.ext.resolver` and `riko.ext.pipelines` are not public namespaces.

## Compatibility imports

Some supported objects are also importable directly from the module that implements them.

These are re-exports of the same objects, not separate implementations.

For example:

```python
>>> riko.Context is riko.definitions.context.Context
True
```

## Contract enforcement

`riko.base._api_surface` declares the intended surface, while each namespace's `__all__` describes what the implementation exports.

This document illustrates the key relationships between those declarations. `tests/public/test_imports.py` provides the complete black-box coverage for importability, private-name leakage, duplicate exports, compatibility aliases, and other public-boundary invariants; a change to the declared surface that this document does not track will surface there.
