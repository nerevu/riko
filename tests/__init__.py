# vim: sw=4:ts=4:expandtab
"""
tests
~~~~~

Provides application unit tests
"""

from collections.abc import AsyncIterable
from pathlib import Path
from typing import Protocol, overload

import pytest

from riko.bado._backend import issync, run
from riko.collections import AsyncPipe, SyncPipe

TESTS_DIR = Path(__file__).parent.absolute()

skipif_issync = pytest.mark.skipif(issync, reason="async support not available")


def async_test(f):
    """Shortcut to apply multiple pytest markers at once."""
    f = pytest.mark.anyio(f)
    f = skipif_issync(f)
    return f


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
