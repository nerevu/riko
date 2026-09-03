# vim: sw=4:ts=4:expandtab
"""
riko._io
~~~~~~~~

Provides HTTP and file I/O helpers.

Attributes:
    STREAMING_THRESHOLD: Response size above which content is streamed.

"""

from codecs import StreamReader
from collections.abc import Iterable, Iterator, Mapping
from functools import partial, wraps
from http.client import HTTPResponse
from io import BytesIO, RawIOBase, StringIO, TextIOBase
from logging import Logger
from tempfile import SpooledTemporaryFile
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
from mezmorize.utils import get_cache_type

from riko._constants import ENCODING, STREAMING_THRESHOLD
from riko._metadata import __version__
from riko._reencode import reencode
from riko._rssutils import truncate_content
from riko._serialize import repr_cache
from riko.paths import get_abspath
from riko.types._collections import BasicArg
from riko.types._io import BinaryFileLike, FileLike, Opener, StringFileLike
from riko.types._scalars import AnyStr

logger: Logger = gogo.Gogo(__name__, verbose=False, monolog=True).logger


def ext_from_content_type(content_type: str | None) -> str | None:
    """
    Maps a content type to its file extension.

    Args:
        content_type: The response content type, if the source reported one.

    Returns:
        ``"xml"``/``"json"`` for the feed types, otherwise the content subtype,
        or ``None`` when no content type is available.

    Examples:
        >>> ext_from_content_type("application/json; charset=utf-8")
        'json'
        >>> ext_from_content_type("text/html")
        'html'
        >>> ext_from_content_type(None) is None
        True

    """
    if not content_type:
        ext = None
    elif "xml" in content_type:
        ext = "xml"
    elif "json" in content_type:
        ext = "json"
    else:
        ext = content_type.split("/")[1].split(";")[0]

    return ext


def make_blocking(f: RawIOBase | TextIOBase) -> None:
    """
    Clears the ``O_NONBLOCK`` flag on ``f`` so its reads block.

    riko's readers expect blocking reads; a non-blocking descriptor would not
    wait for data. A no-op where ``fcntl`` is unavailable (e.g. Windows).

    Args:
        f: The file whose descriptor is switched to blocking mode.

    Raises:
        io.UnsupportedOperation: If ``f`` has no underlying file descriptor.

    """
    if fcntl is not None:
        fd = f.fileno()
        flags = fcntl.fcntl(fd, fcntl.F_GETFL)

        if flags & O_NONBLOCK:
            blocking = flags & ~O_NONBLOCK
            fcntl.fcntl(fd, fcntl.F_SETFL, blocking)


def default_user_agent(name: str = "riko") -> str:
    """
    Formats the default user agent as ``name/version``.

    Args:
        name: The product name in the ``name/version`` string.

    Returns:
        The ``name/version`` user agent string.

    Examples:
        >>> default_user_agent("app")  # doctest: +ELLIPSIS
        'app/...'

    """
    return f"{name}/{__version__}"


def get_response_content_type(r: HTTPResponse | addinfourl | requests.Response) -> str:
    """
    Reads the response's ``Content-Type`` header.

    Args:
        r: The HTTP response to inspect.

    Returns:
        The lowercased content type, or ``""`` when the header is absent.

    Examples:
        >>> from types import SimpleNamespace
        >>>
        >>> r = SimpleNamespace(headers={"Content-Type": "Application/JSON"})
        >>> get_response_content_type(r)
        'application/json'

    """
    content_type = r.headers.get("Content-Type", "")
    return content_type.lower()


def get_response_encoding(
    r: HTTPResponse | addinfourl, def_encoding: str = ENCODING
) -> str:
    """
    Resolves the response's charset.

    Args:
        r: The HTTP response to inspect.
        def_encoding: The fallback used when no charset is declared.

    Returns:
        The declared charset, otherwise ``def_encoding``.

    Examples:
        >>> from types import SimpleNamespace
        >>>
        >>> ct = "text/html; charset=latin-1"
        >>> get_response_encoding(SimpleNamespace(headers={"Content-Type": ct}))
        'latin-1'
        >>> plain = SimpleNamespace(headers={"Content-Type": "text/html"})
        >>> get_response_encoding(plain, "utf-8")
        'utf-8'

    """
    content_type = get_response_content_type(r)

    if "charset=" in content_type:
        ctype = content_type.split("charset=")[1]
        encoding = ctype.strip().strip('"').strip("'")
    else:
        encoding = None

    return encoding or def_encoding


# https://docs.python.org/3.3/reference/expressions.html#examples
def auto_close[T](stream: Iterable[T], *files: FileLike) -> Iterator[T]:
    """
    Passes ``stream`` through so it closes ``files`` when iteration ends.

    Pairs a fetched stream with the files backing it. Closing runs in a
    ``finally``, so each file is released on exhaustion, an early ``break``, or an
    exception. This is the tool for handles whose consumption is deferred. I.e., a
    parser that returns a lazy iterator after opening a file keeps the file alive
    until the caller drains it. Whereas a ``with``/``async with`` block would close
    it before the first item is read. Pass more than one file when a ``seekable``
    copy is read but the original fetch must still be released; closing an already
    closed file is a harmless no-op.

    Args:
        stream: The items to yield.
        files: The files closed once iteration finishes.

    Yields:
        The elements of ``stream``.

    Examples:
        >>> from io import StringIO
        >>>
        >>> f = StringIO("hi")
        >>> list(auto_close(f, f))
        ['hi']
        >>> f.closed
        True

    """
    try:
        yield from stream
    finally:
        for f in files:
            f.close()


@overload
def buffer(  # noqa: E704
    f: StringFileLike, binary: bool = ..., encoding: str = ...
) -> SpooledTemporaryFile[str]: ...
@overload  # noqa: E302
def buffer(  # noqa: E704
    f: BinaryFileLike, binary: bool = ..., encoding: str = ...
) -> SpooledTemporaryFile[bytes]: ...
@overload  # noqa: E302
def buffer(  # noqa: E704
    f: BinaryFileLike, binary: bool = ..., *, encoding: str
) -> SpooledTemporaryFile[str]: ...
@overload  # noqa: E302
def buffer(  # noqa: E704
    f: FileLike, binary: bool | None = ..., encoding: str | None = ...
) -> SpooledTemporaryFile[bytes] | SpooledTemporaryFile[str]: ...
def buffer(  # noqa: E302
    f: FileLike, binary: bool | None = None, encoding: str | None = None
) -> SpooledTemporaryFile[bytes] | SpooledTemporaryFile[str]:
    """
    Buffers ``f`` into a re-readable copy.

    The spool stays in memory until it exceeds the streaming threshold, then
    spills to disk. Byte streams are decoded when ``encoding`` is set; ``binary``
    is auto-detected from the first chunk when not supplied.

    Args:
        f: The forward-only stream to copy.
        binary: Whether the chunks are bytes. Auto-detected when omitted.
        encoding: Encoding used to decode byte chunks while buffering.

    Returns:
        A rewound spool holding the contents of ``f``.

    Examples:
        >>> from io import StringIO
        >>>
        >>> spool = buffer(StringIO("abc"))
        >>> spool.read()
        'abc'
        >>> spool.close()

    """
    chunks = iter(f)
    first = None

    if binary is None:
        first = next(chunks, None)
        binary = isinstance(first, bytes)

    decode = binary and encoding
    encoding = encoding or ""
    mode = "w+b" if binary and not decode else "w+"
    spool = SpooledTemporaryFile(  # noqa: SIM115
        max_size=STREAMING_THRESHOLD, mode=mode
    )

    if first is not None:
        spool.write(cast(bytes, first).decode(encoding) if decode else first)

    for chunk in chunks:
        spool.write(cast(bytes, chunk).decode(encoding) if decode else chunk)

    spool.seek(0)
    return spool


def seekable(
    f: FileLike, binary: bool | None = None, encoding: str | None = None
) -> FileLike | SpooledTemporaryFile[bytes] | SpooledTemporaryFile[str]:
    """
    Rewinds ``f``, or buffers a copy when it cannot be rewound.

    A fetched stream is forward-only, so readers that need a second pass (e.g.
    a headerless csv) get a spooled copy instead. ``f`` is consumed when it is
    buffered, so close it separately.

    Args:
        f: The file to rewind or copy.
        binary: Whether the chunks are bytes. Auto-detected when omitted.
        encoding: Encoding used to decode byte chunks while buffering.

    Returns:
        ``f`` itself when it rewound, otherwise a rewound spooled copy.

    Examples:
        >>> from io import StringIO
        >>>
        >>> f = StringIO("abc")
        >>> seekable(f) is f
        True

    """
    seek = getattr(f, "seek", None)
    rewound = False

    if callable(seek):
        try:
            seek(0)
        except (OSError, ValueError, AttributeError):
            pass
        else:
            rewound = True

    return f if rewound else buffer(f, binary=binary, encoding=encoding)


@overload
def opener(  # noqa: E704
    url: str,
    memoize: Literal[True],
    encoding: str = ...,
    params: Mapping[str, AnyStr | int | float] | None = ...,
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
    encoding: str = ...,
    params: Mapping[str, AnyStr | int | float] | None = ...,
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
    encoding: str = ...,
    params: Mapping[str, AnyStr | int | float] | None = ...,
    offline: bool = ...,
    binary: Literal[False] = ...,
    timeout: float | None = None,
    **_: object,
) -> tuple[StringIO, str | None]: ...
@overload  # noqa: E302
def opener(  # noqa: E704
    url: str,
    memoize: Literal[False] = ...,
    encoding: str = ...,
    params: Mapping[str, AnyStr | int | float] | None = ...,
    offline: bool = ...,
    binary: Literal[False] = ...,
    timeout: float | None = None,
    **_: object,
) -> tuple[StreamReader, str | None]: ...
def opener(  # noqa: E302
    url: str,
    memoize: bool = False,
    encoding: str = ENCODING,
    params: Mapping[str, AnyStr | int | float] | None = None,
    offline: bool = True,
    binary: bool = False,
    timeout: float | None = None,
    **_: object,
) -> tuple[FileLike, str | None]:
    """
    Opens a url or file.

    ``http(s)`` urls go through ``requests``; anything else through ``urllib``
    or the filesystem. The stream is lazy unless ``memoize`` is set. In that case
    it buffers the body so it can be re-read. ``binary`` selects bytes over decoded
    text, and ``encoding`` decodes byte streams.

    Args:
        url: The resource to open.
        memoize: Whether to buffer the body for re-reading.
        encoding: Encoding used to decode byte streams.
        params: Query parameters for http requests.
        offline: Whether to treat a schemeless path as a local file (not an http host).
        binary: Whether to return bytes rather than decoded text.
        timeout: Per-request timeout in seconds.

    Returns:
        A ``(stream, content_type)`` pair; ``content_type`` is ``None`` when the
        source reports none.

    Raises:
        TypeError: If ``url`` is empty.

    """
    if not url:
        raise TypeError("a url is required")

    params = params or {}
    url = get_abspath(url, offline=offline)
    r = None

    if url.startswith("http"):
        r = requests.get(
            url,
            params=params,
            headers={"User-Agent": default_user_agent()},
            stream=not memoize,
            timeout=timeout,
        )
        r.raise_for_status()
        r.raw.decode_content = True

        if binary and memoize:
            response = BytesIO(r.content)
            r.close()
        elif binary:
            response = cast(RawIOBase, r.raw)
        elif memoize:
            response = StringIO(r.text)
            r.close()
        else:
            encoding = r.encoding or encoding
            reencoded = reencode(r.raw, encoding, decode=True, owner=r)
            response = cast(StreamReader, reencoded)
    else:
        req = Request(url, headers={"User-Agent": default_user_agent()})  # noqa: S310

        if (r := urlopen(req, timeout=timeout)) and binary:  # noqa: S310
            response = buffer(r, binary=True) if memoize else cast(RawIOBase, r)
        elif r:
            encoding = get_response_encoding(r, encoding)

            if not (binary or encoding):
                encoding = ENCODING

            if memoize and encoding:
                response = buffer(r, encoding=encoding)
            elif memoize:
                response = buffer(r, binary=False)
            elif encoding:
                reencoded = reencode(r.fp, encoding, decode=True, owner=r)
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
    Builds a URL opener cached by call arguments.

    Args:
        memoize: Whether the returned opener buffers responses for re-reading.

    Returns:
        An opener callable; identical arguments return the cached opener.

    Examples:
        >>> get_opener.cache_clear()
        >>> o1 = get_opener()
        >>> o1 is get_opener()
        True
        >>> o1 is get_opener(encoding="utf-8")
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
    """
    Opens a url or file as an iterable byte or text stream.

    Degrades on a failed fetch: a ``URLError``/``RequestException`` is logged and
    the instance yields a single empty chunk instead of raising. A broken source drops
    out of a pipeline rather than aborting it.

    Args:
        url: The resource to open; empty yields an empty stream.
        memoize: Whether to buffer the body so it can be re-read.
        binary: Whether to expose bytes rather than decoded text.

    """

    binary: B
    file: FileLike | None
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
        except requests.RequestException as e:
            logger.error(f"Error opening {truncate_content(url)}: {e}")

    def __getattr__(self, name: str) -> object:
        if self.file is not None:
            return getattr(self.file, name)

        raise AttributeError(name)

    def close(self) -> None:
        if self.file:
            self.file.close()
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
        if self.file:
            result = self.file.read(size)
        else:
            result = b"" if self.binary else ""

        return result

    @property
    def ext(self) -> str | None:
        """The file extension implied by the response content type."""
        return ext_from_content_type(self.content_type)
