# vim: sw=4:ts=4:expandtab
"""
riko.ext
~~~~~~~~
The supported extension-author API: pipe decorators, parsed config types,
module metadata, and parser protocols. SemVer-guaranteed for a smaller audience
than the stable :mod:`riko.api` surface.

``register`` joins this surface in a later phase (see docs/API_SURFACE.md).
"""

from riko.ext.config import DynamicConf, get_conf_type
from riko.ext.decorators import operator, processor, splitter
from riko.ext.protocols import (
    AsyncOperatorWrapper,
    AsyncProcessorWrapper,
    AsyncSplitterWrapper,
    ModuleWrapper,
    SyncOperatorWrapper,
    SyncProcessorWrapper,
    SyncSplitterWrapper,
)
from riko.modules import ModuleMetadata, ModuleSubtype, ModuleType

__all__ = [
    "AsyncOperatorWrapper",
    "AsyncProcessorWrapper",
    "AsyncSplitterWrapper",
    "DynamicConf",
    "ModuleMetadata",
    "ModuleSubtype",
    "ModuleType",
    "ModuleWrapper",
    "SyncOperatorWrapper",
    "SyncProcessorWrapper",
    "SyncSplitterWrapper",
    "get_conf_type",
    "operator",
    "processor",
    "splitter",
]
