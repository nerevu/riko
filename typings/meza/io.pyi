from codecs import StreamReader
from collections.abc import Callable, Iterable, Iterator
from io import TextIOBase
from typing import Protocol, Self

from _typeshed import StrOrBytesPath

class _Readable(Protocol):
    def read(self, size: int = ..., /) -> object: ...

class _LineSource(Protocol):
    def __next__(self) -> str | bytes: ...
    def __iter__(self) -> Iterator[str | bytes]: ...
    def fileno(self) -> int: ...

type _FilePath = StrOrBytesPath | _Readable
type _Content = _Readable | Callable[..., Iterable[object]] | Iterable[object]

class IterStringIO(TextIOBase):
    iter: Iterator[bytes]
    decode: bool
    bufsize: int
    pos: int
    def __init__(
        self,
        iterable: Iterable[str] | None = None,
        bufsize: int = 4096,
        decode: bool = False,
        **kwargs: object,
    ) -> None: ...
    def __next__(self) -> str | bytes: ...  # pyright: ignore[reportIncompatibleMethodOverride]
    def __iter__(self) -> Self: ...  # pyright: ignore[reportIncompatibleMethodOverride]
    @property
    def lines(self) -> Iterator[Iterator[bytes]]: ...
    def write(self, iterable: Iterable[str]) -> None: ...  # pyright: ignore[reportIncompatibleMethodOverride]
    def read(self, num: int | None = None) -> str | bytes: ...  # pyright: ignore[reportIncompatibleMethodOverride]
    def readline(self, num: int | None = None) -> str | bytes: ...  # pyright: ignore[reportIncompatibleMethodOverride]
    def readlines(self) -> Iterator[str | bytes]: ...  # pyright: ignore[reportIncompatibleMethodOverride]
    def seek(self, num: int) -> None: ...  # pyright: ignore[reportIncompatibleMethodOverride]
    def tell(self) -> int: ...

class Reencoder(StreamReader):
    binary: bool
    stream: Iterator[str | bytes]  # pyright: ignore[reportIncompatibleVariableOverride]
    def __init__(
        self,
        f: _LineSource,
        fromenc: str = ...,
        toenc: str = ...,
        *,
        remove_BOM: bool = ...,  # noqa: N803
        decode: bool = ...,
    ) -> None: ...
    def __next__(self) -> str | bytes: ...  # pyright: ignore[reportIncompatibleMethodOverride]
    def __iter__(self) -> Self: ...
    def read(self, n: int | None = None) -> str | bytes: ...  # pyright: ignore[reportIncompatibleMethodOverride]
    def readline(  # pyright: ignore[reportIncompatibleMethodOverride]
        self, n: int | None = None, keepends: bool = True
    ) -> str | bytes: ...
    def readlines(self, sizehint: int | None = None) -> list[str | bytes]: ...  # pyright: ignore[reportIncompatibleMethodOverride]
    def tell(self) -> None: ...
    def reset(self) -> None: ...

def read_csv(
    filepath: _FilePath, mode: str = "r", **kwargs: object
) -> Iterator[dict[str, str | None]]: ...
def read(
    filepath: _FilePath, ext: str | None = None, **kwargs: object
) -> Iterator[object]: ...
def write(
    filepath: _FilePath, content: _Content, mode: str = "wb+", **kwargs: object
) -> int: ...
