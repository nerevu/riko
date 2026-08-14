# vim: sw=4:ts=4:expandtab
"""
riko.ext.registry
~~~~~~~~~~~~~~~~~~
The module registry — resolves named *module implementations* (``fetch``,
``tokenizer``, extension modules) to their sync/async callables. It never loads
JSON or invokes the compiler; composed pipelines (``pipe_*``) are a separate
concern handled by the resolver façade.

Lifetime is hybrid: built-ins are immutable, process-global static facts
resolved lazily on first use (importing ``riko.modules.<name>`` on demand keeps
heavy optional deps off the startup path). Runtime ``register`` shadows live in a
mutable global tier with ``reset()`` for test isolation — the one part that may
later move onto ``Context.resources`` if concurrent pipelines need distinct
registrations. Precedence: runtime registration → entry point
(``[project.entry-points."riko.modules"]``) → built-in. Entry points are
discovered by name lazily (no extension import until a name is resolved).
"""

from dataclasses import dataclass
from dataclasses import replace as _replace
from importlib import import_module
from importlib.metadata import EntryPoint, entry_points
from typing import Literal, cast, overload

from riko.exceptions import UnsupportedModuleError
from riko.types.general import AsyncPipeParser, Pipeline, SyncPipeParser

type Interface = Literal["pipe", "async_pipe"]

ENTRY_POINT_GROUP = "riko.modules"


@dataclass(frozen=True, slots=True)
class ModuleDefinition:
    """
    A named module and its interface callables, plus discovery metadata.

    Point ``module`` at an object that exposes ``pipe`` / ``async_pipe`` by the
    same convention as a built-in (e.g. a ``riko.ext``-decorated extension
    module); the interface callables are read off it on demand. Or pass
    ``sync_pipe`` / ``async_pipe`` explicitly (handy for a bare callable). An
    explicit callable wins over the one derived from ``module``.

    ``name`` is the canonical identifier. It may be **omitted** when registering
    via an entry point — the registry stamps it from the entry-point key (the
    external declaration is then the single source of truth); a name given here
    that disagrees with the key is an error. Runtime ``register`` requires it.
    """

    name: str = ""
    sync_pipe: SyncPipeParser | None = None
    async_pipe: AsyncPipeParser | None = None
    module: object | None = None
    description: str | None = None

    def pipe_for(self, interface: Interface) -> Pipeline | None:
        explicit = self.sync_pipe if interface == "pipe" else self.async_pipe

        if explicit is None and self.module is not None:
            explicit = getattr(self.module, interface, None)

        return explicit


class ModuleRegistry:
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
        target = f"riko.modules.{name}"

        try:
            module = import_module(target)
        except ModuleNotFoundError as e:
            if e.name != target:
                raise

            raise UnsupportedModuleError(name) from e

        if (resolved := getattr(module, interface, None)) is None:
            raise UnsupportedModuleError(f"{name!r} has no {interface!r}")

        return resolved

    def register(self, definition: ModuleDefinition, *, replace: bool = False) -> None:
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
        definition = self._runtime.get(name) or self._entry_point_definition(name)

        if definition is None:
            resolved = self._resolve_builtin(name, interface)
        elif (resolved := definition.pipe_for(interface)) is None:
            raise UnsupportedModuleError(f"{name!r} has no {interface!r}")

        return resolved

    def registered_names(self) -> tuple[str, ...]:
        return tuple(sorted(self._runtime))

    def reset(self) -> None:
        self._runtime.clear()
        self._loaded.clear()
        self._entry_points = None


registry: ModuleRegistry = ModuleRegistry()


def register(definition: ModuleDefinition, *, replace: bool = False) -> None:
    registry.register(definition, replace=replace)


def reset_registry() -> None:
    registry.reset()
