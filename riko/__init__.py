# vim: sw=4:ts=4:expandtab
"""
riko
~~~~

Public entry point for riko.

Application code imports stable APIs from ``riko`` or ``riko.api``; extension
authors import from ``riko.ext``. See ``README.rst`` and the cookbook for
worked examples.
"""

from importlib import metadata
from importlib.metadata import PackageMetadata

from riko.context import Context, ExecutionMode  # noqa: F401

# https://github.com/astral-sh/uv/issues/7533#issuecomment-2472804995
_meta: PackageMetadata = metadata.metadata("riko")

PACKAGE_INFO = {
    "__version__": metadata.version("riko"),
    "__title__": _meta["Name"],
    "__package_name__": _meta["Name"],
    "__description__": _meta.get("Summary") or _meta.get("Description", ""),
    "__license__": _meta.get("License-Expression") or _meta.get("License", ""),
    "__author__": _meta.get("Author", ""),
    "__email__": _meta.get("Author-email", ""),
}


def __getattr__(name: str) -> str:
    if name in PACKAGE_INFO:
        return PACKAGE_INFO[name]
    else:
        msg = f"module {__name__} has no attribute {name}"
        raise AttributeError(msg)


__copyright__ = "Copyright 2015 Reuben Cummings"

DEF_CONNECTION_COUNT = 16
ENCODING = "utf-8"

from riko.api import (  # noqa: E402
    AsyncCollection,
    AsyncPipe,
    Modules,
    PipelineStateError,
    PipeState,
    Sinks,
    Sources,
    SyncCollection,
    SyncPipe,
    Targets,
    Transforms,
    UnsupportedModuleError,
    UnsupportedPipelineError,
    async_read,
    async_return,
    async_sleep,
    async_write,
    backend,
    build_pipeline,
    compile_pipe,
    convert_dag,
    describe_module,
    export,
    extract_dependencies,
    get_async_temp_file,
    get_module_metadata,
    get_path,
    get_temp_file,
    isasync,
    issync,
    list_modules,
    list_targets,
    parse_pipe_def,
    run,
)

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
