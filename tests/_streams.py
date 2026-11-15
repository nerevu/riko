# vim: sw=4:ts=4:expandtab
"""Provides shared stream stand-ins for close and cleanup tests."""

from __future__ import annotations


class Closeable:
    """Stands in for a stream or file, recording each close and raising ``error``."""

    def __init__(self, name: str, closes: list[str], error: Exception | None = None):
        self.name, self.closes, self.error = name, closes, error

    def __iter__(self) -> Closeable:
        return self

    def __next__(self) -> int:
        raise self.error or StopIteration

    def __aiter__(self) -> Closeable:
        return self

    async def __anext__(self) -> int:
        raise self.error or StopAsyncIteration

    def close(self) -> None:
        self.closes.append(self.name)
