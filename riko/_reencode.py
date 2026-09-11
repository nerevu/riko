# vim: sw=4:ts=4:expandtab
"""
riko._reencode
~~~~~~~~~~~~~~
A corrected ``Reencoder`` (over meza's ``Reencoder``) plus a ``reencode``
factory. This whole module is meant to be ported wholesale into meza, after
which riko drops it and imports ``reencode`` from ``meza.io`` again. It fixes:

* ``read`` — meza treats ``n`` as a *line* count and, via a falsy ``if n``
  guard, reads the entire stream when ``n == 0``, so a probing ``read(0)``
  (e.g. html5lib's) silently drains the source and every later read hits EOF.
  Here ``read`` honors ``n`` as documented (``0`` -> empty, negative/``None``
  -> read all).
* ``close`` — a ``StreamReader`` should close its underlying stream, but meza's
  ``Reencoder`` only closes the decoded generator. It now retains the source
  (``self._f``) and closes it. When the readable is a sub-stream of a larger
  resource (e.g. a requests ``raw`` or a urlopen ``fp``), pass the owning
  object as ``owner`` so ``close`` releases the whole resource.
"""

from __future__ import annotations

from codecs import iterdecode, iterencode
from collections.abc import Callable, Iterable, Iterator
from itertools import chain
from os import linesep
from typing import TYPE_CHECKING, cast

from meza.io import IterStringIO as _IterStringIO
from meza.io import Reencoder as _Reencoder
from meza.io import groupby_line

from riko._constants import ENCODING
from riko.types._scalars import AnyStr

if TYPE_CHECKING:
    from typing import Literal, overload

    from riko.types._io import FileLike, SyncCloseable


class PatchedReencoder(_Reencoder):
    def __init__[T: (str, bytes)](
        self, f: FileLike, fromenc=ENCODING, toenc=ENCODING, decode=False
    ):
        self.fileno = f.fileno
        first_line: T = cast(T, next(f))
        bytes_mode = isinstance(first_line, bytes)
        rencode = not decode
        chained = cast(Iterator[T], chain([first_line], f))

        if bytes_mode:
            decoded = iterdecode(cast(Iterator[bytes], chained), fromenc)
            self.binary = rencode
            proper_newline = first_line.endswith(linesep.encode(fromenc))
        else:
            decoded = cast(Iterator[str], chained)
            self.binary = bytes_mode or rencode
            proper_newline = first_line.endswith(linesep)

        stream = iterencode(decoded, toenc) if rencode else decoded

        if proper_newline:
            self.join_char = b"" if self.binary else ""
            _stream = stream
        else:
            groups = groupby_line(next(stream))

            if self.binary:
                self.join_char = linesep.encode(fromenc)
                _stream = (bytes(cast(int, g)) for k, g in groups if k)
            else:
                self.join_char = cast(str, linesep)
                _stream = (self.join_char.join(cast(str, g)) for k, g in groups if k)

        self.stream = _stream  # pyright: ignore [reportAttributeAccessIssue]


class IterStringIO(_IterStringIO):  # pyright: ignore[reportRedeclaration])
    def __buffer__(self, flags: int) -> memoryview:
        """
        Exposes the internal memory buffer directly for passing into bytes().
        """
        joined = b"".join(cast(Iterator[bytes], self.iter))
        return memoryview(cast(bytes, joined))


class Reencoder[T: AnyStr](PatchedReencoder):  # pyright: ignore[reportRedeclaration])
    """Reencoder whose ``read`` honors ``n`` and closes its source/owner."""

    def __init__(self, f, *args, owner=None, **kwargs):
        self._f = f if owner is None else owner
        super().__init__(f, *args, **kwargs)
        self._chunks = cast(Iterator[T], self.stream)
        self._join_char: T = cast(T, self.join_char)
        self._buf: T = self._join_char
        self.lineseps: T = cast(T, b"\r\n" if self.binary else "\r\n")

    def __buffer__(self, flags: int) -> memoryview:
        """
        Exposes the internal memory buffer directly for passing into bytes().
        """
        if not isinstance(self._buf, bytes):
            raise TypeError("Buffer not enabled for str Reencoder")

        joined = self.join(self._chunks)
        return memoryview(cast(bytes, joined))

    def join(self, parts: Iterable[T]) -> T:
        return cast(Callable[[Iterable[T]], T], self._join_char.join)(parts)

    def _parse_n(self, n: int | None = None) -> int | None:
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
            head, self._buf = self._buf, self._join_char
        else:
            head, self._buf = cast(T, self._buf[:n]), cast(T, self._buf[n:])

        return head

    def read(self, n: int | None = None) -> T:
        if (parsed_n := self._parse_n(n)) is None:
            result = self.join(chain((self._buf,), self._chunks))
            self._buf = self._join_char
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
            line = self._join_char
        else:
            line = self._take(self._parse_n(n))

        return line if keepends else cast(Callable[[T], T], line.rstrip)(self.lineseps)

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
