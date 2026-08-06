# vim: sw=4:ts=4:expandtab
"""
riko
~~~~
Provides functions for analyzing and processing streams of structured data

Examples:
    basic usage::

        >>> from riko.modules.itembuilder import pipe as itembuilder
        >>> from riko.modules.strreplace import pipe as strreplace
        >>> from riko.collections import SyncPipe
        >>>
        >>> ib_conf = {
        ...     'attrs': [
        ...         {'key': 'link', 'value': 'www.google.com'},
        ...         {'key': 'title', 'value': 'google'},
        ...         {'key': 'author', 'value': 'Tommy'}
        ...      ]
        ... }
        >>>
        >>> items = itembuilder(conf=ib_conf)
        >>> next(items)
        {'link': 'www.google.com', 'title': 'google', 'author': 'Tommy'}
        >>> sr_conf = {
        ...     'rule': [{'find': 'Tom', 'param': 'first', 'replace': 'Tim'}]
        ... }
        >>>
        >>> items = itembuilder(conf=ib_conf)
        >>> replaced = strreplace(next(items), conf=sr_conf, field='author')
        >>> next(replaced)['strreplace']
        'Timmy'

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
    PipelineStateError,
    PipeState,
    SyncCollection,
    SyncPipe,
    UnsupportedModuleError,
    UnsupportedPipelineError,
    export,
    get_path,
    list_modules,
    list_targets,
)

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
    "export",
    "get_path",
    "list_modules",
    "list_targets",
]
