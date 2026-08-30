# vim: sw=4:ts=4:expandtab
"""
riko.bado.io
~~~~~~~~~~~~

Async file and URL reading and writing for riko pipes (anyio + httpx).

Examples:
    Basic usage::

        >>> from riko import get_path, issync, run
        >>> from riko.bado.io import async_url_open
        >>>
        >>> async def main():
        ...     async with async_url_open(get_path("spreadsheet.csv")) as f:
        ...         print(f.readline())
        >>>
        >>> print("Member,Name,") if issync else run(main)
        Member,Name,...

"""

from __future__ import annotations

from collections.abc import Awaitable, Callable, Generator, Iterator
from io import BytesIO, StringIO, TextIOWrapper
from logging import Logger
from pathlib import Path
from typing import TYPE_CHECKING, Any, Literal, cast, overload

import pygogo as gogo
from meza.fntools import chunk as _chunk
from typing_extensions import TypeIs

from riko._constants import ENCODING
from riko._io import ext_from_content_type
from riko.paths import get_abspath

from . import _backend
from ._backend import open_file
from ._util import async_get, async_read

if TYPE_CHECKING:
    from _typeshed import OpenBinaryMode, OpenTextMode

    from ._backend import NamedTemporaryFile

logger: Logger = gogo.Gogo(__name__, monolog=True).logger

type TextChunk = str | list[str]
type BinaryChunk = bytes | list[int]
type Chunk = TextChunk | BinaryChunk


_MODE_KINDS = frozenset("rwxa")
_MODE_DUPLEX = frozenset("bt")
_MODE_CHARS = _MODE_KINDS | _MODE_DUPLEX | {"+"}


def _is_open_mode(mode: str) -> TypeIs[OpenBinaryMode | OpenTextMode]:
    """Validates at runtime whether a string is a well-formed open-file mode."""
    return (
        _MODE_CHARS.issuperset(mode)
        and len(mode) == len(_MODE_CHARS.intersection(mode))
        and len(_MODE_KINDS.intersection(mode)) == 1
        and not _MODE_DUPLEX.issubset(mode)
    )


@overload
def chunk(  # noqa: E704
    content: str, chunksize: int | None = None, *args: int, **kwargs: int
) -> Iterator[list[str]]: ...
@overload  # noqa: E302
def chunk(  # noqa: E704
    content: StringIO, chunksize: int | None = None, *args: int, **kwargs: int
) -> Iterator[str]: ...
@overload  # noqa: E302
def chunk(  # noqa: E704
    content: bytes, chunksize: int | None = None, *args: int, **kwargs: int
) -> Iterator[list[int]]: ...
@overload  # noqa: E302
def chunk(  # noqa: E704
    content: BytesIO, chunksize: int | None = None, *args: int, **kwargs: int
) -> Iterator[bytes]: ...
def chunk(  # noqa: E302
    content: str | bytes | BytesIO | StringIO,
    chunksize: int | None = None,
    *args: int,
    **kwargs: int,
) -> Iterator[Chunk]:
    """
    Splits content into chunks by delegating to :func:`meza.fntools.chunk`.

    A typed wrapper that narrows meza's untyped return for the write path.
    A ``chunksize`` of ``None`` yields the whole content as one chunk.

    Args:
        content: The source data to split.
        chunksize: The number of units per chunk, or ``None`` for a single chunk.
        *args: Extra positional arguments forwarded to meza.
        **kwargs: Extra keyword arguments forwarded to meza.

    Yields:
        Each chunk; a bare ``str``/``bytes`` for a file-like source (read via
        ``.read``), or a ``list`` of characters or ints for a ``str``/``bytes``
        source.

    Examples:
        >>> list(chunk("abcdef", 3))
        [['a', 'b', 'c'], ['d', 'e', 'f']]
        >>> list(chunk(b"abcdef", 3))
        [[97, 98, 99], [100, 101, 102]]

    """
    result = _chunk(content, chunksize, *args, **kwargs)
    return cast(Iterator[Chunk], result)


@overload
def _chunk_content(  # noqa: E704
    content: str | StringIO, chunksize: int | None = None
) -> Iterator[str]: ...
@overload  # noqa: E302
def _chunk_content(  # noqa: E704
    content: bytes | BytesIO, chunksize: int | None = None
) -> Iterator[bytes]: ...
def _chunk_content(  # noqa: E302
    content: str | bytes | BytesIO | StringIO, chunksize: int | None = None
) -> Iterator[str | bytes]:
    """
    Splits content into whole ``str`` or ``bytes`` chunks for the write path.

    Dispatches on the ``content`` type. :func:`chunk` yields a ``list`` of characters
    or ints for a ``str``/``bytes`` source, but a bare ``str``/``bytes`` for a file-like
    one. Joins the former into a scalar and passes the latter through. The caller always
    receives a whole ``str``/``bytes`` per chunk.

    Args:
        content: The source data to split.
        chunksize: The number of units per chunk, or ``None`` for a single chunk.

    Yields:
        Each chunk as a ``str`` for a text source or ``bytes`` for a binary one.

    Examples:
        >>> list(_chunk_content("abcdef", 3))
        ['abc', 'def']
        >>> list(_chunk_content(b"abcdef", 3))
        [b'abc', b'def']

    """
    if isinstance(content, str):
        for raw in chunk(content, chunksize):
            yield "".join(raw)
    elif isinstance(content, StringIO):
        yield from chunk(content, chunksize)
    elif isinstance(content, bytes):
        for raw in chunk(content, chunksize):
            yield bytes(raw)
    else:
        yield from chunk(content, chunksize)


def _coerce_chunk(raw: str | bytes, binary: bool, encoding: str) -> str | bytes:
    if isinstance(raw, str):
        result: str | bytes = raw.encode(encoding) if binary else raw
    else:
        result = raw if binary else raw.decode(encoding)

    return result


class NamedTextIOWrapper(TextIOWrapper):
    """
    A text stream that carries a settable filename and content type.

    Wraps an in-memory buffer so a URL read presents like an opened file:
    ``name`` is assignable (the base ``TextIOWrapper.name`` is read-only) and
    ``ext`` is derived from the recorded ``content_type``.
    """

    _name: str = ""
    content_type: str | None = None

    @property
    def name(self) -> str:  # type: ignore[override]
        """The stream's filename or source URL."""
        return self._name

    @name.setter
    def name(self, value: str) -> None:
        self._name = value

    @property
    def ext(self) -> str | None:
        """The file extension inferred from ``content_type``, if any."""
        return ext_from_content_type(self.content_type)


async def _read_bytes(url: str, timeout: float) -> tuple[bytes, str, str | None]:
    """
    Reads a resource as raw bytes over HTTP or from the local filesystem.

    Args:
        url: An ``http(s)`` URL or a local path, optionally ``file://``-prefixed.
        timeout: The HTTP request timeout in seconds (ignored for local reads).

    Returns:
        The content bytes, a name (the URL for HTTP, the ``file://``-stripped
        path locally), and the content type (populated only for HTTP).

    """
    if url.startswith("http"):
        response = await async_get(url, timeout=timeout)
        content_type = response.headers.get("content-type")
        result = (response.content, url, content_type)
    else:
        response = await async_read(url, binary=True)
        result = (response, url.replace("file://", ""), None)

    return result


class _AsyncURLStream[T]:
    """
    An awaitable, async-context-manager handle over a lazily opened buffer.

    ``await``-ing it returns the opened buffer (the caller then owns closing
    it), while ``async with`` yields the buffer and closes it on exit. Both
    paths open a fresh buffer, so the handle is reusable.
    """

    def __init__(self, opener: Callable[[], Awaitable[T]]) -> None:
        self._open = opener
        self._stream: BytesIO | NamedTextIOWrapper | None = None

    def __await__(self) -> Generator[Any, None, T]:
        return self._open().__await__()

    async def __aenter__(self) -> T:
        opened = await self._open()
        self._stream = cast("BytesIO | NamedTextIOWrapper", opened)
        return opened

    async def __aexit__(self, *_: object) -> bool:
        if self._stream is not None:
            self._stream.close()

        return False


@overload
def async_url_open(  # noqa: E704
    url: str,
    timeout: float = ...,
    encoding: str = ...,
    *,
    binary: Literal[True],
    **_: object,
) -> _AsyncURLStream[BytesIO]: ...
@overload  # noqa: E302
def async_url_open(  # noqa: E704
    url: str,
    timeout: float = ...,
    encoding: str = ...,
    binary: Literal[False] = ...,
    **_: object,
) -> _AsyncURLStream[NamedTextIOWrapper]: ...
def async_url_open(  # noqa: E302
    url: str,
    timeout: float = 0,
    encoding: str = ENCODING,
    binary: bool = False,
    **_: object,
) -> _AsyncURLStream[BytesIO | NamedTextIOWrapper]:
    """
    Opens a URL or local file as an in-memory, buffered file object.

    The whole body is read into memory up front, in a single ``await``. The
    returned handle wraps a *buffered* copy, not an incremental network read, so
    there is no read-time backpressure. Only downstream parsing stays lazy.

    The handle may be ``await``-ed for the buffer (the caller then closes it) or
    used with ``async with`` to auto-close it on exit. Use ``async with`` only when
    the buffer is consumed inside the block. When returning a lazy iterator that
    outlives the block, keep the ``await`` form and release the handle on iteration
    end with :func:`riko._io.auto_close` (an ``async with``would close it before the
    caller ever reads it).

    Args:
        url: An ``http(s)`` URL or a local path.
        timeout: The HTTP request timeout in seconds; ``0`` means no timeout.
        encoding: The text decoding used when ``binary`` is False.
        binary: Whether to return raw bytes rather than decoded text.

    Returns:
        A handle whose buffer is a ``BytesIO`` when ``binary`` is True, else a
        ``NamedTextIOWrapper`` carrying the source name and content type.

    Examples:
        >>> from riko import get_path, issync, run
        >>>
        >>> url = get_path("spreadsheet.csv")
        >>>
        >>> async def main():
        ...     async with async_url_open(url) as f:
        ...         print(f.readline())
        >>>
        >>> print("Member,Name,") if issync else run(main)
        Member,Name,...

    """

    async def opener() -> BytesIO | NamedTextIOWrapper:
        data, name, content_type = await _read_bytes(url, timeout)

        if binary:
            f: BytesIO | NamedTextIOWrapper = BytesIO(data)
        else:
            f = NamedTextIOWrapper(BytesIO(data), encoding=encoding)
            f.name = name
            f.content_type = content_type

        return f

    return _AsyncURLStream(opener)


async def async_url_read(
    url: str, timeout: float = 0, encoding: str = ENCODING, **_: object
) -> str:
    """
    Reads a URL or local file in full.

    Args:
        url: An ``http(s)`` URL or a local path; resolved to an absolute path.
        timeout: The HTTP request timeout in seconds; ``0`` means no timeout.
        encoding: The text decoding used for local reads.

    Returns:
        The full resource contents as text.

    Examples:
        >>> from riko import get_path, issync, run
        >>>
        >>> async def main():
        ...     content = await async_url_read(get_path("spreadsheet.csv"))
        ...     print(content[:6])
        >>>
        >>> print("Member") if issync else run(main)
        Member

    """
    url = get_abspath(url, offline=True)

    if url.startswith("http"):
        response = await async_get(url, timeout=timeout)
        content = response.text
    else:
        content = await async_read(url, encoding=encoding)

    return content


async def async_write(
    filepath: str | Path,
    content: str | bytes | BytesIO | StringIO,
    mode: str = "wb+",
    encoding: str = ENCODING,
    chunksize: int | None = None,
    **_: object,
) -> int:
    """
    Writes content to a file using anyio's async file I/O.

    Accepts a file-like object, iterable, ``str`` or ``bytes``, which mirrors
    :func:`meza.io.write` chunking, mode, and encoding semantics.

    Args:
        filepath: The destination path.
        content: The data to write.
        mode: The file mode; a ``"b"`` in it selects binary I/O.
        encoding: The text encoding used when ``mode`` is not binary.
        chunksize: The units written per chunk, or ``None`` for a single chunk.

    Returns:
        The number of units (bytes or characters) written.

    Examples:
        >>> from io import StringIO
        >>> from riko import get_temp_file, issync, run
        >>>
        >>> async def main():
        ...     with get_temp_file() as fp:
        ...         await async_write(fp.name, StringIO("Hello World"))
        ...
        ...         with open(fp.name, mode="rb") as f:
        ...             print(f.read())
        >>>
        >>> print(b"Hello World") if issync else run(main)
        b'Hello World'

    """
    if not _is_open_mode(mode):
        raise ValueError(f"the file mode {mode!r} is invalid")

    progress = 0
    binary = "b" in mode
    open_encoding = None if binary else encoding
    opener = open_file(filepath, mode, encoding=open_encoding)

    async with await opener as f:
        for normalized in _chunk_content(content, chunksize):
            data = _coerce_chunk(normalized, binary, encoding)
            await f.write(data)  # pyright: ignore[reportArgumentType]
            progress += len(data)

    written = progress
    return written


def get_async_temp_file() -> NamedTemporaryFile[bytes]:
    """
    Creates an auto-deleting named temporary file for async use.

    A plain ``def`` (not a coroutine) returning anyio's async context manager.
    ``async with`` needs no ``await`` on the call itself.

    Returns:
        An anyio ``NamedTemporaryFile`` context manager over a binary temp file
        that is removed when the context exits.

    Examples:
        >>> from riko import issync, run
        >>>
        >>> async def main():
        ...     async with get_async_temp_file() as f:
        ...         await f.write(b"hi")
        ...         print(f.name is not None)
        >>>
        >>> print(True) if issync else run(main)
        True

    """
    return _backend.NamedTemporaryFile(delete=True, delete_on_close=False)
