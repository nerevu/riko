# vim: sw=4:ts=4:expandtab
"""
Stable, SemVer-guaranteed API for riko extension authors.

This namespace contains pipe decorators, configuration helpers, module
metadata and naming types; wrapper protocols, target and workflow authoring
contracts; and registry interfaces.

The names are grouped by extension point in the ``modules``, ``targets``, and
``workflows`` submodules and re-exported here. ``codegen`` generates typed
discovery names for a plugin.
"""

from riko.coercion._dynamic_conf import DynamicConf
from riko.definitions._inputs import resolve_inputs
from riko.definitions._module_definition import ModuleDefinition, normalize_module_name
from riko.definitions._nodes import (
    ActionNode,
    CacheNode,
    CallableNode,
    ModuleNode,
    PublishEdge,
    ReadNode,
    StreamEdge,
    SubscribeNode,
    WriteNode,
)
from riko.definitions._targets import FileTarget
from riko.definitions._write import WriteCapabilities
from riko.modules._decorators import operator, processor, splitter
from riko.runtime._module_registry import ModuleRegistry, register_module
from riko.runtime._registrations import temporary_registrations
from riko.runtime._target_registry import TargetRegistry, register_target
from riko.runtime._workflow_pipes import workflow
from riko.runtime._workflow_resolver import register_workflow_store
from riko.types._enums import ModuleName, ModuleNameLike
from riko.types._target_protocols import (
    SupportsActions,
    SupportsRead,
    SupportsWrite,
    Target,
)
from riko.types._wrappers import (
    AsyncOperatorWrapper,
    AsyncProcessorWrapper,
    AsyncSplitterWrapper,
    Dispatcher,
    ModuleWrapper,
    PreparedCall,
    SyncOperatorWrapper,
    SyncProcessorWrapper,
    SyncSplitterWrapper,
)
from riko.types.modules import ModuleMetadata, ModuleSubtype, ModuleType

from .modules import get_conf_type

__all__ = [
    "ActionNode",
    "AsyncOperatorWrapper",
    "AsyncProcessorWrapper",
    "AsyncSplitterWrapper",
    "CacheNode",
    "CallableNode",
    "Dispatcher",
    "DynamicConf",
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
    "PreparedCall",
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
    "WriteCapabilities",
    "WriteNode",
    "get_conf_type",
    "normalize_module_name",
    "operator",
    "processor",
    "register_module",
    "register_target",
    "register_workflow_store",
    "resolve_inputs",
    "splitter",
    "temporary_registrations",
    "workflow",
]
