# vim: sw=4:ts=4:expandtab
"""
Provides pipe resolution for modules and named pipelines.

Names prefixed with ``pipe_`` or ``pipe:`` resolve as pipelines, everything else as a
module.

Attributes:

    dispatcher: Process-global façade over the two default resolvers.

"""

from __future__ import annotations

from typing import TYPE_CHECKING, Literal, overload

from riko.base.exceptions import UnsupportedModuleError

from ._module_registry import module_registry
from ._pipelines import pipeline_resolver

if TYPE_CHECKING:
    from riko.types._wrappers import (
        AsyncModuleWrapper,
        Interface,
        ModuleWrapper,
        Resolver,
        SyncModuleWrapper,
    )


class ResolverDispatcher:
    """
    Dispatches a pipe name to the first compatible resolver.

    Examples:

        >>> pipe = dispatcher.resolve("count")
        >>> list(pipe([{"x": 1}, {"x": 2}]))
        [{'count': 2}]

    """

    def __init__(self, *resolvers: Resolver) -> None:
        self.resolvers = resolvers

    def resolver_for(self, name: str) -> Resolver:
        """
        Selects the first compatible resolver for ``name``.

        Returns:

            The first registered resolver whose ``is_compatible`` accepts ``name``.

        Raises:

            UnsupportedModuleError: If a module or ``pipe_*`` name is unresolved.

        """
        resolver = next((r for r in self.resolvers if r.is_compatible(name)), None)

        if resolver is None:
            raise UnsupportedModuleError(f"{name} is not compatible with any resolver")

        return resolver

    @overload
    def require(  # noqa: E704
        self, name: str, is_async: Literal[False] = ...
    ) -> SyncModuleWrapper: ...
    @overload  # noqa: E301
    def require(  # noqa: E704
        self, name: str, is_async: Literal[True]
    ) -> AsyncModuleWrapper: ...
    def require(self, name: str, is_async: bool = False) -> ModuleWrapper:  # noqa: E301
        """
        Resolves ``name``'s callable for ``interface``.

        Raises:

            UnsupportedModuleError: If a module name is unresolved.
            UnsupportedPipelineError: If a ``pipe_*`` name is unresolved.

        """
        return self.resolver_for(name).require(name, is_async)

    def require_interfaces(self, name: str) -> frozenset[Interface]:
        """
        Reports which of a pipe name's sync and async interfaces are defined.

        Args:

            name: Module or ``pipe_*`` pipeline name to inspect.

        Returns:

            The subset of ``pipe``/``async_pipe`` the name exposes.

        Examples:

            >>> "pipe" in dispatcher.require_interfaces("count")
            True

        """
        return self.resolver_for(name).require_interfaces(name)

    def validate(self, name: str) -> None:
        if not self.require_interfaces(name):
            raise UnsupportedModuleError(f"{name!r} has no interfaces")

    def is_capable(self, name: str, is_async: bool = False) -> bool:
        """
        Reports whether ``name`` exposes ``interface``.

        Args:

            name: Module or ``pipe_*`` pipeline name to inspect.
            is_async: Whether to check the async interface.

        Returns:

            Whether the name exposes the interface.

        Examples:

            >>> dispatcher.is_capable("count")
            True
            >>> dispatcher.is_capable("count", is_async=True)
            True

        """
        interface = "async_pipe" if is_async else "pipe"
        return interface in self.resolver_for(name).require_interfaces(name)

    @overload
    def resolve(  # noqa: E704
        self, name: str, is_async: Literal[False] = ...
    ) -> SyncModuleWrapper | None: ...
    @overload  # noqa: E301
    def resolve(  # noqa: E704
        self, name: str, is_async: Literal[True]
    ) -> AsyncModuleWrapper | None: ...
    def resolve(  # noqa: E301
        self, name: str, is_async: bool = False
    ) -> ModuleWrapper | None:
        """
        Resolves ``name`` if it exposes ``interface``, else returns ``None``.

        Args:

            name: Module or ``pipe_*`` pipeline name to inspect.
            is_async: Whether to check the async interface.

        """
        if self.is_capable(name, is_async=is_async):
            return self.require(name, is_async=is_async)


dispatcher: ResolverDispatcher = ResolverDispatcher(module_registry, pipeline_resolver)
