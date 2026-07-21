# vim: sw=4:ts=4:expandtab
"""
riko.api
~~~~~~~~
The stable, SemVer-guaranteed public surface of riko. Import application code
from here (or the top-level ``riko`` package, which re-exports this module).

Extension-author symbols live in :mod:`riko.ext`; everything else is private.
See docs/API_SURFACE.md for the full three-tier contract.
"""

from riko.collections import (
    AsyncCollection,
    AsyncPipe,
    SyncCollection,
    SyncPipe,
    export,
    list_targets,
)
from riko.context import Context
from riko.exceptions import UnsupportedModuleError, UnsupportedPipelineError
from riko.modules import list_modules

__all__ = [
    "AsyncCollection",
    "AsyncPipe",
    "Context",
    "SyncCollection",
    "SyncPipe",
    "UnsupportedModuleError",
    "UnsupportedPipelineError",
    "export",
    "list_modules",
    "list_targets",
]
