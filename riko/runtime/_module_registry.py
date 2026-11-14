"""
Module registration and resolution backing the extension API.

Examples:

    Basic usage::

        >>> from riko import Sources
        >>> from riko.modules.fetch import pipe as fetch
        >>> from riko.ext import ModuleDefinition, ModuleRegistry
        >>>
        >>> registry = ModuleRegistry()
        >>> registry.require(Sources.FETCH) is fetch
        True
        >>> def example(conf, **kwargs):
        ...     return []
        >>>
        >>> registry.register(ModuleDefinition(sync_pipe=example))
        >>> registry.require("example") is example
        True

Attributes:

    module_registry: Process-global registry backing ``register_module`` and pipe
        resolution.

"""

from __future__ import annotations

from typing import TYPE_CHECKING, Literal, overload

from attrs import evolve

from riko.base._exceptions import UnsupportedModuleError
from riko.definitions._module_definition import ModuleDefinition, normalize_module_name
from riko.types._module_ids import BUILTIN_MODULE_IDS
from riko.types._pipedef import is_pipe_id

from ._importutils import load_interfaces, require_interface
from ._registry import Registry

if TYPE_CHECKING:
    from importlib.metadata import EntryPoint

    from riko.types._enums import ModuleNameLike
    from riko.types._wrappers import (
        AsyncModuleWrapper,
        Interface,
        ModuleWrapper,
        SyncModuleWrapper,
    )


def _resolve_definition(obj: object, name: str) -> ModuleDefinition | None:
    """Passes a ``ModuleDefinition`` through, and wraps a bare pipe-exposing module."""
    if isinstance(obj, ModuleDefinition):
        definition = obj
    elif hasattr(obj, "pipe") or hasattr(obj, "async_pipe"):
        definition = ModuleDefinition.from_module(obj, name=name)
    else:
        definition = None

    return definition


class ModuleRegistry(Registry[ModuleDefinition]):
    """
    Resolves module names to their ``pipe``/``async_pipe`` callables.

    Precedence is runtime registration, entry point
    (``[project.entry-points."riko.modules"]``), built-in. A runtime registration
    shadows an entry-point or built-in module only when registered with
    ``replace=True``.

    Only module implementations are resolved here. Stored workflows (looked up by their
    ``pipe_<id>`` names) are the workflow resolver's concern, and no JSON is loaded or
    compiled. Built-ins are imported lazily on first use so heavy optional dependencies
    stay off the startup path.

    Examples:

        >>> from riko.ext import ModuleDefinition, ModuleRegistry
        >>>
        >>> def pipe(*args, **kwargs):
        ...     return []
        >>>
        >>> registry = ModuleRegistry()
        >>> registry.register(ModuleDefinition(name="example", sync_pipe=pipe))
        >>> registry.registered_names
        ('example',)
        >>> registry.require("example") is pipe
        True

    """

    entry_point_group = "riko.modules"
    label = "module"
    builtin_names = BUILTIN_MODULE_IDS

    def _key(self, entry: ModuleDefinition) -> str:
        return entry.name

    def _load(self, ep: EntryPoint) -> ModuleDefinition:
        loaded = ep.load()
        obj = loaded() if callable(loaded) else loaded

        if (definition := _resolve_definition(obj, ep.name)) is None:
            msg = f"entry point {ep.name!r} returned {type(obj).__name__}, expected a "
            msg += "ModuleDefinition or a module exposing 'pipe'/'async_pipe'"
            raise TypeError(msg)
        elif not definition.declared_name:
            definition = evolve(definition, name=ep.name)

        return definition

    def _require_builtin_name(self, name: str) -> None:
        if name not in BUILTIN_MODULE_IDS:
            candidates = BUILTIN_MODULE_IDS.union(self.discovered_names)
            raise UnsupportedModuleError(name, candidates=candidates)

    def _resolve_builtin(self, name: str, is_async: bool = False) -> ModuleWrapper:
        return require_interface(name, is_async=is_async)

    def is_compatible(self, name: ModuleNameLike) -> bool:
        return not is_pipe_id(name)

    @overload
    def require(
        self, name: ModuleNameLike, is_async: Literal[False] = ...
    ) -> SyncModuleWrapper: ...
    @overload
    def require(
        self, name: ModuleNameLike, is_async: Literal[True]
    ) -> AsyncModuleWrapper: ...
    def require(self, name: ModuleNameLike, is_async: bool = False) -> ModuleWrapper:
        """
        Finds a module's sync or async callable by tier precedence, or raises.

        Args:

            name: Module name to resolve.

        Kwargs:

            is_async: Whether to resolve the ``async_pipe``.

        Returns:

            The selected pipe callable from the runtime, entry-point, or built-in
            tier.

        Raises:

            UnsupportedModuleError: If no tier defines ``name``, or the tier that
                does has no requested interface callable.

        Examples:

            >>> def pipe(*args, **kwargs):
            ...     return []
            >>>
            >>> registry = ModuleRegistry()
            >>> registry.register(ModuleDefinition(name="example", sync_pipe=pipe))
            >>> registry.require("example") is pipe
            True

        """
        canonical = normalize_module_name(name)

        if (definition := self._load_entry(canonical)) is None:
            self._require_builtin_name(canonical)
            pipe = self._resolve_builtin(canonical, is_async)
        elif (pipe := definition.get_pipe(is_async)) is None:
            interface = "async_pipe" if is_async else "pipe"
            raise UnsupportedModuleError(canonical, f"it has no {interface!r}")

        return pipe

    def require_interfaces(self, name: ModuleNameLike) -> frozenset[Interface]:
        """
        Finds which of ``pipe`` and ``async_pipe`` a module defines.

        Args:

            name: Module name to inspect.

        Returns:

            The subset of ``pipe``/``async_pipe`` a caller may resolve.

        Raises:

            UnsupportedModuleError: If no tier defines ``name``.

        Examples:

            >>> registry = ModuleRegistry()
            >>> sync_pipe = lambda s, **_: s
            >>> registry.register(ModuleDefinition(name="example", sync_pipe=sync_pipe))
            >>> sorted(registry.require_interfaces("example"))
            ['pipe']

        """
        canonical = normalize_module_name(name)

        if (definition := self._load_entry(canonical)) is None:
            self._require_builtin_name(canonical)
            interfaces = load_interfaces(canonical)
        else:
            interfaces = definition.interfaces

        return interfaces

    def load_definition(self, name: ModuleNameLike) -> ModuleDefinition | None:
        """
        Loads a runtime or entry-point definition by name.

        Args:

            name: Module name to inspect.

        Returns:

            The matching definition, or ``None`` for a built-in or unknown name.

        Examples:

            >>> registry = ModuleRegistry()
            >>> definition = ModuleDefinition(name="example", sync_pipe=lambda: [])
            >>> registry.register(definition)
            >>> registry.load_definition("example") is definition
            True

        """
        return self._load_entry(normalize_module_name(name))


module_registry: ModuleRegistry = ModuleRegistry()


def register_module(definition: ModuleDefinition, *, replace: bool = False) -> None:
    """
    Registers a module on the process-global registry.

    Args:

        definition: Named module definition to register.

    Kwargs:

        replace: Whether the definition may replace an existing runtime
            registration, or shadow an entry-point or built-in module.

    Raises:

        ValueError: If ``definition`` has no name, or names an already registered,
            entry-point, or built-in module and ``replace`` is False.

    Examples:

        >>> from riko.ext import ModuleDefinition, register_module
        >>> from riko.ext import temporary_registrations
        >>>
        >>> definition = ModuleDefinition(name="__doctest__", sync_pipe=lambda: [])
        >>> with temporary_registrations():
        ...     register_module(definition)
        ...     module_registry.load_definition("__doctest__") is definition
        True

    """
    module_registry.register(definition, replace=replace)


__all__ = ["ModuleRegistry", "module_registry", "register_module"]
