"""
Module registration and resolution backing the extension API.

Examples:

    >>> from riko.ext import ModuleDefinition, ModuleRegistry
    >>>
    >>> def pipe(*args, **kwargs):
    ...     return []
    >>> registry = ModuleRegistry()
    >>> registry.register(ModuleDefinition(name="example", sync_pipe=pipe))
    >>> registry.resolve("example") is pipe
    True

Attributes:

    ENTRY_POINT_GROUP: Python entry-point group used for extension modules.
    registry: Process-global registry used by the extension-level ``register`` helper.

"""

from __future__ import annotations

from dataclasses import replace as _replace
from importlib.metadata import EntryPoint, entry_points
from typing import TYPE_CHECKING, Literal, overload

from riko.base.exceptions import UnsupportedModuleError
from riko.definitions.modules import ModuleDefinition

from ._importutils import resolve_interface

if TYPE_CHECKING:
    from riko.types._wrappers import (
        AsyncPipeWrapper,
        Pipe,
        PipeCallable,
        SyncPipeWrapper,
    )

ENTRY_POINT_GROUP = "riko.modules"


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


class ModuleRegistry:
    """
    Resolves module names to their sync/async interface callables.

    Precedence is runtime registration, then entry point
    (``[project.entry-points."riko.modules"]``), then built-in. Only module
    implementations are resolved here. Composed ``pipe_*`` pipelines are the resolver
    façade's concern and no JSON is loaded or compiled.

    Lifetime is hybrid. Built-ins are immutable process-global facts imported lazily
    on first use. This keeps heavy optional dependencies off the startup path. Entry
    points are discovered by name on first lookup so no extension is imported until
    one of its names is resolved. Runtime registrations live in a mutable tier that
    ``reset`` clears for test isolation.

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

    def __init__(self) -> None:
        self._runtime: dict[str, ModuleDefinition] = {}
        self._entry_points: dict[str, EntryPoint] | None = None
        self._loaded: dict[str, ModuleDefinition] = {}

    def _discover_entry_points(self) -> dict[str, EntryPoint]:
        if self._entry_points is None:
            eps = entry_points(group=ENTRY_POINT_GROUP)
            self._entry_points = {ep.name: ep for ep in eps}

        return self._entry_points

    def _entry_point_definition(self, name: str) -> ModuleDefinition | None:
        if name not in self._loaded and (ep := self._discover_entry_points().get(name)):
            loaded = ep.load()
            obj = loaded() if callable(loaded) else loaded
            definition: ModuleDefinition | None = _resolve_definition(obj)

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

            self._loaded[name] = definition

        return self._loaded.get(name)

    def _resolve_builtin(self, name: str, is_async: bool = False) -> Pipe:
        return resolve_interface(name, is_async=is_async)

    def register(self, definition: ModuleDefinition, *, replace: bool = False) -> None:
        """
        Adds a definition to the runtime tier that shadows lower tiers.

        Args:

            definition: Named module definition to register.
            replace: Whether an existing runtime definition with the same name may
                be replaced.

        Raises:

            ValueError: If ``definition`` has no name, or names an already
                registered module and ``replace`` is False.

        Examples:

            >>> registry = ModuleRegistry()
            >>> definition = ModuleDefinition(name="example", sync_pipe=lambda: [])
            >>> registry.register(definition)
            >>> registry.definition("example") is definition
            True

        """
        if not definition.name:
            raise ValueError("a runtime-registered module needs a name")

        if definition.name in self._runtime and not replace:
            raise ValueError(f"module {definition.name!r} is already registered")

        self._runtime[definition.name] = definition

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
        definition = self._runtime.get(name) or self._entry_point_definition(name)

        if definition is None:
            pipe = self._resolve_builtin(name, is_async)
        elif (pipe := definition.get_pipe(is_async)) is None:
            interface = "async_pipe" if is_async else "pipe"
            raise UnsupportedModuleError(f"{name!r} has no {interface!r}")

        return pipe

    def registered_names(self) -> tuple[str, ...]:
        """
        Collects the sorted runtime-registered names.

        Returns:

            Runtime-registered module names in lexical order.

        Examples:

            >>> registry = ModuleRegistry()
            >>> registry.register(ModuleDefinition(name="z", sync_pipe=lambda: []))
            >>> registry.register(ModuleDefinition(name="a", sync_pipe=lambda: []))
            >>> registry.registered_names()
            ('a', 'z')

        """
        return tuple(sorted(self._runtime))

    def catalog_names(self) -> tuple[str, ...]:
        """
        Collects the sorted runtime-registered and entry-point names.

        Built-ins are excluded since the pkgutil catalog enumerates those separately.

        Returns:

            Runtime and discovered entry-point names in lexical order.

        Examples:

            >>> registry = ModuleRegistry()
            >>> registry.register(ModuleDefinition(name="example", sync_pipe=lambda: []))
            >>> "example" in registry.catalog_names()
            True

        """
        return tuple(sorted({*self._runtime, *self._discover_entry_points()}))

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
        return self._runtime.get(name) or self._entry_point_definition(name)

    def reset(self) -> None:
        """
        Drops runtime registrations and the entry-point discovery cache.

        Examples:

            >>> registry = ModuleRegistry()
            >>> registry.register(ModuleDefinition(name="example", sync_pipe=lambda: []))
            >>> registry.reset()
            >>> registry.registered_names()
            ()

        """
        self._runtime.clear()
        self._loaded.clear()
        self._entry_points = None


registry: ModuleRegistry = ModuleRegistry()


def register(definition: ModuleDefinition, *, replace: bool = False) -> None:
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

        >>> from riko.ext import ModuleDefinition, register
        >>>
        >>> reset_registry()
        >>> definition = ModuleDefinition(name="__doctest__", sync_pipe=lambda: [])
        >>> register(definition)
        >>> registry.definition("__doctest__") is definition
        True
        >>> reset_registry()

    """
    registry.register(definition, replace=replace)


def reset_registry() -> None:
    """
    Resets the process-global registry, chiefly for test isolation.

    Examples:

        >>> registry.register(ModuleDefinition(name="__doctest__", sync_pipe=lambda: []))
        >>> reset_registry()
        >>> registry.registered_names()
        ()

    """
    registry.reset()
