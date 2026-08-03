# vim: sw=4:ts=4:expandtab
"""
riko._io
~~~~~~~~
HTTP/file I/O: URL/file openers, the ``Fetch`` context manager, response
introspection, and blocking-fd helpers.
"""

from codecs import StreamReader
from collections.abc import Iterable, Iterator, Mapping
from functools import partial, wraps
from http.client import HTTPResponse
from io import BytesIO, RawIOBase, StringIO, TextIOBase
from logging import Logger
from typing import Literal, cast, overload
from urllib.error import URLError
from urllib.request import Request, urlopen
from urllib.response import addinfourl

try:
    import fcntl
    from os import O_NONBLOCK
except ImportError:
    fcntl = None
    O_NONBLOCK = 0

import mezmorize
import pygogo as gogo
import requests
from meza.io import reencode
from mezmorize.utils import get_cache_type

from riko import ENCODING, __version__, get_abspath
from riko._feed import truncate_content
from riko._serialize import repr_cache
from riko.types.general import FileTypes, Opener
from riko.types.values import BasicArg

logger: Logger = gogo.Gogo(__name__, verbose=False, monolog=True).logger


def make_blocking(f: RawIOBase | TextIOBase) -> None:
    if fcntl is not None:
        fd = f.fileno()
        flags = fcntl.fcntl(fd, fcntl.F_GETFL)

        if flags & O_NONBLOCK:
            blocking = flags & ~O_NONBLOCK
            fcntl.fcntl(fd, fcntl.F_SETFL, blocking)


def default_user_agent(name: str = "riko") -> str:
    """
    Return a string representing the default user agent.
    :rtype: str
    """
    return f"{name}/{__version__}"


def get_response_content_type(r: HTTPResponse | addinfourl | requests.Response) -> str:
    content_type = r.headers.get("Content-Type", "")
    return content_type.lower()


def get_response_encoding(
    r: HTTPResponse | addinfourl, def_encoding: str = ENCODING
) -> str:
    content_type = get_response_content_type(r)

    if "charset=" in content_type:
        ctype = content_type.split("charset=")[1]
        encoding = ctype.strip().strip('"').strip("'")
    else:
        encoding = None

    return encoding or def_encoding


# https://docs.python.org/3.3/reference/expressions.html#examples
def auto_close[T](stream: Iterable[T], f: FileTypes) -> Iterator[T]:
    try:
        yield from stream
    finally:
        f.close()


@overload
def opener(  # noqa: E704
    url: str,
    memoize: Literal[True],
    delay: int = ...,
    encoding: str = ...,
    params: Mapping[str, str | bytes | int | float] | None = ...,
    offline: bool = ...,
    *,
    binary: Literal[True],
    timeout: float | None = None,
    **_: object,
) -> tuple[BytesIO, str | None]: ...
@overload  # noqa: E302
def opener(  # noqa: E704
    url: str,
    memoize: Literal[False] = ...,
    delay: int = ...,
    encoding: str = ...,
    params: Mapping[str, str | bytes | int | float] | None = ...,
    offline: bool = ...,
    *,
    binary: Literal[True],
    timeout: float | None = None,
    **_: object,
) -> tuple[RawIOBase, str | None]: ...
@overload  # noqa: E302
def opener(  # noqa: E704
    url: str,
    memoize: Literal[True],
    delay: int = ...,
    encoding: str = ...,
    params: Mapping[str, str | bytes | int | float] | None = ...,
    offline: bool = ...,
    binary: Literal[False] = ...,
    timeout: float | None = None,
    **_: object,
) -> tuple[StringIO, str | None]: ...
@overload  # noqa: E302
def opener(  # noqa: E704
    url: str,
    memoize: Literal[False] = ...,
    delay: int = ...,
    encoding: str = ...,
    params: Mapping[str, str | bytes | int | float] | None = ...,
    offline: bool = ...,
    binary: Literal[False] = ...,
    timeout: float | None = None,
    **_: object,
) -> tuple[StreamReader, str | None]: ...
def opener(  # noqa: E302
    url: str,
    memoize: bool = False,
    delay: int = 0,
    encoding: str = ENCODING,
    params: Mapping[str, str | bytes | int | float] | None = None,
    offline: bool = True,
    binary: bool = False,
    timeout: float | None = None,
    **_: object,
) -> tuple[FileTypes, str | None]:
    params = params or {}
    url = get_abspath(url, offline=offline)
    r = None

    if url.startswith("http") and params:
        r = requests.get(url, params=params, stream=binary, timeout=timeout)
        r.raw.decode_content = not binary

        if binary:
            response = BytesIO(r.content) if memoize else cast(RawIOBase, r.raw)
        elif memoize:
            response = StringIO(r.text)
        else:
            encoding = r.encoding or encoding
            reencoded = reencode(r.raw, encoding, decode=True)
            # TODO: Add self._f = f to Reencoder
            reencoded._r = r  # pyright: ignore[reportAttributeAccessIssue]
            response = cast(StreamReader, reencoded)
    else:
        req = Request(url, headers={"User-Agent": default_user_agent()})  # noqa: S310

        if delay:
            logger.debug("Request delaying not currently implemented.")

        if (r := urlopen(req, timeout=timeout)) and binary:  # noqa: S310
            response = BytesIO(r.read()) if memoize else cast(RawIOBase, r)
        elif r:
            encoding = get_response_encoding(r, encoding)

            if not (binary or encoding):
                encoding = ENCODING

            if memoize and encoding:
                response = StringIO(r.read().decode(encoding))
            elif memoize:
                response = StringIO(r.read())
            elif encoding:
                reencoded = reencode(r.fp, encoding, decode=True)
                # TODO: Add self._f = f to Reencoder
                reencoded._r = r  # pyright: ignore[reportAttributeAccessIssue]
                response = cast(StreamReader, reencoded)
            else:
                response = cast(TextIOBase, r)
        else:
            response = BytesIO() if binary else StringIO()

    content_type = get_response_content_type(r) if r else None
    return (response, content_type)


@repr_cache
def get_opener(memoize: bool = False, **kwargs: object) -> Opener:
    """
    Examples:
        >>> get_opener.cache_clear()
        >>> o1 = get_opener()
        >>> o1 is get_opener()
        True
        >>> o1 is get_opener(encoding='utf-8')
        False
        >>> get_opener.cache_info().hits
        1
        >>> o2 = get_opener(memoize=True)
        >>> o2 is get_opener(memoize=True)
        True
        >>> get_opener.cache_info().hits
        2

    """
    wrapper = partial(opener, memoize=memoize, **kwargs)
    current_opener = wraps(opener)(wrapper)

    if memoize:
        kwargs.setdefault("cache_type", get_cache_type(spread=False))
        return mezmorize.memoize(**kwargs)(current_opener)

    return current_opener


class Fetch[B: (Literal[True], Literal[False])]:
    binary: B
    file: FileTypes | None
    content_type: str | None

    @overload
    def __init__(  # noqa: E704
        self: "Fetch[Literal[True]]",
        url: str = ...,
        *,
        binary: Literal[True],
        **kwargs: BasicArg,
    ) -> None: ...
    @overload  # noqa: E301
    def __init__(  # noqa: E704
        self: "Fetch[Literal[False]]",
        url: str = ...,
        *,
        binary: Literal[False] = ...,
        **kwargs: BasicArg,
    ) -> None: ...
    def __init__(  # noqa: E301
        self,
        url: str = "",
        *,
        memoize: BasicArg = False,
        binary: bool = False,
        **kwargs: BasicArg,
    ) -> None:
        # TODO: need to use separate timeouts for memoize and urlopen
        self.binary = binary  # pyright: ignore[reportAttributeAccessIssue]
        self.content_type = None
        self.file = None
        opener = get_opener(memoize=bool(url and memoize), binary=binary, **kwargs)

        try:
            self.file, self.content_type = opener(url)
        except URLError as e:
            if "File name too long" in str(e.reason):
                raise

            logger.error(f"Error opening {truncate_content(url)}: {e.reason}")

    def __getattr__(self, name: str) -> object:
        if self.file is not None:
            return getattr(self.file, name)

        raise AttributeError(name)

    def close(self) -> None:
        if self.file:
            response = getattr(self.file, "_r", None)

            try:
                self.file.close()
            finally:
                if response is not None:
                    response.close()

            self.file = None

    def __enter__(self) -> "Fetch[B]":
        return self

    def __exit__(self, *_: object) -> None:
        self.close()

    @overload
    def __iter__(self: "Fetch[Literal[True]]") -> Iterator[bytes]: ...  # noqa: E704
    @overload
    def __iter__(self: "Fetch[Literal[False]]") -> Iterator[str]: ...  # noqa: E704
    def __iter__(self) -> Iterator[bytes | str]:  # noqa: E301
        if self.file:
            result = iter(self.file)
        elif self.binary:
            result = iter([b""])
        else:
            result = iter([""])

        return result

    @overload
    def __next__(self: "Fetch[Literal[True]]") -> bytes: ...  # noqa: E704
    @overload
    def __next__(self: "Fetch[Literal[False]]") -> str: ...  # noqa: E704
    def __next__(self) -> bytes | str:  # noqa: E301
        if self.file:
            return next(self.file)

        raise StopIteration

    @overload
    def read(self: "Fetch[Literal[True]]", size: int = ...) -> bytes: ...  # noqa: E704
    @overload
    def read(self: "Fetch[Literal[False]]", size: int = ...) -> str: ...  # noqa: E704
    def read(self, size: int = -1) -> bytes | str:  # noqa: E301
        if self.file and size < 0:
            result = self.file.read()
        elif self.file:
            result = self.file.read(size)
        else:
            result = b"" if self.binary else ""

        return result

    @property
    def ext(self) -> str | None:
        if not self.content_type:
            ext = None
        elif "xml" in self.content_type:
            ext = "xml"
        elif "json" in self.content_type:
            ext = "json"
        else:
            ext = self.content_type.split("/")[1].split(";")[0]

        return ext
