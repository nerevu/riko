# vim: sw=4:ts=4:expandtab
"""
Stable application API for Riko.

Application code imports from this namespace; extension authors use ``riko.ext``.
``riko.bado`` exposes the supported async-runtime namespace.
"""

from riko.bado._backend import async_chain, async_sleep, backend, isasync, issync, run
from riko.bado._util import async_read, async_return
from riko.bado.itertools import (
    alist,
    as_async,
    async_map,
    async_map_stream,
    materialize,
)
from riko.base._exceptions import (
    EmptyPipelineError,
    InvalidPipelineError,
    PipelineError,
    PipelineStateError,
    RemovedOptionError,
    RikoError,
    UnsupportedModuleError,
    UnsupportedTargetError,
    UnsupportedWorkflowError,
)
from riko.base._paths import get_path
from riko.definitions._context import Context
from riko.definitions._nodes import RikoNode
from riko.definitions._resource_definition import (
    OneShotResource,
    Resource,
    ReusableResource,
)
from riko.definitions._settings import ExecutionSettings
from riko.definitions._workflow_definition import Workflow, WorkflowLike
from riko.definitions._write import WriteMode
from riko.io._async import (
    async_get_temp_file,
    async_get_temp_path,
    async_url_open,
    async_write,
)
from riko.io._sync import get_temp_file, get_temp_path
from riko.modules._metadata import (
    describe_module,
    get_module_metadata,
    list_module_metadata,
    list_modules,
)
from riko.modules._names import Modules, Sinks, Sources, Transforms
from riko.runtime._compile import compile_workflow
from riko.runtime._export import export, list_formats
from riko.runtime._pipeline import Pipeline
from riko.types._enums import (
    Backends,
    CastType,
    DocumentShape,
    Executor,
    FeedType,
    Formats,
    IdentityMode,
    SortableCastType,
    UserAgent,
)
from riko.types._workflow import Endpoint, PortEdge, WorkflowDocument, WorkflowModule

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
    "EmptyPipelineError",
    "Endpoint",
    "ExecutionSettings",
    "Executor",
    "FeedType",
    "Formats",
    "IdentityMode",
    "InvalidPipelineError",
    "Modules",
    "OneShotResource",
    "Pipeline",
    "PipelineError",
    "PipelineStateError",
    "PortEdge",
    "RemovedOptionError",
    "Resource",
    "ReusableResource",
    "RikoError",
    "RikoNode",
    "Sinks",
    "SortableCastType",
    "Sources",
    "Transforms",
    "UnsupportedModuleError",
    "UnsupportedTargetError",
    "UnsupportedWorkflowError",
    "UserAgent",
    "Workflow",
    "WorkflowDocument",
    "WorkflowLike",
    "WorkflowModule",
    "WriteMode",
    "alist",
    "as_async",
    "async_chain",
    "async_get_temp_file",
    "async_get_temp_path",
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
    "get_temp_path",
    "isasync",
    "issync",
    "list_formats",
    "list_module_metadata",
    "list_modules",
    "materialize",
    "run",
]
