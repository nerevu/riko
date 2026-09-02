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

from itertools import chain
from typing import TYPE_CHECKING

from meza.io import Reencoder as _Reencoder

from riko._constants import ENCODING

if TYPE_CHECKING:
    from collections.abc import Iterator
    from typing import Protocol

    from riko.types._io import FileTypes

    class _Closeable(Protocol):
        def close(self) -> None: ...  # noqa: E704

    class Reencoder:
        _f: _Closeable
        binary: bool
        join_char: str | bytes
        stream: Iterator[str | bytes]

        def __init__(  # noqa: E704
            self,
            f: FileTypes,
            fromenc: str = ...,
            toenc: str = ...,
            *,
            owner: _Closeable | None = ...,
            decode: bool = ...,
            remove_BOM: bool = ...,  # noqa: N803
        ) -> None: ...
        def read(self, n: int | None = None) -> str | bytes: ...  # noqa: E704
        def readline(  # noqa: E301, E704
            self, n: int | None = None, keepends=True
        ) -> str | bytes: ...
        def readlines(self, keepends=True) -> list[str | bytes]: ...  # noqa: E704
        def close(self) -> None: ...  # noqa: E704
else:

    class Reencoder(_Reencoder):
        """Reencoder whose ``read`` honors ``n`` and closes its source/owner."""

        def __init__(self, f, *args, owner=None, **kwargs):
            self._f = f if owner is None else owner
            super().__init__(f, *args, **kwargs)
            self._chunks = iter(self.stream)
            self._buf = self.join_char
            self.lineseps = b"\r\n" if self.binary else "\r\n"

        def _parse_n(self, n):
            """Parse ``n`` into a non-negative int or None."""
            return None if n is None or n < 0 else max(0, int(n))

        def _fill(self):
            """Load the next non-empty chunk into the buffer. False at EOF."""
            for chunk in self._chunks:
                if chunk:
                    self._buf, result = chunk, True
                    break
            else:
                result = False

            return result

        def _take(self, n):
            """Pop up to ``n`` items off the buffer, or all of it when ``n`` is None."""
            if n is None:
                head, self._buf = self._buf, self.join_char
            else:
                head, self._buf = self._buf[:n], self._buf[n:]

            return head

        def read(self, n=None):
            if (parsed_n := self._parse_n(n)) is None:
                result = self.join_char.join(chain((self._buf,), self._chunks))
                self._buf = self.join_char
            else:
                parts, remaining = [], parsed_n

                while remaining and (self._buf or self._fill()):
                    parts.append(part := self._take(remaining))
                    remaining -= len(part)

                result = self.join_char.join(parts)

            return result

        def readline(self, n=None, keepends=True):
            if not (self._buf or self._fill()):
                line = self.join_char
            else:
                line = self._take(self._parse_n(n))

            return line if keepends else line.rstrip(self.lineseps)

        def _readlines(self, keepends=True):
            while self._buf or self._fill():
                yield self.readline(keepends=keepends)

        def readlines(self, keepends=True):
            return list(self._readlines(keepends=keepends))

        def close(self):
            self._f.close()


def reencode(f, fromenc=ENCODING, toenc=ENCODING, *, owner=None, **kwargs):
    return Reencoder(f, fromenc, toenc, owner=owner, **kwargs)
