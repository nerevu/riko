# vim: sw=4:ts=4:expandtab
"""
Synchronous file and URL I/O helpers.

Examples:

    Basic usage::

        >>> from riko import get_path
        >>>
        >>> with Fetch(get_path("spreadsheet.csv")) as f:
        ...     print(f.readline())
        Member,Name,...

Attributes:

    STREAMING_THRESHOLD: Response size above which content is streamed.

"""

from __future__ import annotations

from contextlib import ExitStack, contextmanager
from functools import partial, wraps
from io import BytesIO, RawIOBase, StringIO
from math import isinf
from pathlib import Path
from tempfile import NamedTemporaryFile, SpooledTemporaryFile, TemporaryDirectory
from typing import IO, TYPE_CHECKING, Literal, cast, overload
from urllib.request import Request, urlopen

import mezmorize
import requests
from mezmorize.utils import get_cache_type

from riko.base._config import ENCODING, STREAMING_THRESHOLD, settings
from riko.base._paths import is_http_url, normalize_url
from riko.base._sentinels import MISSING, is_missing_type
from riko.coercion._canonical import repr_cache
from riko.types._io import resolve_user_agent

from ._reencode import TextReencoder

if TYPE_CHECKING:
    from codecs import StreamReader
    from collections.abc import Generator, Iterable, Iterator, Mapping
    from http.client import HTTPResponse
    from urllib.response import addinfourl

    from _typeshed import WriteableBuffer
    from urllib3.response import HTTPResponse as URLLib3Response

    from riko.types._enums import UserAgentLike
    from riko.types._scalars import AnyStr
    from riko.types._streams import Stream
    from riko.types._values import BasicArg

    from ._filelike import (
        BinaryFileLike,
        BinaryIOLike,
        FileLike,
        Opener,
        StringFileLike,
    )


def ext_from_content_type(content_type: str | None) -> str | None:
    """
    Maps a content type to its file extension.

    Args:

        content_type: The response content type, if the source reported one.

    Returns:

        ``"xml"``/``"json"`` for the feed types, otherwise the content subtype,
        or ``None`` when no content type is available.

    Examples:

        >>> ext_from_content_type("application/rss+xml; charset=utf-8")
        'xml'
        >>> ext_from_content_type("application/vnd.api+json")
        'json'
        >>> ext_from_content_type("text/html")
        'html'
        >>> ext_from_content_type(None)

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


def get_response_content_type(
    r: HTTPResponse | addinfourl | requests.Response,
) -> str | None:
    """
    Reads the response's ``Content-Type`` header.

    Args:

        r: The HTTP response to inspect.

    Returns:

        The lowercased content type, or ``None`` when the header is absent.

    Examples:

        >>> from types import SimpleNamespace
        >>>
        >>> r = SimpleNamespace(headers={"Content-Type": "Application/JSON"})
        >>> get_response_content_type(r)
        'application/json'

    """
    content_type = r.headers.get("Content-Type")
    return None if content_type is None else content_type.lower()


def get_response_encoding(
    r: HTTPResponse | addinfourl, def_encoding: str = ENCODING
) -> str:
    """
    Gets the response's declared charset, or ``def_encoding`` when it declares none.

    Args:

        r: The HTTP response to inspect.

    Kwargs:

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

    if content_type is not None and "charset=" in content_type:
        ctype = content_type.split("charset=")[1]
        encoding = ctype.strip().strip('"').strip("'")
    else:
        encoding = None

    return encoding or def_encoding


# https://docs.python.org/3.3/reference/expressions.html#examples
def auto_close[T](stream: Iterable[T], *files: FileLike | None) -> Iterator[T]:
    """
    Passes ``stream`` through so it closes ``files`` when iteration ends.

    Unconditionally closes the file backing a fetched stream so that each file is
    released on exhaustion, an early ``break``, or an exception. This is the tool for
    handles whose consumption is deferred. I.e., a parser that returns a lazy iterator
    after opening a file keeps the file alive until the caller drains it. Whereas a
    ``with``/``async with`` block would close it before the first item is read. Pass
    multiple files when a ``seekable`` copy is read but the original fetch must still be
    released. Closing an already closed file is a harmless no-op.

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
            if f is not None:
                f.close()


def gen_rows(rows: Stream) -> Stream:
    """
    Generates the rows of a table read by meza, or none when the source is empty.

    meza's csv reader raises ``RuntimeError`` on an empty source instead of
    yielding nothing; that error is dropped before the first row.

    Args:

        rows: The rows read from the table source.

    Yields:

        Each row, in order.

    Examples:

        >>> from io import StringIO
        >>> from meza.io import read_csv
        >>>
        >>> list(gen_rows(read_csv(StringIO("a\\n1\\n"))))
        [{'a': '1'}]
        >>> list(gen_rows(read_csv(StringIO(""))))
        []

    """
    first = MISSING

    try:
        first = next(rows, MISSING)
    except RuntimeError as err:
        if not isinstance(err.__cause__, StopIteration):
            raise

    if not is_missing_type(first):
        yield first
        yield from rows


@overload
def buffer(
    f: StringFileLike, binary: bool = ..., encoding: str = ...
) -> SpooledTemporaryFile[str]: ...
@overload
def buffer(
    f: BinaryFileLike, binary: bool = ..., encoding: str = ...
) -> SpooledTemporaryFile[bytes]: ...
@overload
def buffer(
    f: BinaryFileLike, binary: bool = ..., *, encoding: str
) -> SpooledTemporaryFile[str]: ...
@overload
def buffer(
    f: FileLike, binary: bool | None = ..., encoding: str | None = ...
) -> SpooledTemporaryFile[bytes] | SpooledTemporaryFile[str]: ...
def buffer(
    f: FileLike, binary: bool | None = None, encoding: str | None = None
) -> SpooledTemporaryFile[bytes] | SpooledTemporaryFile[str]:
    """
    Buffers ``f`` into a re-readable copy.

    The spool stays in memory until it exceeds the streaming threshold, then spills to
    disk. Byte streams are decoded when ``encoding`` is set. ``binary`` is auto-detected
    from the first chunk when not supplied.

    Args:

        f: The forward-only stream to copy.

    Kwargs:

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
        spool.write(cast("bytes", first).decode(encoding) if decode else first)

    for chunk in chunks:
        spool.write(cast("bytes", chunk).decode(encoding) if decode else chunk)

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

    Kwargs:

        binary: Whether the chunks are bytes. Auto-detected when omitted.
        encoding: Encoding used to decode byte chunks while buffering.

    Returns:

        ``f`` itself when it rewound, otherwise a rewound spooled copy.

    Examples:

        >>> from io import StringIO
        >>>
        >>> f = StringIO("abc")
        >>> f.read()
        'abc'
        >>> seekable(f).read()
        'abc'

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


class ReplayReader(RawIOBase):
    """
    Reads a binary stream once, and then replays it from where reading started.

    A seekable source seeks back. A forward-only source (e.g., an HTTP response body)
    is spooled as it is read, so the copy holds only what was read before
    :meth:`replay`, and spills to disk past the streaming threshold. Closing the
    reader closes the copy, not ``source``.

    Examples:

        >>> from io import BytesIO
        >>>
        >>> with ReplayReader(BytesIO(b"abcdef")) as reader:
        ...     reader.read(2)
        ...     reader.replay()
        ...     reader.read()
        b'ab'
        b'abcdef'

    """

    def __init__(self, source: BinaryIOLike) -> None:
        super().__init__()
        self.source = source
        self.start = source.tell() if source.seekable() else None

        if self.start is None:
            self.spool = SpooledTemporaryFile(  # noqa: SIM115
                max_size=STREAMING_THRESHOLD, mode="w+b"
            )
        else:
            self.spool = None

        self.replaying = False

    def readable(self) -> bool:
        return True

    def readinto(self, b: WriteableBuffer) -> int:
        view = memoryview(b).cast("B")
        size = len(view)

        if self.spool is None:
            data = self.source.read(size) or b""
        elif self.replaying:
            data = self.spool.read(size) or self.source.read(size) or b""
        else:
            data = self.source.read(size) or b""
            self.spool.write(data)

        view[: len(data)] = data
        return len(data)

    def replay(self) -> None:
        """Rewinds to where reading started."""
        if self.spool is None:
            self.source.seek(0 if self.start is None else self.start)
        else:
            self.spool.seek(0)
            self.replaying = True

    def close(self) -> None:
        if self.spool is not None:
            self.spool.close()

        super().close()


@overload
def opener(
    url: str,
    memoize: Literal[True],
    encoding: str = ...,
    params: Mapping[str, AnyStr | int | float] | None = ...,
    offline: bool = ...,
    *,
    binary: Literal[True],
    timeout: float | None = settings.fetch_timeout,
    user_agent: UserAgentLike | None = None,
    **_: object,
) -> tuple[BytesIO, str | None]: ...
@overload
def opener(
    url: str,
    memoize: Literal[False] = ...,
    encoding: str = ...,
    params: Mapping[str, AnyStr | int | float] | None = ...,
    offline: bool = ...,
    *,
    binary: Literal[True],
    timeout: float | None = settings.fetch_timeout,
    user_agent: UserAgentLike | None = None,
    **_: object,
) -> tuple[addinfourl | URLLib3Response, str | None]: ...
@overload
def opener(
    url: str,
    memoize: Literal[True],
    encoding: str = ...,
    params: Mapping[str, AnyStr | int | float] | None = ...,
    offline: bool = ...,
    binary: Literal[False] = ...,
    timeout: float | None = settings.fetch_timeout,
    *,
    user_agent: UserAgentLike | None = None,
    **_: object,
) -> tuple[StringIO, str | None]: ...
@overload
def opener(
    url: str,
    memoize: Literal[False] = ...,
    encoding: str = ...,
    params: Mapping[str, AnyStr | int | float] | None = ...,
    offline: bool = ...,
    binary: Literal[False] = ...,
    timeout: float | None = settings.fetch_timeout,
    *,
    user_agent: UserAgentLike | None = None,
    **_: object,
) -> tuple[StreamReader, str | None]: ...
def opener(
    url: str,
    memoize: bool = False,
    encoding: str = ENCODING,
    params: Mapping[str, AnyStr | int | float] | None = None,
    offline: bool = True,
    binary: bool = False,
    timeout: float | None = settings.fetch_timeout,
    *,
    user_agent: UserAgentLike | None = None,
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

    Kwargs:

        memoize: Whether to buffer the body for re-reading.
        encoding: Encoding used to decode byte streams.
        params: Query parameters for http requests.
        offline: Whether to treat a schemeless path as a local file (not an http host).
        binary: Whether to return bytes rather than decoded text.

        timeout: Per-request timeout in seconds (default: ``RIKO_FETCH_TIMEOUT``, 30
            seconds). ``None``, ``0``, or ``inf`` waits forever.

        user_agent: The HTTP ``User-Agent`` to send. A ``UserAgent`` member selects an
            agent of that kind (default: "riko/<version>").

    Returns:

        A ``(stream, content_type)`` pair. ``content_type`` is ``None`` when the
        source reports none.

    Raises:

        TypeError: If ``url`` is empty.

    """
    if not url:
        raise TypeError("a url is required")

    params = params or {}
    url = normalize_url(url, offline=offline)
    timeout = None if (not timeout) or isinf(timeout) else timeout
    headers = {"User-Agent": resolve_user_agent(user_agent)}

    with ExitStack() as stack:
        if is_http_url(url):
            r = requests.get(
                url, params=params, headers=headers, stream=not memoize, timeout=timeout
            )
            stack.callback(r.close)
            r.raise_for_status()
            r.raw.decode_content = True

            if binary and memoize:
                response = BytesIO(r.content)
            elif binary:
                response = r.raw
            elif memoize:
                response = StringIO(r.text)
            else:
                encoding = r.encoding or encoding
                response = TextReencoder(r.raw, encoding, owner=r)
        else:
            req = Request(url, headers=headers)  # noqa: S310
            r = urlopen(req, timeout=timeout)  # noqa: S310
            stack.callback(r.close)

            if binary and memoize:
                response = buffer(r, binary=True)
            elif binary:
                response = r
            elif memoize:
                encoding = get_response_encoding(r, encoding or ENCODING)
                response = buffer(r, encoding=encoding)
            else:
                encoding = get_response_encoding(r, encoding or ENCODING)
                response = TextReencoder(r.fp, encoding, owner=r)

        if not memoize:
            stack.pop_all()

    return (response, get_response_content_type(r))


@repr_cache
def build_opener(
    memoize: bool = False, *, user_agent: UserAgentLike | None = None, **kwargs: object
) -> Opener:
    """
    Builds a URL opener cached by call arguments.

    Kwargs:

        memoize: Whether the returned opener buffers responses for re-reading.
        user_agent: The HTTP ``User-Agent`` each request resolves and sends.

    Returns:

        An opener callable; identical arguments return the cached opener.

    Examples:

        >>> build_opener.cache_clear()
        >>> o1 = build_opener()
        >>> o1 is build_opener()
        True
        >>> o1 is build_opener(encoding="utf-8")
        False
        >>> build_opener.cache_info().hits
        1
        >>> o2 = build_opener(memoize=True)
        >>> o2 is build_opener(memoize=True)
        True
        >>> build_opener.cache_info().hits
        2

    """
    wrapper = partial(opener, memoize=memoize, user_agent=user_agent, **kwargs)
    current_opener = wraps(opener)(wrapper)

    if memoize:
        kwargs.setdefault("cache_type", get_cache_type(spread=False))
        current_opener = mezmorize.memoize(**kwargs)(current_opener)

    return current_opener


def get_temp_file() -> IO[bytes]:
    """
    Gets a named binary temporary file that is removed when its context exits.

    The file stays on disk inside the ``with`` block.

    Returns:

        The open temporary file.

    Examples:

        >>> with get_temp_file() as fp:
        ...     Path(fp.name).exists()
        True

    """
    return NamedTemporaryFile(delete=True, delete_on_close=False)


@contextmanager
def get_temp_path(filename: str = "tmp", *, delete: bool = True) -> Generator[Path]:
    """
    Gets a temporary path, in a fresh directory, that no file occupies yet.

    The path and its directory are removed when the context exits.

    Kwargs:

        filename: The path's file name, e.g. ``"items.csv"`` (default: "tmp").
        delete: Whether the context's exit removes the path (default: True).

    Yields:

        The unoccupied temporary path.

    Examples:

        >>> with get_temp_path("report.csv") as temp_path:
        ...     print(temp_path.name, temp_path.exists())
        ...     _ = temp_path.write_text("x\\n1\\n")
        report.csv False
        >>> temp_path.exists()
        False

    """
    with TemporaryDirectory(delete=delete) as tmpdir:
        yield Path(tmpdir, filename)


class Fetch[B: (Literal[True], Literal[False])]:
    """
    Opens a url or file as an iterable byte or text stream.

    A source that cannot be opened raises its error (e.g., a ``URLError`` wrapping a
    missing file, or a ``requests`` error), as the asynchronous opener does.

    Args:

        url: The resource to open.

    Kwargs:

        memoize: Whether to buffer the body so it can be re-read.
        binary: Whether to expose bytes rather than decoded text.

        user_agent: The HTTP ``User-Agent`` to send. A ``UserAgent`` member selects an
            agent of that kind (default: "riko/<version>").

    Raises:

        TypeError: If ``url`` is empty.

    """

    binary: B
    file: FileLike | None
    content_type: str | None

    @overload
    def __init__(
        self: Fetch[Literal[True]],
        url: str,
        *,
        binary: Literal[True],
        user_agent: UserAgentLike | None = None,
        **kwargs: BasicArg | float,
    ) -> None: ...
    @overload
    def __init__(
        self: Fetch[Literal[False]],
        url: str,
        *,
        binary: Literal[False] = ...,
        user_agent: UserAgentLike | None = None,
        **kwargs: BasicArg | float,
    ) -> None: ...
    def __init__(
        self,
        url: str,
        *,
        memoize: BasicArg | float = False,
        binary: bool = False,
        user_agent: UserAgentLike | None = None,
        **kwargs: BasicArg | float,
    ) -> None:
        # TODO: need to use separate timeouts for memoize and urlopen
        self.binary = binary  # pyright: ignore[reportAttributeAccessIssue]
        self.file = None
        opener = build_opener(
            memoize=bool(memoize), user_agent=user_agent, binary=binary, **kwargs
        )
        self.file, self.content_type = opener(url)

    def __getattr__(self, name: str) -> object:
        if self.file is not None:
            return getattr(self.file, name)

        raise AttributeError(name)

    def close(self) -> None:
        if self.file:
            self.file.close()
            self.file = None

    def __enter__(self) -> Fetch[B]:
        return self

    def __exit__(self, *_: object) -> None:
        self.close()

    @overload
    def __iter__(self: Fetch[Literal[True]]) -> Iterator[bytes]: ...
    @overload
    def __iter__(self: Fetch[Literal[False]]) -> Iterator[str]: ...
    def __iter__(self) -> Iterator[bytes | str]:
        if self.file:
            result = iter(self.file)
        elif self.binary:
            result = iter([b""])
        else:
            result = iter([""])

        return result

    @overload
    def __next__(self: Fetch[Literal[True]]) -> bytes: ...
    @overload
    def __next__(self: Fetch[Literal[False]]) -> str: ...
    def __next__(self) -> bytes | str:
        if self.file:
            return next(self.file)

        raise StopIteration

    @overload
    def read(self: Fetch[Literal[True]], size: int = ...) -> bytes: ...
    @overload
    def read(self: Fetch[Literal[False]], size: int = ...) -> str: ...
    def read(self, size: int = -1) -> bytes | str:
        if self.file:
            result = self.file.read(size)
        else:
            result = b"" if self.binary else ""

        return result

    @property
    def ext(self) -> str | None:
        """The file extension implied by the response content type."""
        return ext_from_content_type(self.content_type)
