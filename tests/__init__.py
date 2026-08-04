# vim: sw=4:ts=4:expandtab
"""
tests
~~~~~

Provides application unit tests
"""

from typing import Protocol, overload

from riko.collections import AsyncPipe, SyncPipe


class PipeBuilder(Protocol):
    @overload
    def __call__(self, pipe: type[SyncPipe]) -> SyncPipe: ...  # noqa: E704
    @overload
    def __call__(self, pipe: type[AsyncPipe]) -> AsyncPipe: ...  # noqa: E704
