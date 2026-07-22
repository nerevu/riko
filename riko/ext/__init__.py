# vim: sw=4:ts=4:expandtab
"""
riko.ext
~~~~~~~~
The supported extension-author API: pipe decorators, module metadata, and
parser protocols. SemVer-guaranteed for a smaller audience than the stable
:mod:`riko.api` surface.

Config types (``ParsedConf``/``DynamicConf``) and ``register`` join this
surface in later phases (see docs/API_SURFACE.md).
"""

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
    "ModuleMetadata",
    "ModuleSubtype",
    "ModuleType",
    "ModuleWrapper",
    "SyncOperatorWrapper",
    "SyncProcessorWrapper",
    "SyncSplitterWrapper",
    "operator",
    "processor",
    "splitter",
]
