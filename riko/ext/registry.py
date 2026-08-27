# vim: sw=4:ts=4:expandtab
"""
riko.ext.registry
~~~~~~~~~~~~~~~~~

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
        >>> list(registry.resolve("double", "pipe")([{"x": 2}]))
        [{'x': 4}]

Attributes:
    ENTRY_POINT_GROUP: Entry point group scanned for third-party modules.
    registry: Process-global registry backing ``register`` and pipe resolution.

"""

from dataclasses import dataclass
from dataclasses import replace as _replace
from importlib.metadata import EntryPoint, entry_points
from typing import Literal, cast, overload

from riko._importutils import import_or_else
from riko.exceptions import UnsupportedModuleError
from riko.types.general import (
    AsyncPipeCallable,
    AsyncPipeParser,
    Interface,
    Pipeline,
    SyncPipeCallable,
    SyncPipeParser,
)

ENTRY_POINT_GROUP = "riko.modules"


@dataclass(frozen=True, slots=True)
class ModuleDefinition:
    """
    Defines a named module and its sync/async pipe callables.

    Callables may be given directly, or read off ``module`` on demand. This lets an
    extension point at a module exposing ``pipe``/``async_pipe`` by the same convention
    as a built-in.

    Attributes:
        name: Canonical identifier. Required by ``register``, but optional for an
            entry-point definition. The registry stamps it from the entry-point key
            so the external declaration stays the single source of truth.

        sync_pipe: Sync interface callable. Wins over ``module``'s ``pipe``.

        async_pipe: Async interface callable. Wins over ``module``'s ``async_pipe``.

        module: Object to read the interface callables off of.

        description: Summary used by module discovery.

    """

    name: str = ""
    sync_pipe: SyncPipeCallable | None = None
    async_pipe: AsyncPipeCallable | None = None
    module: object | None = None
    description: str | None = None

    def get_pipe(self, interface: Interface) -> Pipeline | None:
        """Returns the callable for ``interface``, or ``None`` if undefined."""
        pipe = self.sync_pipe if interface == "pipe" else self.async_pipe

        if pipe is None and self.module is not None:
            pipe = getattr(self.module, interface, None)

        return cast(Pipeline | None, pipe)


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
            _definition = loaded() if callable(loaded) else loaded
            definition = cast(ModuleDefinition, _definition)

            if not definition.name:
                definition = _replace(definition, name=ep.name)
            elif definition.name != ep.name:
                raise ValueError(
                    f"entry point {ep.name!r} declares a module named "
                    f"{definition.name!r}; the two must match"
                )

            self._loaded[name] = definition

        return self._loaded.get(name)

    def _resolve_builtin(self, name: str, interface: Interface) -> Pipeline:
        if module := import_or_else(f"riko.modules.{name}"):
            if (resolved := getattr(module, interface, None)) is None:
                raise UnsupportedModuleError(f"{name!r} has no {interface!r}")
        else:
            raise UnsupportedModuleError(name)

        return resolved

    def register(self, definition: ModuleDefinition, *, replace: bool = False) -> None:
        """
        Adds ``definition`` to the runtime tier that shadows any lower tier.

        Raises:
            ValueError: If ``definition`` has no name, or names an already
                registered module and ``replace`` is False.

        """
        if not definition.name:
            raise ValueError("a runtime-registered module needs a name")

        if definition.name in self._runtime and not replace:
            raise ValueError(f"module {definition.name!r} is already registered")

        self._runtime[definition.name] = definition

    @overload
    def resolve(  # noqa: E704
        self, name: str, interface: Literal["pipe"]
    ) -> SyncPipeParser: ...
    @overload  # noqa: E301
    def resolve(  # noqa: E704
        self, name: str, interface: Literal["async_pipe"]
    ) -> AsyncPipeParser: ...
    def resolve(self, name: str, interface: Interface) -> Pipeline:  # noqa: E301
        """
        Returns ``name``'s callable for ``interface`` and honors tier precedence.

        Raises:
            UnsupportedModuleError: If no tier defines ``name``, or the tier that
                does has no ``interface`` callable.

        """
        definition = self._runtime.get(name) or self._entry_point_definition(name)

        if definition is None:
            pipe = self._resolve_builtin(name, interface)
        elif (pipe := definition.get_pipe(interface)) is None:
            raise UnsupportedModuleError(f"{name!r} has no {interface!r}")

        return pipe

    def registered_names(self) -> tuple[str, ...]:
        """Returns the sorted runtime-registered names."""
        return tuple(sorted(self._runtime))

    def catalog_names(self) -> tuple[str, ...]:
        """
        Returns the sorted registered and entry-point names.

        Built-ins are excluded since the pkgutil catalog enumerates those separately.

        """
        return tuple(sorted({*self._runtime, *self._discover_entry_points()}))

    def definition(self, name: str) -> ModuleDefinition | None:
        """Returns ``name``'s definition, or ``None`` for a built-in or unknown."""
        return self._runtime.get(name) or self._entry_point_definition(name)

    def reset(self) -> None:
        """Drops runtime registrations and the entry-point discovery cache."""
        self._runtime.clear()
        self._loaded.clear()
        self._entry_points = None


registry: ModuleRegistry = ModuleRegistry()


def register(definition: ModuleDefinition, *, replace: bool = False) -> None:
    """
    Registers a module on the process-global registry.

    Raises:
        ValueError: If ``definition`` has no name, or names an already registered
            module and ``replace`` is False.

    """
    registry.register(definition, replace=replace)


def reset_registry() -> None:
    """Resets the process-global registry, chiefly for test isolation."""
    registry.reset()
