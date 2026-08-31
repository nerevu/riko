# vim: sw=4:ts=4:expandtab
"""
riko.ext._resolver
~~~~~~~~~~~~~~~~~~

Provides pipe resolution for modules and named pipelines.

Names prefixed with ``pipe_`` or ``pipe:`` resolve as pipelines, everything
else as a module.

Examples:
    Basic usage::

        >>> from riko.ext._resolver import pipe_resolver
        >>>
        >>> pipe = pipe_resolver.resolve("count", "pipe")
        >>> list(pipe([{"x": 1}, {"x": 2}]))
        [{'count': 2}]

Attributes:
    pipe_resolver: Process-global façade over the two default resolvers.

"""

from typing import Literal, overload

from riko.ext._pipelines import pipeline_resolver
from riko.ext.registry import registry
from riko.types._wrappers import (
    AsyncPipeParser,
    Interface,
    Pipeline,
    Resolver,
    SyncPipeParser,
)


class PipeResolver:
    """
    Dispatches a pipe name to whichever of the two resolvers owns it.

    Both sides share a ``resolve(name, interface)`` shape. The dispatch is a single
    symmetric branch: :class:`ModuleRegistry` for leaf modules,
    :class:`PipelineResolver` for composed ``pipe_*`` sub-pipelines.

    Notes:
        Neither resolver imports the compiler at module scope. The two ``riko.compile``
        imports on this path are deliberately function-local (marked
        ``noqa: PLC0415``). That is what keeps importing this module, and therefore
        ``riko.collections``, from pulling in ``riko.compile``. Hoisting them to
        the top would reintroduce that cycle, and no test guards it.

    """

    def __init__(self, registry: Resolver, pipelines: Resolver) -> None:
        self._registry = registry
        self._pipelines = pipelines

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
        Returns ``name``'s callable for ``interface``.

        Raises:
            UnsupportedModuleError: If a module name is unresolved.
            UnsupportedPipelineError: If a ``pipe_*`` name is unresolved.

        """
        is_pipeline = name.startswith(("pipe_", "pipe:"))
        resolver: Resolver = self._pipelines if is_pipeline else self._registry
        return resolver.resolve(name, interface)


pipe_resolver: PipeResolver = PipeResolver(registry, pipeline_resolver)
