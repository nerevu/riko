"""
Module registration and resolution backing the extension API.

Examples:

    Basic usage::

        >>> from riko import Sources
        >>> from riko.modules.fetch import pipe as fetch
        >>> from riko.ext import ModuleDefinition, ModuleRegistry
        >>>
        >>> registry = ModuleRegistry()
        >>> registry.resolve(Sources.FETCH) is fetch
        True
        >>> def example(conf, **kwargs):
        ...     return []
        >>>
        >>> registry.register(ModuleDefinition(sync_pipe=example))
        >>> registry.resolve("example") is example
        True

Attributes:

    module_registry: Process-global registry backing ``register_module`` and pipe
        resolution.

"""

from __future__ import annotations

from dataclasses import replace as _replace
from typing import TYPE_CHECKING, Literal, overload

from riko.base.exceptions import UnsupportedModuleError
from riko.definitions.modules import ModuleDefinition

from ._importutils import resolve_interface
from ._registry import Registry

if TYPE_CHECKING:
    from importlib.metadata import EntryPoint

    from riko.types._wrappers import (
        AsyncPipeWrapper,
        Pipe,
        PipeCallable,
        SyncPipeWrapper,
    )


def _module_summary(module: object) -> str | None:
    lines = (getattr(module, "__doc__", "") or "").strip().splitlines()
    return next((line.strip() for line in lines if line.strip()), None)


def _resolve_definition(obj: object) -> ModuleDefinition | None:
    """Passes a ``ModuleDefinition`` through, and wraps a bare pipe-exposing module."""
    if isinstance(obj, ModuleDefinition):
        definition = obj
    elif hasattr(obj, "pipe") or hasattr(obj, "async_pipe"):
        definition = ModuleDefinition(module=obj, description=_module_summary(obj))
    else:
        definition = None

    return definition


class ModuleRegistry(Registry[ModuleDefinition]):
    """
    Resolves module names to their sync/async interface callables.

    Precedence is runtime registration, then entry point
    (``[project.entry-points."riko.modules"]``), then built-in. Only module
    implementations are resolved here. Composed ``pipe_*`` pipelines are the resolver
    façade's concern and no JSON is loaded or compiled. Built-ins are imported lazily
    on first use so heavy optional dependencies stay off the startup path.

    Examples:

        >>> from riko.ext import ModuleDefinition, ModuleRegistry
        >>>
        >>> def pipe(*args, **kwargs):
        ...     return []
        >>> registry = ModuleRegistry()
        >>> registry.register(ModuleDefinition(name="example", sync_pipe=pipe))
        >>> registry.registered_names()
        ('example',)
        >>> registry.resolve("example") is pipe
        True

    """

    entry_point_group = "riko.modules"
    label = "module"

    def _key(self, entry: ModuleDefinition) -> str:
        return entry.resolved_name

    def _load(self, ep: EntryPoint) -> ModuleDefinition:
        loaded = ep.load()
        obj = loaded() if callable(loaded) else loaded
        definition = _resolve_definition(obj)

        if definition is None:
            raise TypeError(
                f"entry point {ep.name!r} returned {type(obj).__name__}, expected a"
                " ModuleDefinition or a module exposing 'pipe'/'async_pipe'"
            )
        elif not definition.name:
            definition = _replace(definition, name=ep.name)
        elif definition.name != ep.name:
            raise ValueError(
                f"entry point {ep.name!r} declares a module named "
                f"{definition.name!r}; the two must match"
            )

        return definition

    def _resolve_builtin(self, name: str, is_async: bool = False) -> Pipe:
        return resolve_interface(name, is_async=is_async)

    @overload
    def resolve(  # noqa: E704
        self, name: str, is_async: Literal[False] = ...
    ) -> SyncPipeWrapper: ...
    @overload  # noqa: E301
    def resolve(  # noqa: E704
        self, name: str, is_async: Literal[True]
    ) -> AsyncPipeWrapper: ...
    def resolve(self, name: str, is_async: bool = False) -> Pipe | PipeCallable:  # noqa: E301
        """
        Resolves a module's sync or async callable, honoring tier precedence.

        Args:

            name: Canonical module name to resolve.
            is_async: Whether to resolve the async interface.

        Returns:

            The selected pipe callable from the runtime, entry-point, or built-in
            tier.

        Raises:

            UnsupportedModuleError: If no tier defines ``name``, or the tier that
                does has no requested interface callable.

        Examples:

            >>> def pipe(*args, **kwargs):
            ...     return []
            >>> registry = ModuleRegistry()
            >>> registry.register(ModuleDefinition(name="example", sync_pipe=pipe))
            >>> registry.resolve("example") is pipe
            True

        """
        definition = self._registered(name)

        if definition is None:
            pipe = self._resolve_builtin(name, is_async)
        elif (pipe := definition.get_pipe(is_async)) is None:
            interface = "async_pipe" if is_async else "pipe"
            raise UnsupportedModuleError(f"{name!r} has no {interface!r}")

        return pipe

    def definition(self, name: str) -> ModuleDefinition | None:
        """
        Resolves a runtime or entry-point definition by name.

        Args:

            name: Canonical module name to inspect.

        Returns:

            The matching definition, or ``None`` for a built-in or unknown name.

        Examples:

            >>> registry = ModuleRegistry()
            >>> definition = ModuleDefinition(name="example", sync_pipe=lambda: [])
            >>> registry.register(definition)
            >>> registry.definition("example") is definition
            True

        """
        return self._registered(name)


module_registry: ModuleRegistry = ModuleRegistry()


def register_module(definition: ModuleDefinition, *, replace: bool = False) -> None:
    """
    Registers a module on the process-global registry.

    Args:

        definition: Named module definition to register.
        replace: Whether an existing runtime definition with the same name may be
            replaced.

    Raises:

        ValueError: If ``definition`` has no name, or names an already registered
            module and ``replace`` is False.

    Examples:

        >>> from riko.ext import ModuleDefinition, register_module
        >>>
        >>> reset_module_registry()
        >>> definition = ModuleDefinition(name="__doctest__", sync_pipe=lambda: [])
        >>> register_module(definition)
        >>> module_registry.definition("__doctest__") is definition
        True
        >>> reset_module_registry()

    """
    module_registry.register(definition, replace=replace)


def reset_module_registry() -> None:
    """
    Resets the process-global registry, chiefly for test isolation.

    Examples:

        >>> module_registry.register(
        ...     ModuleDefinition(name="__doctest__", sync_pipe=lambda: [])
        ... )
        >>> reset_module_registry()
        >>> module_registry.registered_names()
        ()

    """
    module_registry.reset()


__all__ = [
    "ModuleRegistry",
    "module_registry",
    "register_module",
    "reset_module_registry",
]
