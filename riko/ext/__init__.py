# vim: sw=4:ts=4:expandtab
"""
riko.ext
~~~~~~~~

Stable, SemVer-guaranteed API for riko extension authors.

This namespace contains pipe decorators, configuration helpers, module
metadata and naming types, wrapper protocols, and registry interfaces.
"""

from riko.types._names import ModuleNameLike
from riko.types.modules import ModuleMetadata, ModuleSubtype, ModuleType

from .config import DynamicConf, get_conf_type
from .decorators import operator, processor, splitter
from .names import ModuleName, derive_category, normalize_module_name
from .protocols import (
    AsyncOperatorWrapper,
    AsyncProcessorWrapper,
    AsyncSplitterWrapper,
    ModuleWrapper,
    SyncOperatorWrapper,
    SyncProcessorWrapper,
    SyncSplitterWrapper,
)
from .registry import ModuleDefinition, ModuleRegistry, register

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
