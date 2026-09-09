from __future__ import annotations

from codecs import StreamReader
from collections.abc import Callable
from io import BytesIO, RawIOBase, StringIO, TextIOBase
from tempfile import SpooledTemporaryFile
from typing import TYPE_CHECKING, Literal, Protocol, runtime_checkable

if TYPE_CHECKING:
    from riko._io import Fetch
    from riko.bado.io import NamedTextIOWrapper

type IOFileLike = BytesIO | StringIO
type BinaryFileLike = (
    BytesIO | RawIOBase | Fetch[Literal[True]] | SpooledTemporaryFile[bytes]
)
type StringFileLike = (
    Fetch[Literal[False]]
    | NamedTextIOWrapper
    | SpooledTemporaryFile[str]
    | StreamReader
    | StringIO
    | TextIOBase
)
type FileLike = BinaryFileLike | StringFileLike
type Opener = Callable[[str], tuple[FileLike, str | None]]


@runtime_checkable
class SyncCloseable(Protocol):
    def close(self) -> object | None: ...  # noqa: E704


@runtime_checkable
class AsyncCloseable(Protocol):
    async def aclose(self) -> object | None: ...  # noqa: E704


type Closeable = SyncCloseable | AsyncCloseable

IOFileLikeType: tuple[type[BytesIO], type[StringIO]] = (BytesIO, StringIO)
CloseableType = (SyncCloseable, AsyncCloseable)
