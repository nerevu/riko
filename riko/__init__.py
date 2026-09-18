# vim: sw=4:ts=4:expandtab
"""
Stable application API for Riko.

Application code imports from this namespace; extension authors use ``riko.ext``.
``riko.bado`` exposes the supported async-runtime namespace.
"""

from riko.bado._backend import async_sleep, backend, isasync, issync, run
from riko.bado._util import async_read, async_return
from riko.bado.itertools import as_async, async_map, async_map_stream
from riko.base._paths import get_path, get_temp_file
from riko.base.exceptions import (
    PipelineStateError,
    RikoError,
    UnsupportedModuleError,
    UnsupportedPipelineError,
)
from riko.definitions._workflow import Pipeline
from riko.ext.codegen import list_modules
from riko.io._async import async_url_open, async_write, get_async_temp_file
from riko.modules._metadata import describe_module, get_module_metadata
from riko.modules._names import Modules, Sinks, Sources, Transforms
from riko.runtime._compile import (
    build_pipeline,
    compile_pipe,
    convert_dag,
    extract_dependencies,
    parse_pipe_def,
)
from riko.runtime.collections import (
    AsyncCollection,
    AsyncPipe,
    PipeState,
    SyncCollection,
    SyncPipe,
    export,
    list_formats,
)
from riko.runtime.context import Context
from riko.types._enums import Backends, ExecutionMode, Formats

from ._package import PACKAGE_INFO


def __getattr__(name: str) -> str:
    if name in PACKAGE_INFO:
        return PACKAGE_INFO[name]
    else:
        msg = f"module {__name__} has no attribute {name}"
        raise AttributeError(msg)


__copyright__ = "Copyright 2015 Reuben Cummings"

__all__ = [
    "AsyncCollection",
    "AsyncPipe",
    "Backends",
    "Context",
    "ExecutionMode",
    "Formats",
    "Modules",
    "PipeState",
    "Pipeline",
    "PipelineStateError",
    "RikoError",
    "Sinks",
    "Sources",
    "SyncCollection",
    "SyncPipe",
    "Transforms",
    "UnsupportedModuleError",
    "UnsupportedPipelineError",
    "as_async",
    "async_map",
    "async_map_stream",
    "async_read",
    "async_return",
    "async_sleep",
    "async_url_open",
    "async_write",
    "backend",
    "build_pipeline",
    "compile_pipe",
    "convert_dag",
    "describe_module",
    "export",
    "extract_dependencies",
    "get_async_temp_file",
    "get_module_metadata",
    "get_path",
    "get_temp_file",
    "isasync",
    "issync",
    "list_formats",
    "list_modules",
    "parse_pipe_def",
    "run",
]
