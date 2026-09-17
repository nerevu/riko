# vim: sw=4:ts=4:expandtab
"""
Provides registration and resolution for named modules.

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
        >>> list(registry.resolve("double")([{"x": 2}]))
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

__all__ = [
    "ModuleDefinition",
    "ModuleRegistry",
    "register_module",
    "reset_module_registry",
]
