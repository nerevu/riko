# vim: sw=4:ts=4:expandtab
"""Provides byte/text re-encoding with file-like read and close semantics."""

from __future__ import annotations

import re
from abc import ABC, abstractmethod
from codecs import iterdecode, iterencode
from itertools import chain
from os import linesep
from typing import TYPE_CHECKING, cast, overload

from meza import BOM
from meza.io import IterStringIO as _IterStringIO
from meza.io import Reencoder as _Reencoder

from riko.base._config import ENCODING

if TYPE_CHECKING:
    from collections.abc import Iterable, Iterator
    from typing import Literal, Self

    from riko.types._io import SyncCloseable

    from ._filelike import FileLike

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


def _decode(
    f: FileLike,
    fromenc: str,
    remove_BOM: bool,  # noqa: N803
) -> tuple[Iterator[str], bool]:
    first_line = next(f, None)

    if first_line is None:
        decoded: Iterator[str] = iter(())
        proper_newline = True
    else:
        chained = chain([first_line], f)

        if isinstance(first_line, bytes):
            decoded = iterdecode(cast("Iterator[bytes]", chained), fromenc)
            proper_newline = first_line.endswith(linesep.encode(fromenc))
        else:
            decoded = cast("Iterator[str]", chained)
            proper_newline = first_line.endswith(linesep)

        if remove_BOM:
            decoded = _strip_bom(decoded)

    return decoded, proper_newline


class IterStringIO(_IterStringIO):
    def __buffer__(self, flags: int) -> memoryview:
        """Exposes the internal memory buffer directly for passing into bytes()."""
        joined = b"".join(self.iter)
        return memoryview(joined)


class Reencoder[T: (str, bytes)](_Reencoder, ABC):
    """Reencoder whose ``read`` honors ``n`` and closes its source/owner."""

    join_char: T
    lineseps: T

    def __init__(
        self,
        f: FileLike,
        fromenc: str = ENCODING,
        toenc: str = ENCODING,
        *,
        owner: SyncCloseable | None = None,
        remove_BOM: bool = False,  # noqa: N803
    ) -> None:
        self._f = f if owner is None else owner
        self.fileno = f.fileno

        try:
            decoded, proper_newline = _decode(f, fromenc, remove_BOM)
        except BaseException:
            self._f.close()
            raise

        self._chunks = self._encode(decoded, toenc, proper_newline)
        self.stream = self._chunks
        self._buf = self.join_char

    @abstractmethod
    def _encode(
        self, decoded: Iterator[str], toenc: str, proper_newline: bool
    ) -> Iterator[T]:
        """Encodes the decoded lines into this reencoder's chunk type."""

    def join(self, parts: Iterable[T]) -> T:
        return self.join_char.join(parts)

    def __buffer__(self: Reencoder[bytes], flags: int) -> memoryview:
        """Exposes the internal memory buffer directly for passing into bytes()."""
        if not isinstance(self._buf, bytes):
            raise TypeError("Buffer not enabled for str Reencoder")

        return memoryview(self.read())

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
            head, self._buf = self._buf[:n], self._buf[n:]

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

    def readline(self, n: int | None = None, keepends: bool = True) -> T:
        if not (self._buf or self._fill()):
            line = self.join_char
        else:
            line = self._take(self._normalize_n(n))

        return line if keepends else line.rstrip(self.lineseps)

    def __iter__(self) -> Self:
        return self

    def __next__(self) -> T:
        if not (line := self.readline()):
            raise StopIteration

        return line

    def _readlines(self, keepends: bool = True) -> Iterator[T]:
        while self._buf or self._fill():
            yield self.readline(keepends=keepends)

    def readlines(  # pyright: ignore[reportIncompatibleMethodOverride]
        self, keepends: bool = True
    ) -> list[T]:
        return list(self._readlines(keepends=keepends))

    def close(self) -> None:
        self._f.close()


class BytesReencoder(Reencoder[bytes]):
    join_char = b""
    lineseps = b"\r\n"
    binary = True

    def _encode(
        self, decoded: Iterator[str], toenc: str, proper_newline: bool
    ) -> Iterator[bytes]:
        return iterencode(decoded, toenc)


class TextReencoder(Reencoder[str]):
    join_char = ""
    lineseps = "\r\n"
    binary = False

    def _encode(
        self, decoded: Iterator[str], toenc: str, proper_newline: bool
    ) -> Iterator[str]:
        return decoded if proper_newline else _gen_lines(decoded, linesep)


@overload
def reencode(
    f: FileLike,
    fromenc: str = ...,
    toenc: str = ...,
    *,
    owner: SyncCloseable | None = ...,
    decode: Literal[True],
    remove_BOM: bool = ...,  # noqa: N803
) -> Reencoder[str]: ...
@overload
def reencode(
    f: FileLike,
    fromenc: str = ...,
    toenc: str = ...,
    *,
    owner: SyncCloseable | None = ...,
    decode: Literal[False] = ...,
    remove_BOM: bool = ...,  # noqa: N803
) -> Reencoder[bytes]: ...
def reencode(
    f: FileLike,
    fromenc: str = ENCODING,
    toenc: str = ENCODING,
    *,
    owner: SyncCloseable | None = None,
    decode: bool = False,
    remove_BOM: bool = False,  # noqa: N803
) -> Reencoder[str] | Reencoder[bytes]:
    cls = TextReencoder if decode else BytesReencoder
    return cls(f, fromenc, toenc, owner=owner, remove_BOM=remove_BOM)
