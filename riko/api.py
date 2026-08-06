# vim: sw=4:ts=4:expandtab
"""
riko.api
~~~~~~~~
The stable, SemVer-guaranteed public surface of riko. Import application code
from here (or the top-level ``riko`` package, which re-exports this module).

Extension-author symbols live in :mod:`riko.ext`; everything else is private.
See docs/API_STABILITY.md for additional details.
"""

from riko.bado import backend, isasync, issync, run
from riko.collections import (
    AsyncCollection,
    AsyncPipe,
    PipeState,
    SyncCollection,
    SyncPipe,
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
from riko.modules import get_module_metadata, list_modules
from riko.paths import get_path

__all__ = [
    "AsyncCollection",
    "AsyncPipe",
    "Context",
    "ExecutionMode",
    "PipeState",
    "PipelineStateError",
    "SyncCollection",
    "SyncPipe",
    "UnsupportedModuleError",
    "UnsupportedPipelineError",
    "backend",
    "build_pipeline",
    "compile_pipe",
    "convert_dag",
    "export",
    "extract_dependencies",
    "get_module_metadata",
    "get_path",
    "isasync",
    "issync",
    "list_modules",
    "list_targets",
    "parse_pipe_def",
    "run",
]
