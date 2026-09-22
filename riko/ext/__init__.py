# vim: sw=4:ts=4:expandtab
"""
Stable, SemVer-guaranteed API for riko extension authors.

This namespace contains pipe decorators, configuration helpers, module
metadata and naming types, wrapper protocols, and registry interfaces.
"""

from riko.coercion._dynamic_conf import DynamicConf
from riko.definitions._targets import FileTarget
from riko.definitions._workflow import (
    ActionNode,
    CacheNode,
    ModuleNode,
    PublishEdge,
    ReadNode,
    StreamEdge,
    SubscribeNode,
    WorkflowSpec,
    WriteNode,
)
from riko.definitions._write import WriteCapabilities
from riko.definitions.modules import ModuleDefinition, normalize_module_name
from riko.modules._decorators import operator, processor, splitter
from riko.runtime._module_registry import ModuleRegistry, register_module
from riko.runtime._normalize import normalize_workflow
from riko.runtime._target_registry import TargetRegistry, register_target
from riko.runtime._validate import validate_workflow
from riko.types._enums import ModuleName, ModuleNameLike
from riko.types._targets import SupportsActions, SupportsRead, SupportsWrite, Target
from riko.types._workflow import Endpoint
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

from ._names import get_module_category
from .config import get_conf_type

__all__ = [
    "ActionNode",
    "AsyncOperatorWrapper",
    "AsyncProcessorWrapper",
    "AsyncSplitterWrapper",
    "CacheNode",
    "DynamicConf",
    "Endpoint",
    "FileTarget",
    "ModuleDefinition",
    "ModuleMetadata",
    "ModuleName",
    "ModuleNameLike",
    "ModuleNode",
    "ModuleRegistry",
    "ModuleSubtype",
    "ModuleType",
    "ModuleWrapper",
    "PublishEdge",
    "ReadNode",
    "StreamEdge",
    "SubscribeNode",
    "SupportsActions",
    "SupportsRead",
    "SupportsWrite",
    "SyncOperatorWrapper",
    "SyncProcessorWrapper",
    "SyncSplitterWrapper",
    "Target",
    "TargetRegistry",
    "WorkflowSpec",
    "WriteCapabilities",
    "WriteNode",
    "get_conf_type",
    "get_module_category",
    "normalize_module_name",
    "normalize_workflow",
    "operator",
    "processor",
    "register_module",
    "register_target",
    "splitter",
    "validate_workflow",
]
