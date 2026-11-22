# vim: sw=4:ts=4:expandtab
"""Provides shared stream stand-ins for stream, close, and cleanup tests."""

from __future__ import annotations

from typing import TYPE_CHECKING

from riko.bado._backend import async_sleep

if TYPE_CHECKING:
    from collections.abc import AsyncGenerator, Iterable


async def gen_items[T](items: Iterable[T], delay: float = 0.0) -> AsyncGenerator[T]:
    """Yields each of ``items``, sleeping ``delay`` seconds before each when set."""
    for item in items:
        if delay:
            await async_sleep(delay)

        yield item


class Closable:
    """Stands in for a stream or file, recording each close and raising ``error``."""

    def __init__(self, name: str, closes: list[str], error: Exception | None = None):
        self.name, self.closes, self.error = name, closes, error

    def __iter__(self) -> Closable:
        return self

    def __next__(self) -> int:
        raise self.error or StopIteration

    def __aiter__(self) -> Closable:
        return self

    async def __anext__(self) -> int:
        raise self.error or StopAsyncIteration

    def close(self) -> None:
        self.closes.append(self.name)
