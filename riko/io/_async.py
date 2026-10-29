# vim: sw=4:ts=4:expandtab
"""
Asynchronous file and URL I/O helpers.

Examples:

    Basic usage::

        >>> from riko import async_url_open, get_path, run
        >>>
        >>> async def main():
        ...     async with async_url_open(get_path("spreadsheet.csv")) as f:
        ...         print(f.readline())
        >>>
        >>> run(main)
        Member,Name,...

"""

from __future__ import annotations

from io import BufferedIOBase, BytesIO, StringIO, TextIOBase, TextIOWrapper
from typing import TYPE_CHECKING, Literal, overload

from meza.fntools import chunk as _chunk
from typing_extensions import TypeIs

from riko.bado._backend import NamedTemporaryFile, async_open
from riko.bado._util import async_get, async_read
from riko.base._config import ENCODING
from riko.base._logging import get_logger
from riko.base._paths import is_http_url, normalize_url

from ._sync import ext_from_content_type

if TYPE_CHECKING:
    from collections.abc import Awaitable, Callable, Generator, Iterable, Iterator
    from logging import Logger

    from _typeshed import OpenBinaryMode, OpenTextMode

    from riko.types._io import PathLike
    from riko.types._scalars import AnyStr

    from ._filelike import IOFileLike

logger: Logger = get_logger(__name__)

type TextChunk = str | list[str]
type BinaryChunk = bytes | list[int]
type Chunk = TextChunk | BinaryChunk
type WriteContent = AnyStr | IOFileLike | Iterable[str] | Iterable[bytes]


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
def chunk(
    content: str, chunksize: int | None = None, *args: int, **kwargs: int
) -> Iterator[list[str]]: ...
@overload
def chunk(
    content: TextIOBase, chunksize: int | None = None, *args: int, **kwargs: int
) -> Iterator[str]: ...
@overload
def chunk(
    content: bytes, chunksize: int | None = None, *args: int, **kwargs: int
) -> Iterator[list[int]]: ...
@overload
def chunk(
    content: BufferedIOBase, chunksize: int | None = None, *args: int, **kwargs: int
) -> Iterator[bytes]: ...
def chunk(
    content: AnyStr | IOFileLike,
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
    return _chunk(content, chunksize, *args, **kwargs)


@overload
def _chunk_content(
    content: str | StringIO | Iterable[str], chunksize: int | None = None
) -> Iterator[str]: ...
@overload
def _chunk_content(
    content: bytes | BytesIO | Iterable[bytes], chunksize: int | None = None
) -> Iterator[bytes]: ...
def _chunk_content(
    content: WriteContent, chunksize: int | None = None
) -> Iterator[AnyStr]:
    """
    Splits content into whole ``str`` or ``bytes`` chunks.

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
        >>> list(_chunk_content(iter(["ab", "cd"])))
        ['ab', 'cd']

    """
    if isinstance(content, str):
        for raw in chunk(content, chunksize):
            yield "".join(raw)
    elif isinstance(content, TextIOBase):
        yield from chunk(content, chunksize)
    elif isinstance(content, bytes):
        for raw in chunk(content, chunksize):
            yield bytes(raw)
    elif isinstance(content, BufferedIOBase):
        yield from chunk(content, chunksize)
    else:
        yield from content


def _normalize_chunk(raw: AnyStr, binary: bool, encoding: str) -> AnyStr:
    if isinstance(raw, str):
        result: AnyStr = raw.encode(encoding) if binary else raw
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
    def name(self) -> str:
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
    if is_http_url(url):
        response = await async_get(url, timeout=timeout)
        content_type = response.headers.get("content-type")
        result = (response.content, url, content_type)
    else:
        response = await async_read(url, binary=True)
        result = (response, url.replace("file://", ""), None)

    return result


class _AsyncURLStream[T: BytesIO | NamedTextIOWrapper]:
    """
    An awaitable, async-context-manager handle over a lazily opened buffer.

    ``await``-ing it returns the opened buffer (the caller then owns closing it), while
    ``async with`` yields the buffer and closes it on exit. Both paths open a fresh
    buffer. The handle is reusable, but not reentrant: entering it before the previous
    ``async with`` exits raises ``RuntimeError``.
    """

    def __init__(self, opener: Callable[[], Awaitable[T]]) -> None:
        self._open = opener
        self._stream: BytesIO | NamedTextIOWrapper | None = None

    def __await__(self) -> Generator[object, None, T]:
        return self._open().__await__()

    async def __aenter__(self) -> T:
        if self._stream is not None:
            raise RuntimeError("an async_url_open handle is not reentrant")

        opened = await self._open()
        self._stream = opened
        return opened

    async def __aexit__(self, *_: object) -> bool:
        if self._stream is not None:
            self._stream.close()
            self._stream = None

        return False


@overload
def async_url_open(
    url: str,
    timeout: float = ...,
    encoding: str = ...,
    *,
    binary: Literal[True],
    **_: object,
) -> _AsyncURLStream[BytesIO]: ...
@overload
def async_url_open(
    url: str,
    timeout: float = ...,
    encoding: str = ...,
    binary: Literal[False] = ...,
    **_: object,
) -> _AsyncURLStream[NamedTextIOWrapper]: ...
def async_url_open(
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
    used with ``async with`` to auto-close it on exit. Entering it again before the
    previous ``async with`` exits raises ``RuntimeError``. Use ``async with`` only when
    the buffer is consumed inside the block. When returning a lazy iterator that
    outlives the block, keep the ``await`` form and release the handle on iteration
    end with :func:`riko.io._sync.auto_close` (an ``async with`` would close it
    before the caller ever reads it).

    Args:

        url: An ``http(s)`` URL or a local path.
        timeout: The HTTP request timeout in seconds; ``0`` means no timeout.
        encoding: The text decoding used when ``binary`` is False.
        binary: Whether to return raw bytes rather than decoded text.

    Returns:

        A handle whose buffer is a ``BytesIO`` when ``binary`` is True, else a
        ``NamedTextIOWrapper`` carrying the source name and content type.

    Examples:

        >>> from riko import get_path, run
        >>>
        >>> url = get_path("spreadsheet.csv")
        >>>
        >>> async def main():
        ...     async with async_url_open(url) as f:
        ...         print(f.readline())
        >>>
        >>> run(main)
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

        >>> from riko import get_path, run
        >>>
        >>> async def main():
        ...     content = await async_url_read(get_path("spreadsheet.csv"))
        ...     print(content[:6])
        >>>
        >>> run(main)
        Member

    """
    url = normalize_url(url, offline=True)

    if is_http_url(url):
        response = await async_get(url, timeout=timeout)
        content = response.text
    else:
        content = await async_read(url, encoding=encoding)

    return content


async def async_write(
    dest: PathLike,
    content: WriteContent,
    mode: str = "wb+",
    encoding: str = ENCODING,
    chunksize: int | None = None,
    **_: object,
) -> int:
    """
    Asynchronously writes content to a file.

    Args:

        dest: The destination path.
        content: The data to write.
        mode: The file mode; a ``"b"`` in it selects binary I/O.
        encoding: The text encoding used when ``mode`` is not binary.
        chunksize: The units to write per ``content`` chunk, or ``None`` for a single
            chunk (ignored for content that isn't a ``str``, ``bytes``, or file-like
            object).

    Returns:

        The number of units (bytes or characters) written.

    Examples:

        >>> from io import StringIO
        >>> from riko import async_get_temp_file, run
        >>>
        >>> async def main():
        ...     async with async_get_temp_file() as fp:
        ...         await async_write(fp.name, StringIO("Hello World"))
        ...
        ...         with open(fp.name, mode="rb") as f:
        ...             print(f.read())
        >>>
        >>> run(main)
        b'Hello World'

    """
    if not _is_open_mode(mode):
        raise ValueError(f"the file mode {mode!r} is invalid")

    progress = 0
    binary = "b" in mode
    open_encoding = None if binary else encoding
    opener = async_open(dest, mode, encoding=open_encoding)

    async with await opener as f:
        for normalized in _chunk_content(content, chunksize):
            data = _normalize_chunk(normalized, binary, encoding)
            await f.write(data)  # pyright: ignore[reportArgumentType]
            progress += len(data)

    written = progress
    return written


def async_get_temp_file() -> NamedTemporaryFile[bytes]:
    """
    Creates an auto-deleting named temporary file for async use.

    A plain ``def`` (not a coroutine) returning anyio's async context manager.
    ``async with`` needs no ``await`` on the call itself.

    Returns:

        An anyio ``NamedTemporaryFile`` context manager over a binary temp file
        that is removed when the context exits.

    Examples:

        >>> from riko import run
        >>>
        >>> async def main():
        ...     async with async_get_temp_file() as f:
        ...         await f.write(b"hi")
        ...         print(f.name is not None)
        >>>
        >>> run(main)
        True

    """
    return NamedTemporaryFile(delete=True, delete_on_close=False)
