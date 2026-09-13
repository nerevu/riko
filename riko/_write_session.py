from __future__ import annotations

from collections.abc import AsyncGenerator, Callable, Generator
from contextlib import asynccontextmanager, contextmanager
from enum import Enum, auto
from io import StringIO
from pathlib import Path
from typing import TYPE_CHECKING, BinaryIO

from riko._constants import ENCODING
from riko._formats import convert_records
from riko._reencode import IterStringIO, Reencoder, reencode
from riko.bado import _backend
from riko.bado._backend import async_open, asyncify
from riko.bado.itertools import as_async
from riko.resources import OneShotResource, Resource
from riko.targets import File, prepare_write
from riko.types._guards import is_mapping
from riko.types._streams import AsyncItems, Item, Items, Stream
from riko.types._wrappers import ConversionOutput
from riko.types._write import (
    AsyncWriteSession,
    Destination,
    Formats,
    KeyLike,
    PreparedWrite,
    SyncWriteSession,
    WriteMode,
    WriteResult,
)

if TYPE_CHECKING:
    from _typeshed import OpenBinaryMode
    from anyio import AsyncFile


class _SessionState(Enum):
    """The lifecycle state of a write session."""

    OPEN = auto()
    FINALIZED = auto()
    ABORTED = auto()
    CLOSED = auto()


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

        self.target: File = prepared.target
        self.operation = prepared.operation
        self.mode: WriteMode = prepared.operation.mode
        self.fmt: Formats = prepared.fmt or Formats.JSON
        self._incremental: bool = prepared.capabilities.incremental
        self._state: _SessionState = _SessionState.OPEN
        self._buffer: list[Item] = []
        self._staged: ConversionOutput | str | None = None
        self._written: int = 0
        self._result: WriteResult = WriteResult()
        self._has_content: bool | None = None
        self._fields: tuple[str, ...] | None = None

        self.path = Path(self.target.url)
        self.csv_format = self.fmt is Formats.CSV
        self.jsonl_format = self.fmt is Formats.JSONL
        self.append_mode = self.mode is WriteMode.APPEND
        self.file_mode: OpenBinaryMode = "ab" if self.append_mode else "wb"

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
    A live, execution-owned file write session (temporary pre-R4B host).

    Acquires the destination once, receives records via :meth:`write` (one ``Item``
    or the whole ``Items`` stream), then commits with :meth:`finalize` or abandons
    with :meth:`abort` before :meth:`teardown` releases the file. An incremental
    format (csv/jsonl) emits each converted chunk as it arrives; a framed format
    (json/geojson/…) stages the logical document and publishes it once at finalize.

    Two conversion paths coexist while the meza converters remain collection-shaped:
    a native whole-stream path (:meth:`write` given ``Items``, used by ``sink``) and
    a temporary singleton path (:meth:`write` given one ``Item``, used by passthrough
    ``write``) that remembers the csv schema/header state across records.

    Attributes:

        target: The resolved file target.
        operation: The normalized, validated write intent.
        mode: ``append`` or ``replace``.
        fmt: The resolved serialization format.

    Examples:

        >>> from riko import get_temp_file
        >>> from riko.targets import prepare_write
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

    @property
    def file_size(self) -> int | None:
        """Whether ``path`` exists and is non-empty."""
        try:
            result = self.path.stat().st_size
        except FileNotFoundError:
            result = None

        return result

    @property
    def has_content(self) -> bool:
        if not self._has_content:
            if self._written > 0:
                self._has_content = True
            else:
                file_size = self.file_size
                self._has_content = file_size is not None and file_size > 0

        return self._has_content

    def ends_with_newline(self) -> bool:
        """Whether ``path``'s final byte is a newline, checked in binary."""
        try:
            with self.path.open("rb") as f:
                f.seek(-1, 2)
                result = f.read(1) == b"\n"
        except (FileNotFoundError, OSError):
            result = False

        return result

    def needs_newline(self) -> bool:
        return self.append_mode and self.has_content and not self.ends_with_newline()

    def acquire(self) -> None:
        """
        Opens the destination once for an incremental format.

        A framed format defers all destination I/O to :meth:`finalize`, so an
        aborted framed session never mutates the file. An incremental append
        captures the existing file's content/newline state up front, since the
        writer opens in binary append and cannot re-derive it afterward.

        Examples:

            >>> from riko import get_temp_file
            >>> from riko.targets import prepare_write
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

        kwargs = {"skip_header": self.has_content} if self.csv_format else {}
        result = convert_records(items, self.fmt, **kwargs)

        if result and self.jsonl_format:
            result = _normalize_jsonl(_as_text(result))

        return result

    def _ensure_append_boundary(self) -> None:
        if self.needs_newline() and self._handle is not None:
            self._written += self._handle.write(b"\n")

    def _emit(self, content: ConversionOutput | str) -> None:
        if content and self._handle is not None:
            self._ensure_append_boundary()
            self._written += self._handle.write(_as_bytes(content))

    def _write_items(self, items: Items) -> None:
        content = self._convert(items)

        if self._incremental:
            self._emit(content)
        else:
            self._staged = content

    def _write_item(self, item: Item) -> None:
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
            >>> from riko.targets import prepare_write
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
            >>> from riko.targets import prepare_write
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
            >>> from riko.targets import prepare_write
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

    async def afile_size(self) -> int | None:
        """Whether ``path`` exists and is non-empty."""
        path = _backend.Path(self.path)

        try:
            file_stat = await path.stat()
        except FileNotFoundError:
            result = None
        else:
            result = file_stat.st_size

        return result

    @property
    async def ahas_content(self) -> bool:
        if not self._has_content:
            if self._written > 0:
                self._has_content = True
            else:
                file_size = await self.afile_size()
                self._has_content = file_size is not None and file_size > 0

        return self._has_content

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

    async def aneeds_newline(self) -> bool:
        return (
            self.append_mode
            and await self.ahas_content
            and not await self.aends_with_newline()
        )

    async def aacquire(self) -> None:
        if self._incremental:
            self._ahandle = await async_open(self.path, self.file_mode)

    async def _aconvert(
        self, items: Items | AsyncItems, validate: bool = False
    ) -> ConversionOutput | str:
        records = [item async for item in as_async(items)]

        if validate:
            items = self._validate_items(records)

        if self.csv_format:
            kwargs = {"skip_header": await self.ahas_content}
        else:
            kwargs = {}

        result = await asyncify(convert_records)(records, self.fmt, **kwargs)

        if result and self.jsonl_format:
            result = _normalize_jsonl(_as_text(result))

        return result

    async def _aensure_append_boundary(self) -> None:
        if await self.aneeds_newline() and self._ahandle is not None:
            self._written += await self._ahandle.write(b"\n")

    async def _aemit(self, content: ConversionOutput | str) -> None:
        if content and self._ahandle is not None:
            await self._aensure_append_boundary()
            self._written += await self._ahandle.write(_as_bytes(content))

    async def _awrite_items(self, items: Items | AsyncItems) -> None:
        content = await self._aconvert(items)

        if self._incremental:
            await self._aemit(content)
        else:
            self._staged = content

    async def _awrite_item(self, item: Item) -> None:

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
            >>> from riko.targets import prepare_write
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
            >>> from riko.targets import prepare_write
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
        >>> from riko.targets import prepare_write
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
    fmt: Formats | str | None = None,
    keys: KeyLike | None = None,
) -> OneShotResource[SyncWriteSession]:
    """
    Mints an anonymous, execution-local write-session resource from a destination.

    The destination string is the surface a ``write`` call presents; the resource is the
    mechanism it desugars onto. The destination is prepared and validated eagerly, then
    wrapped as a one-acquisition lifecycle the execution layer opens before the write and
    tears down after. A one-shot session is never reusable, so the resource is anonymous
    and execution-local — never stored in a ``Context`` — and the caller declares nothing
    for the common case.

    Args:

        dest: A path, ``Path``, or ``WriteTarget``.
        mode: The write mode, as a ``WriteMode`` or its string value.
        fmt: The serialization format override, else derived from the extension.
        keys: The unified keys, interpreted per the target's capabilities.

    Returns:

        A one-shot resource wrapping the live file write session's lifecycle.

    Examples:

        >>> from riko.resources import OneShotResource, _FactoryKind
        >>>
        >>> resource = mint_write_resource("report.csv")
        >>> isinstance(resource, OneShotResource)
        True
        >>> resource.reusable
        False
        >>> resource.external
        False
        >>> resource.kind
        <_FactoryKind.SYNC_CONTEXTMANAGER: 'sync_contextmanager'>

    """
    prepared = prepare_write(dest, mode, fmt=fmt, keys=keys)
    session = file_write_session(prepared)
    return Resource.from_lifecycle(session)


@asynccontextmanager
async def async_file_write_session(
    prepared: PreparedWrite,
) -> AsyncGenerator[AsyncWriteSession]:
    session = _AsyncFileWriteSession(prepared)
    await session.aacquire()

    try:
        yield session
    finally:
        await session.ateardown()


def write_through(
    source: Items, session: SyncWriteSession, *, terminating: Callable[[], bool]
) -> Generator[Item]:
    """
    Passes each item through ``session`` and yields it unchanged.

    Args:

        source: The upstream stream to write and pass through.
        session: The acquired write session.
        terminating: Reports whether the enclosing pipe is terminating (vs. closing).

    Yields:

        Each source item, unchanged.

    """
    try:
        for item in source:
            session.write(item)
            yield item
    except GeneratorExit:
        abort = False if terminating is None else terminating()
        session.abort() if abort else session.finalize()
        raise
    except BaseException:
        session.abort()
        raise
    else:
        session.finalize()
    finally:
        session.teardown()


async def async_write_through(
    source: Items | AsyncItems,
    session: AsyncWriteSession,
    *,
    terminating: Callable[[], bool] | None = None,
) -> AsyncGenerator[Item]:
    """
    Passes each item through ``session`` and yields it unchanged.

    Args:

        source: The upstream stream to write and pass through.
        session: The acquired write session.
        terminating: Reports whether the enclosing pipe is terminating (vs. closing).

    Yields:

        Each source item, unchanged.

    """
    await session.aacquire()

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
    finally:
        await session.ateardown()
