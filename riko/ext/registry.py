# vim: sw=4:ts=4:expandtab
"""
Provides registration and resolution for named modules and workflows.

Resolution order is runtime registration, entry point, then built-in module.

Examples:

    Basic usage::

        >>> from riko.ext import ModuleDefinition, ModuleRegistry
        >>>
        >>> def double(stream, **kwargs):
        ...     return ({"x": item["x"] * 2} for item in stream)
        >>>
        >>> registry = ModuleRegistry()
        >>> registry.register(ModuleDefinition(name="double", sync_pipe=double))
        >>> list(registry.require("double")([{"x": 2}]))
        [{'x': 4}]

Attributes:

    module_registry: Process-global registry backing ``register_module`` and pipe
        resolution.

"""

from riko.definitions.modules import ModuleDefinition
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
from riko.runtime._workflows import register_workflow_store, reset_workflow_resolver

__all__ = [
    "ModuleDefinition",
    "ModuleRegistry",
    "TargetRegistry",
    "register_module",
    "register_target",
    "register_workflow_store",
    "reset_module_registry",
    "reset_target_registry",
    "reset_workflow_resolver",
]
