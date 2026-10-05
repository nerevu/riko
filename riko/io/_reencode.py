# vim: sw=4:ts=4:expandtab
"""Provides byte/text re-encoding with file-like read and close semantics."""

from __future__ import annotations

import re
from codecs import iterdecode, iterencode
from itertools import chain
from os import linesep
from typing import TYPE_CHECKING, cast

from meza import BOM
from meza.io import IterStringIO as _IterStringIO
from meza.io import Reencoder as _Reencoder

from riko.base._constants import ENCODING
from riko.types._scalars import AnyStr

if TYPE_CHECKING:
    from collections.abc import Callable, Iterable, Iterator
    from typing import Literal, overload

    from riko.types._io import FileLike, SyncCloseable

LINE_BREAKS = re.compile(r"\r\n|\r|\n")


def _terminate_lines[S: (str, bytes)](lines: list[S], newline: S) -> Iterator[S]:
    """Appends ``newline`` to every line except the last."""
    return chain((line + newline for line in lines[:-1]), filter(len, lines[-1:]))


def _strip_bom(chunks: Iterable[str]) -> Iterator[str]:
    """Drops a byte order mark from the start of the decoded text."""
    started = False

    for chunk in chunks:
        yield chunk if started else chunk.removeprefix(BOM)
        started = started or bool(chunk)


def _gen_lines(chunks: Iterable[str], newline: str) -> Iterator[str]:
    """Re-splits decoded text chunks into lines ending in ``newline``."""
    pending = ""

    for chunk in chunks:
        text = pending + chunk
        held = "\r" if text.endswith("\r") else ""
        *lines, tail = LINE_BREAKS.split(text[: len(text) - len(held)])
        yield from (line + newline for line in lines)
        pending = tail + held

    yield from _terminate_lines(LINE_BREAKS.split(pending), newline)


class PatchedReencoder[T: AnyStr](_Reencoder):
    join_char: T

    def __init__[L: (str, bytes)](
        self,
        f: FileLike,
        fromenc=ENCODING,
        toenc=ENCODING,
        decode=False,
        remove_BOM=False,  # noqa: N803
    ):
        self.fileno = f.fileno
        self.binary = not decode
        first_line: L | None = cast("L | None", next(f, None))

        if first_line is None:
            _stream: Iterator[str] | Iterator[bytes] = iter(())
        else:
            chained = cast("Iterator[L]", chain([first_line], f))

            if isinstance(first_line, bytes):
                decoded = iterdecode(cast("Iterator[bytes]", chained), fromenc)
                proper_newline = first_line.endswith(linesep.encode(fromenc))
            else:
                decoded = cast("Iterator[str]", chained)
                proper_newline = first_line.endswith(linesep)

            if remove_BOM:
                decoded = _strip_bom(decoded)

            if self.binary:
                _stream = iterencode(decoded, toenc)
            elif proper_newline:
                _stream = decoded
            else:
                _stream = _gen_lines(decoded, linesep)

        self.join_char = cast("T", b"" if self.binary else "")
        self.stream = _stream  # pyright: ignore [reportAttributeAccessIssue]


class IterStringIO(_IterStringIO):  # pyright: ignore[reportRedeclaration])
    def __buffer__(self, flags: int) -> memoryview:
        """Exposes the internal memory buffer directly for passing into bytes()."""
        joined = b"".join(cast("Iterator[bytes]", self.iter))
        return memoryview(joined)


class Reencoder[T: AnyStr](PatchedReencoder[T]):  # pyright: ignore[reportRedeclaration])
    """Reencoder whose ``read`` honors ``n`` and closes its source/owner."""

    def __init__(self, f, *args, owner=None, **kwargs):
        self._f = f if owner is None else owner

        try:
            super().__init__(f, *args, **kwargs)
        except BaseException:
            self._f.close()
            raise

        self._chunks = cast("Iterator[T]", self.stream)
        self._buf: T = self.join_char
        self.lineseps: T = cast("T", b"\r\n" if self.binary else "\r\n")

    def join(self, parts: Iterable[T]) -> T:
        return cast("Callable[[Iterable[T]], T]", self.join_char.join)(parts)

    def __buffer__(self, flags: int) -> memoryview:
        """Exposes the internal memory buffer directly for passing into bytes()."""
        if not isinstance(self._buf, bytes):
            raise TypeError("Buffer not enabled for str Reencoder")

        joined = self.join(self._chunks)
        return memoryview(cast("bytes", joined))

    def _normalize_n(self, n: int | None = None) -> int | None:
        """Parse ``n`` into a non-negative int or None."""
        return None if n is None or n < 0 else max(0, int(n))

    def _fill(self) -> bool:
        """Load the next non-empty chunk into the buffer. False at EOF."""
        for chunk in self._chunks:
            if chunk:
                self._buf, result = chunk, True
                break
        else:
            result = False

        return result

    def _take(self, n: int | None = None) -> T:
        """Pop up to ``n`` items off the buffer, or all of it when ``n`` is None."""
        if n is None:
            head, self._buf = self._buf, self.join_char
        else:
            head, self._buf = cast("T", self._buf[:n]), cast("T", self._buf[n:])

        return head

    def read(self, n: int | None = None) -> T:
        if (parsed_n := self._normalize_n(n)) is None:
            rest = self._chunks
            result = self.join(chain((self._buf,), rest) if self._buf else rest)
            self._buf = self.join_char
        else:
            parts: list[T] = []
            remaining = parsed_n

            while remaining and (self._buf or self._fill()):
                parts.append(part := self._take(remaining))
                remaining -= len(part)

            result = self.join(parts)

        return result

    def readline(self, n=None, keepends=True) -> T:
        if not (self._buf or self._fill()):
            line = self.join_char
        else:
            line = self._take(self._normalize_n(n))

        return (
            line if keepends else cast("Callable[[T], T]", line.rstrip)(self.lineseps)
        )

    def _readlines(self, keepends=True) -> Iterator[T]:
        while self._buf or self._fill():
            yield self.readline(keepends=keepends)

    def readlines(  # pyright: ignore[reportIncompatibleMethodOverride])
        self, keepends=True
    ) -> list[T]:
        return list(self._readlines(keepends=keepends))

    def close(self):
        self._f.close()


def reencode(  # pyright: ignore[reportRedeclaration])
    f, fromenc=ENCODING, toenc=ENCODING, *, owner=None, **kwargs
):
    return Reencoder(f, fromenc, toenc, owner=owner, **kwargs)


if TYPE_CHECKING:

    class IterStringIO[T: AnyStr]:  # noqa: F811
        def __init__(
            self,
            iterable: Iterable[str] | None = None,
            bufsize: int = 4096,
            decode: bool = False,
            **kwargs,
        ) -> None: ...
        def __buffer__(self, flags: int) -> memoryview: ...  # noqa: E704
        def read(self, n: int | None = None) -> T: ...  # noqa: E704
        def readline(  # noqa: E301, E704
            self, n: int | None = None, keepends=True
        ) -> T: ...
        def readlines(self, keepends=True) -> list[T]: ...  # noqa: E704

    class Reencoder[T: AnyStr]:  # noqa: F811
        _f: SyncCloseable
        binary: bool
        join_char: T
        stream: Iterator[T]

        def __init__(  # noqa: E704
            self,
            f: FileLike,
            fromenc: str = ...,
            toenc: str = ...,
            *,
            owner: SyncCloseable | None = ...,
            decode: bool = ...,
            remove_BOM: bool = ...,  # noqa: N803
        ) -> None: ...
        def __buffer__(self, flags: int) -> memoryview: ...  # noqa: E704
        def __iter__(self) -> Iterator[T]: ...  # noqa: E704
        def __next__(self) -> T: ...  # noqa: E704
        def read(self, n: int | None = None) -> T: ...  # noqa: E704
        def readline(  # noqa: E301, E704
            self, n: int | None = None, keepends=True
        ) -> T: ...
        def readlines(self, keepends=True) -> list[T]: ...  # noqa: E704
        def close(self) -> None: ...  # noqa: E704

    @overload
    def reencode(  # noqa: E704, F811
        f: FileLike,
        fromenc: str = ...,
        toenc: str = ...,
        *,
        owner: SyncCloseable | None = ...,
        decode: Literal[True],
        remove_BOM: bool = ...,  # noqa: N803
    ) -> Reencoder[str]: ...
    @overload  # noqa: E301
    def reencode(  # noqa: E704
        f: FileLike,
        fromenc: str = ...,
        toenc: str = ...,
        *,
        owner: SyncCloseable | None = ...,
        decode: Literal[False] = ...,
        remove_BOM: bool = ...,  # noqa: N803
    ) -> Reencoder[bytes]: ...
