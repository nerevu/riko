"""
File-like and opener typing contracts for riko's sync and async I/O.

A file-like value is an in-memory buffer, a raw or text stream, a spooled temporary
file, or a fetched response that reads as bytes (``BinaryFileLike``) or text
(``StringFileLike``). An opener maps a URL to a file-like value and its detected
encoding.
"""

from __future__ import annotations

from codecs import StreamReader
from collections.abc import Callable
from io import BufferedIOBase, BytesIO, RawIOBase, StringIO, TextIOBase
from tempfile import SpooledTemporaryFile
from typing import TYPE_CHECKING, Literal

if TYPE_CHECKING:
    from ._async import NamedTextIOWrapper
    from ._sync import Fetch


type IOFileLike = BufferedIOBase | TextIOBase
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
