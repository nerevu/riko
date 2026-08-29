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

from itertools import islice
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
        def close(self) -> None: ...  # noqa: E704
else:

    class Reencoder(_Reencoder):
        """Reencoder whose ``read`` honors ``n`` and closes its source/owner."""

        def __init__(self, f, *args, owner=None, **kwargs):
            self._f = f if owner is None else owner
            super().__init__(f, *args, **kwargs)

        def read(self, n=None):
            if n is None or n < 0:
                stream = self.stream
            else:
                stream = islice(self.stream, n)

            return self.join_char.join(stream)

        def close(self):
            self._f.close()


def reencode(f, fromenc=ENCODING, toenc=ENCODING, *, owner=None, **kwargs):
    return Reencoder(f, fromenc, toenc, owner=owner, **kwargs)
