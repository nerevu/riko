# vim: sw=4:ts=4:expandtab
"""
riko.ext
~~~~~~~~

Stable, SemVer-guaranteed API for riko extension authors.

This namespace contains pipe decorators, configuration helpers, module
metadata and naming types, wrapper protocols, and registry interfaces.
"""

from riko.coercion._dynamic_conf import DynamicConf
from riko.definitions.modules import ModuleDefinition, resolve_module_name
from riko.modules._decorators import operator, processor, splitter
from riko.runtime._registry import ModuleRegistry, register
from riko.types._enums import ModuleName, ModuleNameLike
from riko.types._wrappers import (
    AsyncOperatorWrapper,
    AsyncProcessorWrapper,
    AsyncSplitterWrapper,
    ModuleWrapper,
    SyncOperatorWrapper,
    SyncProcessorWrapper,
    SyncSplitterWrapper,
)
from riko.types.modules import ModuleMetadata, ModuleSubtype, ModuleType

from ._names import derive_category
from .config import get_conf_type

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
    "operator",
    "processor",
    "register",
    "resolve_module_name",
    "splitter",
]
