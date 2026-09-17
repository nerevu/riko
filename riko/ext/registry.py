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

    ENTRY_POINT_GROUP: Entry point group scanned for third-party modules.
    registry: Process-global registry backing ``register`` and pipe resolution.

"""

from riko.definitions.modules import ModuleDefinition
from riko.runtime._registry import ModuleRegistry, register, reset_registry

__all__ = ["ModuleDefinition", "ModuleRegistry", "register", "reset_registry"]
