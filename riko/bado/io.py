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

from io import BytesIO, TextIOWrapper
from typing import Literal, overload

import pygogo as gogo

from riko import ENCODING, get_abspath
from riko.bado import Path, async_get, async_sleep

logger = gogo.Gogo(__name__, monolog=True).logger


class NamedTextIOWrapper(TextIOWrapper):
    _name: str = ""

    @property
    def name(self) -> str:  # type: ignore[override]
        return self._name

    @name.setter
    def name(self, value: str) -> None:
        self._name = value


async def _read_bytes(url: str, timeout: float) -> tuple[bytes, str]:
    if url.startswith("http"):
        response = await async_get(url, timeout=timeout)
        result = (response.content, url)
    else:
        path = url.replace("file://", "")
        result = (await Path(path).read_bytes(), path)

    return result


@overload
async def async_url_open(  # noqa: E704
    url: str,
    timeout: float = ...,
    encoding: str = ...,
    *,
    binary: Literal[True],
    **kwargs,
) -> BytesIO: ...
@overload  # noqa: E302
async def async_url_open(  # noqa: E704
    url: str,
    timeout: float = ...,
    encoding: str = ...,
    binary: Literal[False] = ...,
    **kwargs,
) -> NamedTextIOWrapper: ...
async def async_url_open(  # noqa: E302
    url: str,
    timeout: float = 0,
    encoding: str = ENCODING,
    binary: bool = False,
    **kwargs,
) -> BytesIO | NamedTextIOWrapper:
    data, name = await _read_bytes(url, timeout)

    if binary:
        f: BytesIO | NamedTextIOWrapper = BytesIO(data)
    else:
        f = NamedTextIOWrapper(BytesIO(data), encoding=encoding)
        f.name = name

    return f


async def async_url_read(
    url: str, timeout: float = 0, encoding: str = ENCODING, delay: float = 0, **kwargs
) -> str:
    if delay:
        await async_sleep(delay)

    url = get_abspath(url, offline=True)

    if url.startswith("http"):
        response = await async_get(url, timeout=timeout)
        content = response.text
    else:
        content = await Path(url.replace("file://", "")).read_text(encoding)

    return content
