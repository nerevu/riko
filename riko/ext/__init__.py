# vim: sw=4:ts=4:expandtab
"""
Stable, SemVer-guaranteed API for riko extension authors.

This namespace contains pipe decorators, configuration helpers, module
metadata and naming types; wrapper protocols, target and workflow authoring
contracts; and registry interfaces.

The names are grouped by extension point in the ``modules``, ``targets``, and
``workflows`` submodules and re-exported here. ``codegen`` generates typed
discovery names for an extension package.
"""

from riko.coercion._dynamic_conf import DynamicConf
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
from riko.definitions._workflow_definition import migrate_v1_to_v2, normalize_workflow
from riko.definitions._write import WriteCapabilities
from riko.modules._decorators import operator, processor, splitter
from riko.modules._metadata import get_module_category
from riko.runtime._module_registry import (
    ModuleRegistry,
    register_module,
    reset_module_registry,
)
from riko.runtime._target_registry import (
    TargetRegistry,
    register_target,
    reset_target_registry,
)
from riko.runtime._workflow_resolver import (
    register_workflow_store,
    reset_workflow_resolver,
)
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
    "get_module_category",
    "migrate_v1_to_v2",
    "normalize_module_name",
    "normalize_workflow",
    "operator",
    "processor",
    "register_module",
    "register_target",
    "register_workflow_store",
    "reset_module_registry",
    "reset_target_registry",
    "reset_workflow_resolver",
    "splitter",
]
