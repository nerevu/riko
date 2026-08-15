# vim: sw=4:ts=4:expandtab
"""
riko.ext.resolver
~~~~~~~~~~~~~~~~~~
The single pipe-resolution façade — one symmetric dispatch over two resolvers
that share a ``resolve(name, interface)`` shape: the :class:`ModuleRegistry` for
leaf modules, the :class:`PipelineResolver` for composed ``pipe`` sub-pipelines.
Neither imports the compiler, so importing this module (and therefore
``riko.collections``) never pulls in ``riko.compile``.
"""

from typing import Literal, overload

from riko.ext.pipelines import pipeline_resolver
from riko.ext.registry import registry
from riko.types.general import (
    AsyncPipeParser,
    Interface,
    Pipeline,
    Resolver,
    SyncPipeParser,
)


class PipeResolver:
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
        is_pipeline = name.startswith(("pipe_", "pipe:"))
        resolver: Resolver = self._pipelines if is_pipeline else self._registry
        return resolver.resolve(name, interface)


pipe_resolver: PipeResolver = PipeResolver(registry, pipeline_resolver)
