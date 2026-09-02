from __future__ import annotations

from codecs import StreamReader
from collections.abc import Callable
from io import BytesIO, RawIOBase, StringIO, TextIOBase
from tempfile import SpooledTemporaryFile
from typing import TYPE_CHECKING, Literal

if TYPE_CHECKING:
    from riko._io import Fetch
    from riko.bado.io import NamedTextIOWrapper

type IOFileLike = BytesIO | StringIO
type BinaryFileLike = (
    BytesIO | RawIOBase | Fetch[Literal[True]] | SpooledTemporaryFile[bytes]
)
type StringFileLike = (
    Fetch[Literal[False]]
    | NamedTextIOWrapper
    | SpooledTemporaryFile[str]
    | StreamReader
    | StringIO
    | TextIOBase
)
type FileLike = BinaryFileLike | StringFileLike
type Opener = Callable[[str], tuple[FileLike, str | None]]

IOFileLikeType: tuple[type, ...] = (BytesIO, StringIO)
