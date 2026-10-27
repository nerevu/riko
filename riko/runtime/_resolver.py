# vim: sw=4:ts=4:expandtab
"""
Provides pipe resolution for modules and stored workflows.

Names prefixed with ``pipe_`` or ``pipe:`` resolve as stored workflows
(``WorkflowStore`` entries looked up by their ``pipe_<id>`` name) through
``WorkflowResolver``. Everything else resolves as a module, such as ``fetch``, through
``ModuleRegistry``.

Attributes:

    dispatcher: Finds each node's pipe by name, whether a module such as ``fetch``
        or a stored workflow's ``pipe_<id>``.

"""

from __future__ import annotations

from typing import TYPE_CHECKING, Literal, overload

from riko.base._exceptions import UnsupportedModuleError, UnsupportedWorkflowError

from ._module_registry import module_registry
from ._workflow_resolver import WorkflowResolver, workflow_resolver

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
    Dispatches a module name or ``pipe_<id>`` name to the first resolver accepting it.

    ``WorkflowResolver`` accepts names prefixed with ``pipe_`` or ``pipe:``.
    ``ModuleRegistry`` accepts every other name, such as ``fetch``.

    Examples:

        >>> count = dispatcher.resolve("count")
        >>> list(count([{"x": 1}, {"x": 2}]))
        [{'count': 2}]

    """

    def __init__(self, *resolvers: Resolver) -> None:
        self.resolvers = resolvers

    def require_resolver(self, name: str) -> Resolver:
        """
        Selects the first resolver that accepts ``name``.

        Returns:

            The first resolver whose ``is_compatible`` accepts ``name``.

        Raises:

            UnsupportedModuleError: If no resolver accepts ``name``.

        """
        resolver = next((r for r in self.resolvers if r.is_compatible(name)), None)

        if resolver is None:
            raise UnsupportedModuleError(name, "no resolver accepts it")

        return resolver

    @overload
    def require(
        self, name: str, is_async: Literal[False] = ...
    ) -> SyncModuleWrapper: ...
    @overload
    def require(self, name: str, is_async: Literal[True]) -> AsyncModuleWrapper: ...
    def require(self, name: str, is_async: bool = False) -> ModuleWrapper:
        """
        Requires the ``pipe`` ``name`` names, or its ``async_pipe`` when ``is_async``.

        Raises:

            UnsupportedModuleError: If no module has that name, or the module lacks
                ``pipe`` (or ``async_pipe`` when ``is_async``).

            UnsupportedWorkflowError: If no stored workflow has that ``pipe_<id>`` name,
                or its ``ResolvedWorkflow`` lacks ``pipe`` (or ``async_pipe`` when
                ``is_async``).

        """
        return self.require_resolver(name).require(name, is_async)

    def require_interfaces(self, name: str) -> frozenset[Interface]:
        """
        Reports which sync and async interfaces a module or stored workflow defines.

        Args:

            name: Module name or ``pipe_<id>`` name to inspect.

        Returns:

            The subset of ``pipe``/``async_pipe`` the name exposes.

        Examples:

            >>> "pipe" in dispatcher.require_interfaces("count")
            True

        """
        return self.require_resolver(name).require_interfaces(name)

    def validate(self, name: str) -> None:
        """
        Validates that ``name`` exposes ``pipe`` and/or ``async_pipe``.

        Args:

            name: Module name or ``pipe_<id>`` name to check.

        Raises:

            UnsupportedModuleError: If no module has that name, or the module exposes
                neither interface.

            UnsupportedWorkflowError: If no stored workflow has that ``pipe_<id>``
                name, or its ``ResolvedWorkflow`` exposes neither interface.

        Examples:

            >>> dispatcher.validate("count")

        """
        resolver = self.require_resolver(name)

        if not resolver.require_interfaces(name):
            is_workflow = isinstance(resolver, WorkflowResolver)
            error = UnsupportedWorkflowError if is_workflow else UnsupportedModuleError
            raise error(name, "it has no interfaces")

    def is_capable(self, name: str, is_async: bool = False) -> bool:
        """
        Reports whether ``name`` exposes ``pipe``, or ``async_pipe`` when ``is_async``.

        Args:

            name: Module name or ``pipe_<id>`` name to inspect.
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
        return interface in self.require_resolver(name).require_interfaces(name)

    @overload
    def resolve(
        self, name: str, is_async: Literal[False] = ...
    ) -> SyncModuleWrapper | None: ...
    @overload
    def resolve(
        self, name: str, is_async: Literal[True]
    ) -> AsyncModuleWrapper | None: ...
    def resolve(self, name: str, is_async: bool = False) -> ModuleWrapper | None:
        """
        Resolves ``name`` to its ``pipe`` (or ``async_pipe`` when ``is_async``).

        Args:

            name: Module name or ``pipe_<id>`` name to inspect.
            is_async: Whether to check the async interface.

        Returns:

            The resolved ``pipe``/``async_pipe``, or ``None`` when ``name`` doesn't
            expose it.

        """
        capable = self.is_capable(name, is_async=is_async)
        return self.require(name, is_async=is_async) if capable else None


dispatcher: ResolverDispatcher = ResolverDispatcher(module_registry, workflow_resolver)
workflow_resolver.register_dispatcher(dispatcher)
