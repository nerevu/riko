# vim: sw=4:ts=4:expandtab
"""
riko.bado.io
~~~~~~~~~~~~
Async file/url reading for riko pipes (anyio + httpx).

Examples:
    basic usage::

        >>> from riko import get_path
        >>> from riko.bado.io import async_url_open

"""

from collections.abc import Iterator
from io import BytesIO, StringIO, TextIOWrapper
from logging import Logger
from typing import TYPE_CHECKING, Literal, cast, overload

import pygogo as gogo
from meza.fntools import chunk as _chunk

from riko import ENCODING, bado
from riko._io import ext_from_content_type
from riko.bado import async_get, async_read, open_file
from riko.paths import get_abspath

if TYPE_CHECKING:
    from _typeshed import OpenBinaryMode, OpenTextMode

    from riko.bado import NamedTemporaryFile

logger: Logger = gogo.Gogo(__name__, monolog=True).logger


def chunk(
    content: str | bytes | BytesIO | StringIO,
    chunksize: int | None = None,
    *args: int,
    **kwargs: int,
) -> Iterator[str | bytes | list[bytes | int | str]]:
    result = _chunk(content, chunksize, *args, **kwargs)
    return cast(Iterator[str | bytes | list[int | str | bytes]], result)


def _coerce_chunk(raw: str | bytes, binary: bool, encoding: str) -> str | bytes:
    if isinstance(raw, str):
        result: str | bytes = raw.encode(encoding) if binary else raw
    else:
        result = raw if binary else raw.decode(encoding)

    return result


class NamedTextIOWrapper(TextIOWrapper):
    _name: str = ""
    content_type: str | None = None

    @property
    def name(self) -> str:  # type: ignore[override]
        return self._name

    @name.setter
    def name(self, value: str) -> None:
        self._name = value

    @property
    def ext(self) -> str | None:
        return ext_from_content_type(self.content_type)


async def _read_bytes(url: str, timeout: float) -> tuple[bytes, str, str | None]:
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
    data, name, content_type = await _read_bytes(url, timeout)

    if binary:
        f: BytesIO | NamedTextIOWrapper = BytesIO(data)
    else:
        f = NamedTextIOWrapper(BytesIO(data), encoding=encoding)
        f.name = name
        f.content_type = content_type

    return f


async def async_url_read(
    url: str,
    timeout: float = 0,
    encoding: str = ENCODING,
    **kwargs: object,
) -> str:
    url = get_abspath(url, offline=True)

    if url.startswith("http"):
        response = await async_get(url, timeout=timeout)
        content = response.text
    else:
        content = await async_read(url, encoding=encoding)

    return content


async def async_write(
    filepath: str,
    content: str | bytes | BytesIO | StringIO,
    mode: str = "wb+",
    encoding: str = ENCODING,
    chunksize: int | None = None,
    **kwargs: object,
) -> int:
    """
    Asynchronously writes ``content`` (a file-like object, iterable, ``str`` or
    ``bytes``) to ``filepath`` using anyio's async file I/O, mirroring
    :func:`meza.io.write` chunking/mode/encoding semantics. Returns the number of units
    written.

    Examples:
        >>> from io import StringIO
        >>> from riko import get_temp_file, run
        >>>
        >>> async def main():
        ...     with get_temp_file() as fp:
        ...         await async_write(fp.name, StringIO("Hello World"))
        ...
        ...         with open(fp.name, mode="rb") as f:
        ...             print(f.read())
        >>>
        >>> run(main)
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
    return bado.NamedTemporaryFile(delete=True, delete_on_close=False)
