# vim: sw=4:ts=4:expandtab
"""
Provides pipe resolution for modules and named pipelines.

Names prefixed with ``pipe_`` or ``pipe:`` resolve as pipelines, everything else as a
module.

Attributes:

    pipe_resolver: Process-global façade over the two default resolvers.

"""

from __future__ import annotations

from typing import TYPE_CHECKING, Literal, overload

from ._module_registry import module_registry
from ._pipelines import pipeline_resolver

if TYPE_CHECKING:
    from riko.types._wrappers import (
        AsyncPipeWrapper,
        Interface,
        Pipe,
        Resolver,
        SyncPipeWrapper,
    )


class PipeResolver:
    """
    Dispatches a pipe name to whichever of the two resolvers owns it.

    Both sides share the ``Resolver`` contract. The dispatch is a single symmetric
    branch: :class:`ModuleRegistry` for leaf modules, :class:`PipelineResolver` for
    composed ``pipe_*`` sub-pipelines.

    Examples:

        >>> pipe = pipe_resolver.resolve("count")
        >>> list(pipe([{"x": 1}, {"x": 2}]))
        [{'count': 2}]

    """

    def __init__(self, registry: Resolver, pipelines: Resolver) -> None:
        self._registry = registry
        self._pipelines = pipelines

    @overload
    def resolve(  # noqa: E704
        self, name: str, is_async: Literal[False] = ...
    ) -> SyncPipeWrapper: ...
    @overload  # noqa: E301
    def resolve(  # noqa: E704
        self, name: str, is_async: Literal[True]
    ) -> AsyncPipeWrapper: ...
    def resolve(self, name: str, is_async: bool = False) -> Pipe:  # noqa: E301
        """
        Resolves ``name``'s callable for ``interface``.

        Raises:

            UnsupportedModuleError: If a module name is unresolved.
            UnsupportedPipelineError: If a ``pipe_*`` name is unresolved.

        """
        is_pipe = name.startswith(("pipe_", "pipe:"))
        resolver = self._pipelines if is_pipe else self._registry
        return resolver.resolve(name, is_async)

    def get_interfaces(self, name: str) -> frozenset[Interface]:
        """
        Reports which of a pipe name's sync and async interfaces are defined.

        Args:

            name: Module or ``pipe_*`` pipeline name to inspect.

        Returns:

            The subset of ``pipe``/``async_pipe`` the name exposes.

        Examples:

            >>> "pipe" in pipe_resolver.get_interfaces("count")
            True

        """
        is_pipe = name.startswith(("pipe_", "pipe:"))
        resolver = self._pipelines if is_pipe else self._registry
        return resolver.get_interfaces(name)


pipe_resolver: PipeResolver = PipeResolver(module_registry, pipeline_resolver)
