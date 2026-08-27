# vim: sw=4:ts=4:expandtab
"""
riko.ext
~~~~~~~~
The supported extension-author API: pipe decorators, parsed config types,
module metadata, and parser protocols. SemVer-guaranteed for a smaller audience
than the stable :mod:`riko.api` surface.

``register`` joins this surface in a later phase. See docs/MIGRATION.rst for additional
details.
"""

from riko.ext.config import DynamicConf, get_conf_type
from riko.ext.decorators import operator, processor, splitter
from riko.ext.names import ModuleName, derive_category, normalize_module_name
from riko.ext.protocols import (
    AsyncOperatorWrapper,
    AsyncProcessorWrapper,
    AsyncSplitterWrapper,
    ModuleWrapper,
    SyncOperatorWrapper,
    SyncProcessorWrapper,
    SyncSplitterWrapper,
)
from riko.ext.registry import ModuleDefinition, ModuleRegistry, register
from riko.types.modules import ModuleMetadata, ModuleSubtype, ModuleType
from riko.types.values import ModuleNameLike

__all__ = [
    "AsyncOperatorWrapper",
    "AsyncProcessorWrapper",
    "AsyncSplitterWrapper",
    "DynamicConf",
    "ModuleDefinition",
    "ModuleMetadata",
    "ModuleName",
    "ModuleNameLike",
    "ModuleRegistry",
    "ModuleSubtype",
    "ModuleType",
    "ModuleWrapper",
    "SyncOperatorWrapper",
    "SyncProcessorWrapper",
    "SyncSplitterWrapper",
    "derive_category",
    "get_conf_type",
    "normalize_module_name",
    "operator",
    "processor",
    "register",
    "splitter",
]
