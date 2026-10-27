from collections.abc import Callable, Iterable, Iterator, Mapping
from json import JSONEncoder
from typing import Protocol, overload

class _Reader[T](Protocol):
    def read(self, size: int = ..., /) -> T: ...

class CustomEncoder(JSONEncoder):
    def default(self, obj: object) -> object: ...  # pyright: ignore[reportIncompatibleMethodOverride]

def dfilter[V](
    content: Mapping[str, V],
    blacklist: Iterable[str] | None = None,
    inverse: bool = False,
) -> dict[str, V]: ...
@overload
def chunk[T](
    content: _Reader[T],
    chunksize: int | None = None,
    start: int = 0,
    stop: int | None = None,
) -> Iterator[T]: ...
@overload
def chunk[T](
    content: Callable[..., Iterable[T]],
    chunksize: int | None = None,
    start: int = 0,
    stop: int | None = None,
) -> Iterator[T | bytearray]: ...
@overload
def chunk[T](
    content: Iterable[T],
    chunksize: int | None = None,
    start: int = 0,
    stop: int | None = None,
) -> Iterator[list[T]]: ...
def remove_keys[V](
    record: Mapping[str, V], *args: str, whitelist: bool = False
) -> dict[str, V]: ...
