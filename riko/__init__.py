# vim: sw=4:ts=4:expandtab
"""
riko
~~~~

Public entry point for riko.

Application code imports stable APIs from ``riko``. Extension
authors import from ``riko.ext``. ``riko.bado`` provides the supported async
runtime namespace, with selected helpers promoted into this stable surface.

The stable, SemVer-guaranteed application-facing surface of riko. Import
application code from here or from the top-level :mod:`riko` package, which
re-exports this module.

Extension-author symbols live in :mod:`riko.ext`. :mod:`riko.bado` is the
supported async-runtime namespace; selected application-facing helpers from it
are promoted here.
"""

from riko._metadata import PACKAGE_INFO
from riko.bado._backend import async_sleep, backend, isasync, issync, run
from riko.bado._util import async_read, async_return
from riko.bado.io import async_url_open, async_write, get_async_temp_file
from riko.bado.itertools import as_async, async_map, async_map_stream
from riko.collections import (
    AsyncCollection,
    AsyncPipe,
    PipeState,
    SyncCollection,
    SyncPipe,
    Targets,
    export,
    list_targets,
)
from riko.compile import (
    build_pipeline,
    compile_pipe,
    convert_dag,
    extract_dependencies,
    parse_pipe_def,
)
from riko.context import Context, ExecutionMode
from riko.exceptions import (
    PipelineStateError,
    RikoError,
    UnsupportedModuleError,
    UnsupportedPipelineError,
)
from riko.modules import describe_module, get_module_metadata, list_modules
from riko.modules._names import Modules, Sinks, Sources, Transforms
from riko.paths import get_path, get_temp_file


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
    "Context",
    "ExecutionMode",
    "Modules",
    "PipeState",
    "PipelineStateError",
    "RikoError",
    "Sinks",
    "Sources",
    "SyncCollection",
    "SyncPipe",
    "Targets",
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
    "list_modules",
    "list_targets",
    "parse_pipe_def",
    "run",
]
