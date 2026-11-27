# vim: sw=4:ts=4:expandtab
"""Provides shared stream stand-ins for stream, close, and cleanup tests."""

from __future__ import annotations

from typing import TYPE_CHECKING, Self

from riko.bado._backend import async_sleep

if TYPE_CHECKING:
    from collections.abc import AsyncGenerator, Iterable, Iterator


async def gen_items[T](items: Iterable[T], delay: float = 0.0) -> AsyncGenerator[T]:
    """Yields each of ``items`` and sleeps ``delay`` seconds before each."""
    for item in items:
        if delay:
            await async_sleep(delay)

        yield item


class Closable:
    """Stands in for a stream or file that records each close and raises ``error``."""

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


class AcloseOnlyClosable(Closable):
    """Stands in for a stream or file whose only close is ``aclose``."""

    close = None  # pyright: ignore[reportAssignmentType] (drops the sync close)

    async def aclose(self) -> None:
        self.closes.append(self.name)


class BrokenClosable(Closable):
    """Stands in for a value whose close records itself, then fails."""

    def close(self) -> None:
        super().close()
        raise OSError(f"{self.name} close failed")


class _PullLog[T]:
    """The cursor and pull record that ``PullLog`` and ``AsyncPullLog`` share."""

    def __init__(self, items: Iterable[T]):
        self._items: Iterator[T] = iter(items)
        self._pulled: list[T] = []
        self._closes = 0

    @property
    def closes(self) -> int:
        """The number of times consumers have closed the log."""
        return self._closes

    @property
    def closed(self) -> bool:
        """Whether a consumer has closed the log."""
        return self._closes > 0

    @property
    def pulled(self) -> tuple[T, ...]:
        """The items consumers have pulled so far, in order."""
        return tuple(self._pulled)

    def _pull(self) -> T:
        if self.closed:
            raise StopIteration

        item = next(self._items)
        self._pulled.append(item)
        return item


class PullLog[T](_PullLog[T]):
    """A source that records each item a consumer pulls from it and its close."""

    def __iter__(self) -> Self:
        return self

    def __next__(self) -> T:
        return self._pull()

    def close(self) -> None:
        self._closes += 1


class AsyncPullLog[T](_PullLog[T]):
    """The async twin of ``PullLog``."""

    def __aiter__(self) -> Self:
        return self

    async def __anext__(self) -> T:
        try:
            item = self._pull()
        except StopIteration:
            raise StopAsyncIteration from None

        return item

    async def aclose(self) -> None:
        self._closes += 1
