# riko API Surface

This document defines riko's supported import boundaries.

The import path determines the compatibility contract for an object. Implementation location does not.

A name listed in a public module's `__all__` is part of Riko's supported compatibility surface. Importable names not listed in `__all__` are implementation-accessible but carry no compatibility guarantee.

The examples in this document mirror the declarations in `riko._api_surface`. They are illustrative; the enforced public-boundary coverage lives in `tests/public/test_imports.py`.

## Contract declarations

The API contract is declared in `riko._api_surface`. This module is private because the declarations describe the public API; they are not themselves part of it.

## Stable application API

Application code should import stable APIs from `riko`.

Breaking changes to this surface follow riko's normal SemVer policy.

**Collections** — pipe/collection runtime and export helpers (`riko.collections`):

```python
>>> sorted(COLLECTIONS)
['AsyncCollection', 'AsyncPipe', 'PipeState', 'SyncCollection', 'SyncPipe', 'Targets', 'export', 'list_targets']
```

**Compilation** — DAG/JSON compilation entry points (`riko.compile`):

```python
>>> sorted(COMPILE)
['build_pipeline', 'compile_pipe', 'convert_dag', 'extract_dependencies', 'parse_pipe_def']
```

**Async runtime** — async helpers promoted from `riko.bado` (see [Async runtime namespace](#async-runtime-namespace)):

```python
>>> sorted(BADO)
['as_async', 'async_map', 'async_map_stream', 'async_read', 'async_return', 'async_sleep', 'async_write', 'backend', 'get_async_temp_file', 'isasync', 'issync', 'run']
```

**Module discovery** — discovery enums and catalog helpers (`riko.modules`):

```python
>>> sorted(MODULES)
['Modules', 'Sinks', 'Sources', 'Transforms', 'describe_module', 'get_module_metadata', 'list_modules']
```

**Root exceptions** — the `RikoError` hierarchy promoted onto the surface (`riko.exceptions`):

```python
>>> sorted(ROOT_EXCEPTIONS)
['PipelineStateError', 'RikoError', 'UnsupportedModuleError', 'UnsupportedPipelineError']
```

**Other** — execution context and filesystem-path helpers:

```python
>>> sorted(OTHER)
['Context', 'ExecutionMode', 'get_path', 'get_temp_file']
```

The complete stable surface is the union of these groups:

```python
>>> STABLE == BADO | COLLECTIONS | COMPILE | MODULES | OTHER | ROOT_EXCEPTIONS
True
```

## Async runtime namespace

`riko.bado` is the supported async-runtime namespace.

It owns riko's async helpers and provides a guarded import surface for selected backend primitives used throughout riko.

`BADO` is specifically the subset promoted into the stable application API:

```python
>>> sorted(BADO)
['as_async', 'async_map', 'async_map_stream', 'async_read', 'async_return', 'async_sleep', 'async_write', 'backend', 'get_async_temp_file', 'isasync', 'issync', 'run']
>>> BADO == set(riko.bado.__all__)
True
```

Promoted Bado names resolve to the same objects through all three supported paths:

```python
>>> riko.run is riko.bado.run
True
```

Lower-level helpers may also remain available from submodules such as `riko.bado.itertools` and `riko.bado.io` without being included in `BADO`.

## Extension API

`riko.ext` is the supported API for module authors and integration packages.

This surface is SemVer-guaranteed but is intended for extension and integration authors rather than ordinary application code.

```python
>>> sorted(EXTENSION)
['AsyncOperatorWrapper', 'AsyncProcessorWrapper', 'AsyncSplitterWrapper', 'DynamicConf', 'ModuleDefinition', 'ModuleMetadata', 'ModuleName', 'ModuleNameLike', 'ModuleRegistry', 'ModuleSubtype', 'ModuleType', 'ModuleWrapper', 'SyncOperatorWrapper', 'SyncProcessorWrapper', 'SyncSplitterWrapper', 'derive_category', 'get_conf_type', 'normalize_module_name', 'operator', 'processor', 'register', 'splitter']
```

The stable application and extension surfaces are separate contracts:

```python
>>> STABLE.isdisjoint(EXTENSION)
True
```

## Private implementation

Underscore-prefixed modules and names are implementation details unless explicitly re-exported through one of the supported namespaces above.

Private implementation paths carry no independent compatibility guarantee.

For example, resolution implementations remain behind private module paths; `riko.ext.resolver` and `riko.ext.pipelines` are not public namespaces.

## Compatibility imports

Some supported objects are also importable directly from the module that implements them.

These are re-exports of the same objects, not separate implementations.

For example:

```python
>>> riko.Context is riko.context.Context
True
```

## Contract enforcement

`riko._api_surface` declares the intended surface, while each namespace's `__all__` describes what the implementation exports.

This document illustrates the key relationships between those declarations. `tests/public/test_imports.py` provides the complete black-box coverage for importability, private-name leakage, duplicate exports, compatibility aliases, and other public-boundary invariants; a change to the declared surface that this document does not track will surface there.
