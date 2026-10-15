# vim: sw=4:ts=4:expandtab
"""
Stable application API for Riko.

Application code imports from this namespace; extension authors use ``riko.ext``.
``riko.bado`` exposes the supported async-runtime namespace.
"""

from riko.bado._backend import async_chain, async_sleep, backend, isasync, issync, run
from riko.bado._util import async_read, async_return
from riko.bado.itertools import as_async, async_map, async_map_stream
from riko.base._paths import get_path, get_temp_file
from riko.base.exceptions import (
    EmptyPipelineError,
    InvalidPipelineError,
    PipelineError,
    PipelineStateError,
    RikoError,
    UnsupportedModuleError,
    UnsupportedWorkflowError,
)
from riko.definitions._context import Context
from riko.definitions._nodes import Node
from riko.definitions._workflow import Workflow, WorkflowLike
from riko.io._async import async_get_temp_file, async_url_open, async_write
from riko.modules._metadata import describe_module, get_module_metadata, list_modules
from riko.modules._names import Modules, Sinks, Sources, Transforms
from riko.runtime._codegen import compile_workflow
from riko.runtime._pipeline import Pipeline
from riko.runtime.collections import export, list_formats
from riko.types._enums import (
    Backends,
    CastType,
    DocumentShape,
    ExecutionMode,
    Executor,
    Formats,
)
from riko.types._workflow import Edge, Endpoint, WorkflowDocument, WorkflowModule

from ._package import PACKAGE_INFO


def __getattr__(name: str) -> str:
    if name in PACKAGE_INFO:
        return PACKAGE_INFO[name]
    else:
        msg = f"module {__name__} has no attribute {name}"
        raise AttributeError(msg)


__copyright__ = "Copyright 2015 Reuben Cummings"

__all__ = [
    "Backends",
    "CastType",
    "Context",
    "DocumentShape",
    "Edge",
    "EmptyPipelineError",
    "Endpoint",
    "ExecutionMode",
    "Executor",
    "Formats",
    "InvalidPipelineError",
    "Modules",
    "Node",
    "Pipeline",
    "PipelineError",
    "PipelineStateError",
    "RikoError",
    "Sinks",
    "Sources",
    "Transforms",
    "UnsupportedModuleError",
    "UnsupportedWorkflowError",
    "Workflow",
    "WorkflowDocument",
    "WorkflowLike",
    "WorkflowModule",
    "as_async",
    "async_chain",
    "async_get_temp_file",
    "async_map",
    "async_map_stream",
    "async_read",
    "async_return",
    "async_sleep",
    "async_url_open",
    "async_write",
    "backend",
    "compile_workflow",
    "describe_module",
    "export",
    "get_module_metadata",
    "get_path",
    "get_temp_file",
    "isasync",
    "issync",
    "list_formats",
    "list_modules",
    "run",
]
