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
registrations. Precedence: runtime registration → (entry points, later) →
built-in.
"""

from dataclasses import dataclass
from importlib import import_module
from typing import Literal, overload

from riko.exceptions import UnsupportedModuleError
from riko.types.general import AsyncPipeParser, Pipeline, SyncPipeParser

type Interface = Literal["pipe", "async_pipe"]


@dataclass(frozen=True, slots=True)
class ModuleDefinition:
    """
    A named module and its interface callables, plus discovery metadata.

    ``sync_pipe``/``async_pipe`` are the resolved ``pipe``/``async_pipe`` callables. The
    discovery fields (``provider``/``enum_name``/``user_type``/``docs_url``) are
    read by the P9A codegen; ``name`` is always the canonical identifier.
    """

    name: str
    sync_pipe: SyncPipeParser | None = None
    async_pipe: AsyncPipeParser | None = None
    provider: str = "riko"
    enum_name: str | None = None
    user_type: str | None = None
    docs_url: str | None = None
    description: str | None = None


class ModuleRegistry:
    def __init__(self) -> None:
        self._runtime: dict[str, ModuleDefinition] = {}

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
        definition = self._runtime.get(name)

        if definition is None:
            resolved = self._resolve_builtin(name, interface)
        else:
            resolved = (
                definition.sync_pipe if interface == "pipe" else definition.async_pipe
            )

            if resolved is None:
                raise UnsupportedModuleError(f"{name!r} has no {interface!r}")

        return resolved

    def registered_names(self) -> tuple[str, ...]:
        return tuple(sorted(self._runtime))

    def reset(self) -> None:
        self._runtime.clear()


registry: ModuleRegistry = ModuleRegistry()


def register(definition: ModuleDefinition, *, replace: bool = False) -> None:
    registry.register(definition, replace=replace)


def reset_registry() -> None:
    registry.reset()
