"""
File-like and opener typing contracts for riko's sync and async I/O.

A file-like value is an in-memory buffer, a raw or text stream, a spooled temporary
file, or a fetched response that reads as bytes (``BinaryFileLike``) or text
(``StringFileLike``). A ``BinaryIOLike`` is any byte stream exposing the ``io`` reader
surface. A streamed parser can read it and ask whether it seeks. An opener maps a URL to
a file-like value and its detected encoding.
"""

from __future__ import annotations

from codecs import StreamReader
from collections.abc import Callable
from io import BufferedIOBase, BytesIO, RawIOBase, StringIO, TextIOBase
from tempfile import SpooledTemporaryFile
from typing import TYPE_CHECKING, Literal, Protocol

from typing_extensions import TypeIs

if TYPE_CHECKING:
    from urllib.response import addinfourl

    from urllib3.response import HTTPResponse as URLLib3Response

    from riko.types._scalars import AnyStr

    from ._async import NamedTextIOWrapper
    from ._sync import Fetch

type IOFileLike = BufferedIOBase | TextIOBase

type BinaryFileLike = (
    BytesIO
    | RawIOBase
    | Fetch[Literal[True]]
    | SpooledTemporaryFile[bytes]
    | addinfourl
    | URLLib3Response
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

_READER_METHODS = ("read", "seek", "seekable", "tell")


class Readable(Protocol):
    """A stream that can be read."""

    def read(self, size: int = ..., /) -> AnyStr | None: ...


class IOLike(Readable, Protocol):
    """A stream exposing the ``io`` reader surface: read, seek, tell, seekable."""

    def seekable(self) -> bool: ...
    def tell(self) -> int: ...
    def seek(self, offset: int, whence: int = ..., /) -> int: ...


class BinaryIOLike(Protocol):
    """A byte stream exposing the ``io`` reader surface: read, seek, tell, seekable."""

    def read(self, size: int = ..., /) -> bytes | None: ...
    def seekable(self) -> bool: ...
    def tell(self) -> int: ...
    def seek(self, offset: int, whence: int = ..., /) -> int: ...


def is_readable(val: object) -> TypeIs[Readable]:
    """Reports whether ``val`` has a callable ``read``."""
    return callable(getattr(val, "read", None))


def is_io_like(val: object) -> TypeIs[IOLike]:
    """Reports whether ``val`` exposes the ``io`` reader surface, text or bytes."""
    return all(callable(getattr(val, name, None)) for name in _READER_METHODS)


def is_binary_io_like(val: object) -> TypeIs[BinaryIOLike]:
    """
    Reports whether ``val`` is a byte stream exposing the ``io`` reader surface.

    Exposing ``seekable`` is not seeking: a forward-only HTTP body passes, and its
    ``seekable()`` then answers False. A text stream with the same methods does not
    count. A wrapper that delegates them, such as ``urllib.response.addinfourl``, does.

    Examples:

        >>> from io import BytesIO, StringIO
        >>>
        >>> is_binary_io_like(BytesIO(b"{}")), is_binary_io_like(StringIO("{}"))
        (True, False)

    """
    methods = (getattr(val, name, None) for name in _READER_METHODS)
    is_text = isinstance(val, (TextIOBase, StreamReader))
    return all(map(callable, methods)) and not is_text
