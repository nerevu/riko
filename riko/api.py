# vim: sw=4:ts=4:expandtab
"""
riko.api
~~~~~~~~
The stable, SemVer-guaranteed public surface of riko. Import application code
from here (or the top-level ``riko`` package, which re-exports this module).

Extension-author symbols live in :mod:`riko.ext`; everything else is private.
See docs/MIGRATION.rst for additional details.
"""

from riko.bado import (
    async_read,
    async_return,
    async_sleep,
    backend,
    isasync,
    issync,
    run,
)
from riko.bado.io import async_write, get_async_temp_file
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
    UnsupportedModuleError,
    UnsupportedPipelineError,
)
from riko.modules import describe_module, get_module_metadata, list_modules
from riko.modules._names import Modules, Sinks, Sources, Transforms
from riko.paths import get_path, get_temp_file

__all__ = [
    "AsyncCollection",
    "AsyncPipe",
    "Context",
    "ExecutionMode",
    "Modules",
    "PipeState",
    "PipelineStateError",
    "Sinks",
    "Sources",
    "SyncCollection",
    "SyncPipe",
    "Targets",
    "Transforms",
    "UnsupportedModuleError",
    "UnsupportedPipelineError",
    "async_read",
    "async_return",
    "async_sleep",
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
