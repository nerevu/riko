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
        >>> url = get_path("spreadsheet.csv")
        >>>
        >>> async def main():
        ...     f = await async_url_open(url)
        ...     print(f.readline())
        ...     f.close()
        >>>
        >>> print("Member,Name,") if issync else run(main)
        Member,Name,...

"""

from collections.abc import Iterator
from io import BytesIO, StringIO, TextIOWrapper
from logging import Logger
from pathlib import Path
from typing import TYPE_CHECKING, Literal, cast, overload

import pygogo as gogo
from meza.fntools import chunk as _chunk

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


def chunk(
    content: str | bytes | BytesIO | StringIO,
    chunksize: int | None = None,
    *args: int,
    **kwargs: int,
) -> Iterator[str | bytes | list[bytes | int | str]]:
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
        Each chunk; a ``str``/``bytes`` for an unsized whole, or a ``list`` of
        elements (characters, bytes or ints) when sized.

    Examples:
        >>> list(chunk("abcdef", 3))
        [['a', 'b', 'c'], ['d', 'e', 'f']]

    """
    result = _chunk(content, chunksize, *args, **kwargs)
    return cast(Iterator[str | bytes | list[int | str | bytes]], result)


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


@overload
async def async_url_open(  # noqa: E704
    url: str,
    timeout: float = ...,
    encoding: str = ...,
    *,
    binary: Literal[True],
    **kwargs: object,
) -> BytesIO: ...
@overload  # noqa: E302
async def async_url_open(  # noqa: E704
    url: str,
    timeout: float = ...,
    encoding: str = ...,
    binary: Literal[False] = ...,
    **kwargs: object,
) -> NamedTextIOWrapper: ...
async def async_url_open(  # noqa: E302
    url: str,
    timeout: float = 0,
    encoding: str = ENCODING,
    binary: bool = False,
    **kwargs: object,
) -> BytesIO | NamedTextIOWrapper:
    """
    Opens a URL or local file as an in-memory, file-like stream.

    Args:
        url: An ``http(s)`` URL or a local path.
        timeout: The HTTP request timeout in seconds; ``0`` means no timeout.
        encoding: The text decoding used when ``binary`` is False.
        binary: Whether to return raw bytes rather than decoded text.
        **kwargs: Accepted for signature parity; ignored.

    Returns:
        A ``BytesIO`` when ``binary`` is True, else a ``NamedTextIOWrapper``
        carrying the source name and content type.

    Examples:
        >>> from riko import get_path, issync, run
        >>>
        >>> async def main():
        ...     url = get_path("spreadsheet.csv")
        ...     f = await async_url_open(url, binary=True)
        ...     print(type(f).__name__)
        ...     f.close()
        >>>
        >>> print("BytesIO") if issync else run(main)
        BytesIO

    """
    data, name, content_type = await _read_bytes(url, timeout)

    if binary:
        f: BytesIO | NamedTextIOWrapper = BytesIO(data)
    else:
        f = NamedTextIOWrapper(BytesIO(data), encoding=encoding)
        f.name = name
        f.content_type = content_type

    return f


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
    if binary := "b" in mode:
        mode = cast("OpenBinaryMode", mode)
    else:
        mode = cast("OpenTextMode", mode)

    progress = 0
    opener = open_file(filepath, mode, encoding=None if binary else encoding)

    async with await opener as f:
        for raw in chunk(content, chunksize):
            if isinstance(raw, (str, bytes)):
                normalized = raw
            elif isinstance(raw[0], str):
                normalized = "".join(cast(list[str], raw))
            elif isinstance(raw[0], bytes):
                normalized = b"".join(cast(list[bytes], raw))
            else:
                normalized = bytes(cast(list[int], raw))

            data = _coerce_chunk(normalized, binary, encoding)
            await f.write(data)  # pyright: ignore[reportArgumentType]
            progress += len(data)

    written = progress
    return written


def get_async_temp_file() -> "NamedTemporaryFile[bytes]":
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
