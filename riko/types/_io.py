from __future__ import annotations

from codecs import StreamReader
from collections.abc import Callable
from io import BytesIO, RawIOBase, StringIO, TextIOBase
from tempfile import SpooledTemporaryFile
from typing import TYPE_CHECKING, Literal

if TYPE_CHECKING:
    from riko._io import Fetch
    from riko.bado.io import NamedTextIOWrapper

# Opener = Callable[[str], tuple[Optional[str | Reencoder], Optional[str]]]
# TODO: add type hint overloads to Reencoder with decode=True -> str
type BinaryFileTypes = (
    BytesIO | RawIOBase | Fetch[Literal[True]] | SpooledTemporaryFile[bytes]
)
type StringFileTypes = (
    Fetch[Literal[False]]
    | NamedTextIOWrapper
    | SpooledTemporaryFile[str]
    | StreamReader
    | StringIO
    | TextIOBase
)
type FileTypes = BinaryFileTypes | StringFileTypes

type Opener = Callable[[str], tuple[FileTypes, str | None]]
