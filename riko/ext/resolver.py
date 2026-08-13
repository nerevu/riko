# vim: sw=4:ts=4:expandtab
"""
riko.ext.resolver
~~~~~~~~~~~~~~~~~~
The single stage-resolution façade. Runtime stages resolve through here instead
of importing the compiler.

Precedence: runtime registration → (entry points, later) → built-in module →
named pipeline. Ordinary module names resolve via the :class:`ModuleRegistry`
with no compiler import; composed pipelines (``pipe_*``) are delegated to the
compiler **lazily** (imported only inside the ``pipe_*`` branch), so importing
this module (and therefore ``riko.collections``) never pulls in ``riko.compile``.
"""

from typing import Literal, overload

from riko.ext.registry import ModuleRegistry, registry
from riko.types.general import AsyncPipeParser, Pipeline, SyncPipeParser

type Interface = Literal["pipe", "async_pipe"]


class StageResolver:
    def __init__(self, module_registry: ModuleRegistry) -> None:
        self._registry = module_registry

    def _resolve_pipeline(self, name: str, interface: Interface) -> Pipeline:
        from riko.compile import resolve_module  # noqa: PLC0415

        return resolve_module(name, interface)

    @overload
    def resolve(  # noqa: E704
        self, name: str, interface: Literal["pipe"]
    ) -> SyncPipeParser: ...
    @overload  # noqa: E301
    def resolve(  # noqa: E704
        self, name: str, interface: Literal["async_pipe"]
    ) -> AsyncPipeParser: ...
    def resolve(self, name: str, interface: Interface) -> Pipeline:  # noqa: E301
        if name.startswith("pipe_"):
            resolved = self._resolve_pipeline(name, interface)
        else:
            resolved = self._registry.resolve(name, interface)

        return resolved


stage_resolver: StageResolver = StageResolver(registry)
