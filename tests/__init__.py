# vim: sw=4:ts=4:expandtab
"""
tests
~~~~~

Provides application unit tests
"""

from collections.abc import AsyncIterable
from typing import Protocol, overload

from riko.bado import run
from riko.collections import AsyncPipe, SyncPipe


def aresolve[T](aiterable: AsyncIterable[T]) -> list[T]:
    """Drain *aiterable* to a list via ``riko.bado.run`` (one event loop)."""

    async def _collect() -> list[T]:
        return [item async for item in aiterable]

    return run(_collect)


class PipeBuilder(Protocol):
    @overload
    def __call__(self, pipe: type[SyncPipe]) -> SyncPipe: ...  # noqa: E704
    @overload
    def __call__(self, pipe: type[AsyncPipe]) -> AsyncPipe: ...  # noqa: E704
