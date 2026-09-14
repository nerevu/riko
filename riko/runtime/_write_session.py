from __future__ import annotations

from collections.abc import AsyncGenerator, Callable, Generator
from contextlib import asynccontextmanager, contextmanager
from enum import Enum, auto
from io import StringIO
from pathlib import Path
from typing import TYPE_CHECKING, BinaryIO

from riko.bado import _backend
from riko.bado._backend import async_open, asyncify
from riko.bado.itertools import as_async
from riko.base._constants import ENCODING
from riko.definitions._targets import File, prepare_write
from riko.definitions._write import (
    AsyncWriteSession,
    Destination,
    PreparedWrite,
    SyncWriteSession,
    WriteMode,
    WriteResult,
)
from riko.io._reencode import IterStringIO, Reencoder, reencode
from riko.io._serialization import convert_records
from riko.types._enums import FmtLike, Formats, KeyLike
from riko.types._guards import is_mapping
from riko.types._streams import AsyncItems, Item, Items, Stream
from riko.types._wrappers import ConversionOutput

from ._resources import OneShotResource, Resource

if TYPE_CHECKING:
    from _typeshed import OpenBinaryMode
    from anyio import AsyncFile


class _SessionState(Enum):
    """The lifecycle state of a write session."""

    OPEN = auto()
    FINALIZED = auto()
    ABORTED = auto()
    CLOSED = auto()


class _InputShape(Enum):
    """How a session's records arrive: repeated singletons or one whole stream."""

    ITEM = auto()
    STREAM = auto()


def _as_text(content: str | ConversionOutput) -> str:
    """Coalesces converter output (a string, ``StringIO``, or chunks) into text."""
    if isinstance(content, StringIO):
        text = content.getvalue()
    elif isinstance(content, str):
        text = content
    else:
        text = "".join(content)

    return text


def _as_bytes(
    content: str | ConversionOutput,
) -> IterStringIO | Reencoder[bytes] | bytes:
    if isinstance(content, StringIO):
        text = reencode(content, toenc=ENCODING)
    elif isinstance(content, str):
        text = content.encode(ENCODING)
    else:
        text = IterStringIO(content)

    return text


def _normalize_jsonl(content: str) -> str:
    """Ensures newline-delimited JSON ends in exactly one line terminator."""
    return f"{content}\n" if content and not content.endswith("\n") else content


class _FileWriteSession:
    def __init__(self, prepared: PreparedWrite):
        if not isinstance(prepared.target, File):
            raise TypeError("_FileWriteSession requires a File target")

        self._buffer: list[Item] = []
        self._incremental: bool = prepared.capabilities.incremental
        self._result: WriteResult = WriteResult()
        self._state: _SessionState = _SessionState.OPEN
        self._written: int = 0
        self.fmt: Formats = prepared.fmt or Formats.JSON
        self.mode: WriteMode = prepared.operation.mode
        self.operation = prepared.operation
        self.target: File = prepared.target

        self.append_mode = self.mode is WriteMode.APPEND
        self.csv_format = self.fmt is Formats.CSV
        self.file_mode: OpenBinaryMode = "ab" if self.append_mode else "wb"
        self.jsonl_format = self.fmt is Formats.JSONL
        self.path = Path(self.target.url)

        self._fields: tuple[str, ...] | None = None
        self._initial_fize_size: int | None = None
        self._input_shape: _InputShape | None = None
        self._needs_newline: bool | None = None
        self._skip_header: bool | None = None
        self._staged: ConversionOutput | str | None = None

    @property
    def input_shape(self):
        return self._input_shape

    @input_shape.setter
    def input_shape(self, value: _InputShape):
        if self._input_shape is None:
            self._input_shape = value
        elif self._input_shape is not value:
            raise RuntimeError("cannot mix item and stream delivery")
        elif self._input_shape is _InputShape.STREAM:
            raise RuntimeError("cannot attempt multiple stream deliveries")

    def _require_open(self) -> None:
        if self._state is not _SessionState.OPEN:
            raise RuntimeError(f"write session is {self._state.name.lower()}")

    def _validate_items(self, items: Items) -> Stream:
        if self.csv_format:
            for item in items:
                if self._fields is None:
                    self._fields = tuple(item)
                else:
                    if extra := set(item).difference(self._fields):
                        msg = f"CSV record has unexpected fields: {sorted(extra)!r}"
                        raise ValueError(msg)

                yield {k: item.get(k) for k in self._fields}
        else:
            yield from items

    def abort(self) -> None:
        if self._state is not _SessionState.ABORTED:
            self._require_open()
            self._buffer.clear()
            self._staged = None
            self._state = _SessionState.ABORTED


class _SyncFileWriteSession(_FileWriteSession):
    r"""
    A live, execution-owned file write session.

    Acquires the destination once, receives records (``Item``/``Items``) via
    :meth:`write`, then commits with :meth:`finalize` or abandons with :meth:`abort`
    before :meth:`teardown` releases the file. An incremental format (csv/jsonl) emits
    each converted chunk as it arrives. A framed format (json/geojson/…) stages the
    logical document and publishes it once at finalize.

    Attributes:

        target: The resolved file target.
        operation: The normalized, validated write intent.
        mode: ``append`` or ``replace``.
        fmt: The resolved serialization format.

    Examples:

        >>> from riko import get_temp_file
        >>> from riko.definitions._targets import prepare_write
        >>>
        >>> with get_temp_file() as fp:
        ...     prepared = prepare_write(fp.name, fmt="jsonl")
        ...     session = _SyncFileWriteSession(prepared)
        ...     session.acquire()
        ...     session.write([{"x": 0}, {"x": 1}])
        ...     _ = session.finalize()
        ...     session.teardown()
        ...
        ...     with open(fp.name, mode="rb") as f:
        ...         f.read()
        b'{"x": 0}\n{"x": 1}\n'

    """

    def __init__(self, prepared: PreparedWrite):
        super().__init__(prepared)
        self._handle: BinaryIO | None = None

    def ends_with_newline(self) -> bool:
        """Whether ``path``'s final byte is a newline, checked in binary."""
        try:
            with self.path.open("rb") as f:
                f.seek(-1, 2)
                result = f.read(1) == b"\n"
        except (FileNotFoundError, OSError):
            result = False

        return result

    @property
    def initial_fize_size(self) -> int:
        """Whether ``path`` exists and is non-empty."""
        if self._initial_fize_size is None:
            try:
                self._initial_fize_size = self.path.stat().st_size
            except FileNotFoundError:
                self._initial_fize_size = 0

        return self._initial_fize_size

    @property
    def needs_newline(self) -> bool:
        if self._needs_newline is None:
            if self.append_mode and self.initial_fize_size:
                self._needs_newline = not self.ends_with_newline()
            else:
                self._needs_newline = False
        elif self._needs_newline and self._written:
            self._needs_newline = False

        return self._needs_newline

    @property
    def skip_header(self) -> bool:
        if self._skip_header is None:
            self._skip_header = (self.initial_fize_size or self._written) > 0
        elif self._written and not self._skip_header:
            self._skip_header = True

        return self._skip_header

    def acquire(self) -> None:
        """
        Opens the destination once for an incremental format.

        A framed format defers all destination I/O to :meth:`finalize`. So if aborted,
        the session never mutates the file. An incremental append inspects the existing
        file's content and trailing newline once and tracks that state in memory rather
        than re-reading the destination.

        Examples:

            >>> from riko import get_temp_file
            >>> from riko.definitions._targets import prepare_write
            >>>
            >>> with get_temp_file() as fp:
            ...     prepare = prepare_write(fp.name, fmt="csv")
            ...     session = _SyncFileWriteSession(prepare)
            ...     session.acquire()
            ...     session.teardown()

        """
        if self._incremental:
            self._handle = self.path.open(self.file_mode)

    def _convert(self, items: Items, validate: bool = False) -> ConversionOutput | str:
        if validate:
            items = self._validate_items(items)

        kwargs = {"skip_header": self.skip_header} if self.csv_format else {}
        result = convert_records(items, self.fmt, **kwargs)

        if result and self.jsonl_format:
            result = _normalize_jsonl(_as_text(result))

        return result

    def _emit(self, content: ConversionOutput | str) -> None:
        if content and self._handle is not None:
            if self.needs_newline:
                self._written += self._handle.write(b"\n")

            self._written += self._handle.write(_as_bytes(content))

    def _write_items(self, items: Items) -> None:
        self.input_shape = _InputShape.STREAM
        content = self._convert(items)

        if self._incremental:
            self._emit(content)
        else:
            self._staged = content

    def _write_item(self, item: Item) -> None:
        self.input_shape = _InputShape.ITEM

        if self._incremental:
            content = self._convert([item], validate=True)
            self._emit(content)
        else:
            self._buffer.append(item)

    def write(self, value: Item | Items) -> None:
        r"""
        Delivers one record or the whole record stream.

        A mapping is one record (the temporary singleton path); anything else is the
        logical stream (the native converter path).

        Args:

            value: One record, or the record stream.

        Examples:

            >>> from riko import get_temp_file
            >>> from riko.definitions._targets import prepare_write
            >>>
            >>> with get_temp_file() as fp:
            ...     prepare = prepare_write(fp.name, fmt="jsonl")
            ...     session = _SyncFileWriteSession(prepare)
            ...     session.acquire()
            ...     session.write({"x": 0})
            ...     _ = session.finalize()
            ...     session.teardown()
            ...
            ...     with open(fp.name, mode="rb") as f:
            ...         f.read()
            b'{"x": 0}\n'

        """
        self._require_open()
        self._write_item(value) if is_mapping(value) else self._write_items(value)

    def _framed_content(self) -> ConversionOutput | str:
        if self._staged is not None:
            content = self._staged
        elif self._buffer:
            content = self._convert(self._buffer)
        else:
            content = ""

        return content

    def _commit(self) -> WriteResult:
        if not self._incremental:
            if content := self._framed_content():
                with Path(self.path).open("wb") as f:
                    self._written += f.write(_as_bytes(content))
        elif self._handle is not None:
            self._handle.flush()

        return WriteResult(written=self._written)

    def finalize(self) -> WriteResult:
        """
        Commits the delivery and reports the bytes written (idempotent).

        A framed document is published here — exactly once. Calling finalize again
        returns the same cached result rather than re-committing.

        Returns:

            A result carrying the number of bytes written.

        Examples:

            >>> from riko import get_temp_file
            >>> from riko.definitions._targets import prepare_write
            >>>
            >>> with get_temp_file() as fp:
            ...     session = _SyncFileWriteSession(prepare_write(fp.name))
            ...     session.acquire()
            ...     session.write([{"x": 1}])
            ...     result = session.finalize()
            ...     same = result is session.finalize()
            ...     session.teardown()
            ...     same
            True

        """
        if self._state is _SessionState.FINALIZED:
            result = self._result
        else:
            self._require_open()
            result = self._commit()
            self._result = result
            self._state = _SessionState.FINALIZED

        return result

    def teardown(self) -> None:
        """
        Releases the file handle; never commits (idempotent).

        Examples:

            >>> from riko import get_temp_file
            >>> from riko.definitions._targets import prepare_write
            >>>
            >>> with get_temp_file() as fp:
            ...     prepare = prepare_write(fp.name, fmt="csv")
            ...     session = _SyncFileWriteSession(prepare)
            ...     session.acquire()
            ...     session.teardown()

        """
        if self._state is not _SessionState.CLOSED:
            if self._handle is not None and not self._handle.closed:
                self._handle.close()

            self._state = _SessionState.CLOSED


class _AsyncFileWriteSession(_FileWriteSession):
    def __init__(self, prepared: PreparedWrite):
        super().__init__(prepared)
        self._ahandle: AsyncFile[bytes] | None = None

    async def aends_with_newline(self) -> bool:
        """Whether ``path``'s final byte is a newline, checked in binary."""
        try:
            async with await async_open(self.path, "rb") as f:
                await f.seek(-1, 2)
                ending = await f.read(1)
                result = ending == b"\n"
        except (FileNotFoundError, OSError):
            result = False

        return result

    @property
    async def ainitial_fize_size(self) -> int:
        """Whether ``path`` exists and is non-empty."""
        if self._initial_fize_size is None:
            path = _backend.Path(self.path)

            try:
                file_stat = await path.stat()
            except FileNotFoundError:
                self._initial_fize_size = 0
            else:
                self._initial_fize_size = int(file_stat.st_size)

        return self._initial_fize_size

    @property
    async def aneeds_newline(self) -> bool:
        if self._needs_newline is None:
            if self.append_mode and await self.ainitial_fize_size:
                self._needs_newline = not await self.aends_with_newline()
            else:
                self._needs_newline = False
        elif self._needs_newline and self._written:
            self._needs_newline = False

        return self._needs_newline

    @property
    async def askip_header(self) -> bool:
        if self._skip_header is None:
            self._skip_header = ((await self.ainitial_fize_size) or self._written) > 0
        elif self._written and not self._skip_header:
            self._skip_header = True

        return self._skip_header

    async def aacquire(self) -> None:
        if self._incremental:
            self._ahandle = await async_open(self.path, self.file_mode)

    async def _aconvert(
        self, items: Items | AsyncItems, validate: bool = False
    ) -> ConversionOutput | str:
        records = [item async for item in as_async(items)]

        if validate:
            records = self._validate_items(records)

        kwargs = {"skip_header": await self.askip_header} if self.csv_format else {}
        result = await asyncify(convert_records)(records, self.fmt, **kwargs)

        if result and self.jsonl_format:
            result = _normalize_jsonl(_as_text(result))

        return result

    async def _aemit(self, content: ConversionOutput | str) -> None:
        if content and self._ahandle is not None:
            if await self.aneeds_newline:
                self._written += await self._ahandle.write(b"\n")

            self._written += await self._ahandle.write(_as_bytes(content))

    async def _awrite_items(self, items: Items | AsyncItems) -> None:
        self.input_shape = _InputShape.STREAM
        content = await self._aconvert(items)

        if self._incremental:
            await self._aemit(content)
        else:
            self._staged = content

    async def _awrite_item(self, item: Item) -> None:
        self.input_shape = _InputShape.ITEM

        if self._incremental:
            content = await self._aconvert([item], validate=True)
            await self._aemit(content)
        else:
            self._buffer.append(item)

    async def write(self, value: Item | Items | AsyncItems) -> None:
        r"""
        Delivers one record or the whole record stream.

        A mapping is one record (the temporary singleton path); anything else is the
        logical stream (the native converter path).

        Args:

            value: One record, or the record stream.

        Examples:

            >>> from riko import get_async_temp_file, issync, run
            >>> from riko.definitions._targets import prepare_write
            >>>
            >>> async def main():
            ...     async with get_async_temp_file() as fp:
            ...         prepare = prepare_write(fp.name, fmt="jsonl")
            ...         session = _AsyncFileWriteSession(prepare)
            ...         await session.aacquire()
            ...         await session.write({"x": 0})
            ...         _ = await session.afinalize()
            ...         await session.ateardown()
            ...
            ...         with open(fp.name, mode="rb") as f:
            ...             print(f.read())
            >>>
            >>> run(main)
            b'{"x": 0}\n'

        """
        self._require_open()

        if is_mapping(value):
            await self._awrite_item(value)
        else:
            await self._awrite_items(value)

    async def _aframed_content(self) -> ConversionOutput | str:
        if self._staged is not None:
            content = self._staged
        elif self._buffer:
            content = await self._aconvert(self._buffer)
        else:
            content = ""

        return content

    async def _acommit(self) -> WriteResult:
        if not self._incremental:
            if content := await self._aframed_content():
                async with await async_open(self.path, "wb") as f:
                    self._written += await f.write(_as_bytes(content))
        elif self._ahandle is not None:
            await self._ahandle.flush()

        return WriteResult(written=self._written)

    async def afinalize(self) -> WriteResult:
        """
        Commits the delivery and reports the bytes written (idempotent).

        A framed document is published here — exactly once. Calling finalize again
        returns the same cached result rather than re-committing.

        Returns:

            A result carrying the number of bytes written.

        Examples:

            >>> from riko import get_async_temp_file, issync, run
            >>> from riko.definitions._targets import prepare_write
            >>>
            >>> async def main():
            ...     async with get_async_temp_file() as fp:
            ...         session = _AsyncFileWriteSession(prepare_write(fp.name))
            ...         await session.aacquire()
            ...         await session.write([{"x": 1}])
            ...         result = await session.afinalize()
            ...         same = await session.afinalize()
            ...         await session.ateardown()
            ...         print(result is same)
            >>>
            >>> run(main)
            True

        """
        if self._state is _SessionState.FINALIZED:
            result = self._result
        else:
            self._require_open()
            result = await self._acommit()
            self._result = result
            self._state = _SessionState.FINALIZED

        return result

    async def ateardown(self) -> None:
        if self._state is not _SessionState.CLOSED:
            if self._ahandle is not None and not self._ahandle.closed:
                await self._ahandle.aclose()

            self._state = _SessionState.CLOSED


@contextmanager
def file_write_session(prepared: PreparedWrite) -> Generator[SyncWriteSession]:
    """
    A resource lifecycle that acquires a file write session and tears it down.

    The lifecycle only acquires and releases the session; committing (finalize) or
    abandoning (abort) is the execution host's decision, made before the ``with``
    block exits.

    Args:

        prepared: The target-bound, validated write.

    Yields:

        The live file write session.

    Examples:

        >>> from riko import get_temp_file
        >>> from riko.definitions._targets import prepare_write
        >>>
        >>> with get_temp_file() as fp:
        ...     prepared = prepare_write(fp.name)
        ...
        ...     with file_write_session(prepared) as session:
        ...         session.write([{"x": 0}])
        ...         result = session.finalize()
        ...
        ...     result.written > 0
        True

    """
    if not isinstance(prepared.target, File):
        raise NotImplementedError("only file targets can be written today")

    session = _SyncFileWriteSession(prepared)
    session.acquire()

    try:
        yield session
    finally:
        session.teardown()


def mint_write_resource(
    dest: Destination,
    *,
    mode: WriteMode | str = WriteMode.REPLACE,
    fmt: FmtLike | None = None,
    keys: KeyLike | None = None,
) -> OneShotResource[SyncWriteSession]:
    """
    Mints an anonymous, execution-local write-session resource from a destination.

    The destination is prepared and validated eagerly, then wrapped as a OneShotResource
    the execution layer opens before the write and tears down after.

    Args:

        dest: A path, ``Path``, or ``WriteTarget``.
        mode: The write mode, as a ``WriteMode`` or its string value.
        fmt: The serialization format override, else derived from the extension.
        keys: The unified keys, interpreted per the target's capabilities.

    Returns:

        A one-shot resource wrapping the live file write session's lifecycle.

    Examples:

        >>> from riko.runtime._resources import OneShotResource
        >>>
        >>> resource = mint_write_resource("report.csv")
        >>> isinstance(resource, OneShotResource)
        True
        >>> resource.reusable
        False
        >>> resource.external
        False
        >>> resource.kind.value
        'sync_contextmanager'

    """
    prepared = prepare_write(dest, mode, fmt=fmt, keys=keys)
    session = file_write_session(prepared)
    return Resource.from_lifecycle(session)


@asynccontextmanager
async def async_file_write_session(
    prepared: PreparedWrite,
) -> AsyncGenerator[AsyncWriteSession]:
    if not isinstance(prepared.target, File):
        raise NotImplementedError("only file targets can be written today")

    session = _AsyncFileWriteSession(prepared)
    await session.aacquire()

    try:
        yield session
    finally:
        await session.ateardown()


def write_through(
    source: Items, prepared: PreparedWrite, *, terminating: Callable[[], bool]
) -> Generator[Item]:
    """
    Passes each item through a lazily acquired write session unchanged.

    The session is opened on first iteration, so preparing a passthrough write has no
    side effects until the stream is consumed. A graceful close finalizes the write; a
    termination/exception aborts it.

    Args:

        source: The upstream stream to write and pass through.
        prepared: The target-bound, validated write.
        terminating: Reports whether the enclosing pipe is terminating (vs. closing).

    Yields:

        Each source item, unchanged.

    """
    with file_write_session(prepared) as session:
        try:
            for item in source:
                session.write(item)
                yield item
        except GeneratorExit:
            session.abort() if terminating() else session.finalize()
            raise
        except BaseException:
            session.abort()
            raise
        else:
            session.finalize()


async def async_write_through(
    source: Items | AsyncItems,
    prepared: PreparedWrite,
    *,
    terminating: Callable[[], bool] | None = None,
) -> AsyncGenerator[Item]:
    """
    Passes each item through a lazily acquired write session unchanged.

    The async counterpart of :func:`write_through`; the session is opened on first
    iteration. Exception-sensitive early-close and terminate semantics are owned by
    the execution layer and remain partial here.

    Args:

        source: The upstream stream to write and pass through.
        prepared: The target-bound, validated write.
        terminating: Reports whether the enclosing pipe is terminating (vs. closing).

    Yields:

        Each source item, unchanged.

    """
    async with async_file_write_session(prepared) as session:
        try:
            async for item in as_async(source):
                await session.write(item)
                yield item
        except GeneratorExit:
            abort = False if terminating is None else terminating()
            session.abort() if abort else await session.afinalize()
            raise
        except BaseException:
            session.abort()
            raise
        else:
            await session.afinalize()
