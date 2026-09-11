from collections.abc import Iterator
from contextlib import contextmanager
from functools import partial
from io import StringIO
from pathlib import Path
from typing import AnyStr

from riko._formats import convert_records
from riko.resources import OneShotResource, Resource
from riko.targets import prepare_write
from riko.types._guards import is_mapping
from riko.types._io import IOFileLike
from riko.types._streams import Item, Items
from riko.types._write import (
    Destination,
    Formats,
    KeyLike,
    PreparedWrite,
    WriteMode,
    WriteOperation,
    WriteResult,
    WriteTarget,
)

FILE_OPEN_MODES: dict[WriteMode, str] = {
    WriteMode.APPEND: "ab",
    WriteMode.REPLACE: "wb+",
}


class _FileWriteSession:
    r"""
    The live file write session yielded by :func:`write_session`'s lifecycle.

    An execution-owned session that receives records via :meth:`write`/:meth:`awrite`.
    The enclosing lifecycle calls :meth:`finalize` on teardown to flush a buffered
    document and report bytes written. Streamable formats (e.g., ``csv``/``jsonl``)
    write each record as it arrives. Others (e.g., ``json``/``geojson``) buffer and
    write one document at finalize.

    Header suppression for a ``csv`` append derives from the destination file's existing
    content, not an in-run flag. So a fresh append execution against an existing
    non-empty file does not re-emit the header.

    Attributes:

        target: The resolved file target.
        mode: ``append`` or ``replace``.
        operation: The normalized, validated write specification.
        fmt: The resolved serialization format.

    Examples:

        >>> from riko import get_temp_file
        >>>
        >>> with get_temp_file() as fp:
        ...     prepared = prepare_write(fp.name)
        ...     session = _FileWriteSession(prepared)
        ...     session.write({"x": 0})
        ...     session.write({"x": 1})
        ...     session.finalize()
        ...
        ...     with open(fp.name, mode="rb") as f:
        ...         f.read()
        b'{"x": 0}\n{"x": 1}\n'

    """

    _streamable: bool = False
    _started: bool = False
    _completed: bool = False
    _written: int = 0

    def __init__(self, prepared: PreparedWrite):
        self.target: WriteTarget = prepared.target
        self.operation: WriteOperation = prepared.operation
        self.fmt: Formats = prepared.fmt
        self.mode: WriteMode = prepared.operation.mode
        self.append_mode = False
        self._buffer: list[Item] = []
        self._started = False
        self._streamable = prepared.capabilities.streamable
        self.content: AnyStr | IOFileLike = None

    @property
    def _url(self) -> str | Path:
        """The destination path of the underlying file target."""
        return getattr(self.target, "url", "")

    def _has_content(self) -> bool:
        """Whether the destination file already exists and is non-empty."""
        try:
            result = Path(str(self._url)).stat().st_size > 0
        except FileNotFoundError:
            result = False

        return result

    def _has_newline(self) -> bool:
        """Whether the destination file already exists and has a newline ending."""
        path = Path(str(self._url))

        try:
            size = path.stat().st_size
        except FileNotFoundError:
            result = False
        else:
            with path.open() as f:
                f.seek(size - 1)
                result = f.read(1) == "\n"

        return result

    def _prepare(self) -> None:
        first = not self._started
        mode = self.mode if first else WriteMode.APPEND

        try:
            self.file_mode = FILE_OPEN_MODES[mode]
        except KeyError as e:
            msg = f"Prepared file write has unsupported mode: {mode!r}"
            raise RuntimeError(msg) from e

        self.append_mode = mode == WriteMode.APPEND
        skip_header = not first or (self.append_mode and self._has_content())
        self.kwargs = {"skip_header": skip_header} if self.fmt == Formats.CSV else {}

    def _convert(self, item: Item | Items) -> None:
        self._prepare()
        records = [item] if is_mapping(item) else item
        content = convert_records(records, self.fmt, **self.kwargs)

        if is_mapping(item):
            if isinstance(content, StringIO):
                _content = content.getvalue()
            else:
                _content = next(iter(content))

            if isinstance(_content, str):
                content = _content.rstrip("\n").lstrip("[").rstrip("]")
            else:
                content = _content

        self.content: AnyStr | IOFileLike = content

    def _write(self) -> None:
        """Appends a single item as a ``csv`` row or a ``jsonl`` line."""
        from meza import io  # noqa: PLC0415

        write = partial(io.write, str(self._url), mode=self.file_mode)

        if self.append_mode and self._started:
            self._written += write("\n")

        self._written += write(self.content)

        if not self._started:
            self._started = True

    def write(self, item: Item | Items) -> None:
        """
        Writes ``item`` to a file.

        Args:

            item: The record to write.

        Examples:

            >>> from pathlib import Path
            >>> from riko import get_temp_file
            >>> from riko.targets import file_writer
            >>>
            >>> with get_temp_file() as fp:
            ...     prepared = prepare_write(fp.name)
            ...     session = _FileWriteSession(prepared)
            ...     session.write({"x": 1})
            ...     Path(fp.name).read_text().strip()
            '{"x": 0}'

        """
        if self._streamable:
            self._convert(item)
            self._write()
        elif is_mapping(item):
            self._buffer.append(item)
        else:
            self._buffer.extend(item)

    async def _awrite(self) -> None:
        from riko.bado.io import async_write  # noqa: PLC0415

        awrite = partial(async_write, self._url, mode=self.file_mode)

        if self.append_mode and self._started:
            self._written += await awrite("\n")

        self._written += await awrite(self.content)

        if not self._started:
            self._started = True

    async def awrite(self, item: Item | Items) -> None:
        r"""
        Asynchronously writes ``item`` to a file.

        The async counterpart of :meth:`write`, driven by the resource's
        ``aopen``/``aclose`` lifecycle.

        Args:

            item: The item or records to serialize.

        Examples:

            >>> await session.awrite({"x": 0})
            >>> fp
            b'{"x": 0}\n'

            >>> from riko import get_temp_file, run
            >>> from riko.targets import File
            >>> from riko.writes import WriteMode, WriteOperation
            >>>
            >>> async def main():
            ...     with get_temp_file() as fp:
            ...         op = WriteOperation(WriteMode.REPLACE)
            ...         result = await File(fp.name).adeliver([{"x": 1}], op)
            ...         return result.written > 0
            >>>
            >>> run(main)
            True

        """
        if self._streamable:
            self._convert(item)
            await self._awrite()
        elif is_mapping(item):
            self._buffer.append(item)
        else:
            self._buffer.extend(item)

    def finalize(self) -> WriteResult:
        """
        Flushes any buffered document and reports the aggregated outcome.

        Returns:

            A result carrying the number of bytes written.

        Examples:

            >>> from riko import get_temp_file
            >>>
            >>> with get_temp_file() as fp:
            ...     prepared = prepare_write(fp.name)
            ...     session = _FileWriteSession(prepared)
            ...     session.write({"x": 1})
            ...     session.finalize()
            >>> Path(fp.name).read_text()
            '[{"x": 0}]'

        """
        from meza import io  # noqa: PLC0415

        if self._buffer:
            self._convert(self._buffer)
            self._write()
            self._buffer.clear()
        elif self.append_mode and not self._has_newline():
            self._written += io.write(str(self._url), "\n", mode=self.file_mode)

        self._completed = True
        self._started = False
        return WriteResult(written=self._written)

    def abort(self) -> None:
        """
        Aborts the session and discards any buffered content.

        Examples:

            >>> from riko import get_temp_file
            >>>
            >>> with get_temp_file() as fp:
            ...     prepared = prepare_write(fp.name)
            ...     session = _FileWriteSession(prepared)
            ...     session.write({"x": 1})
            ...     session.abort()
            ...     Path(fp.name).exists()
            False

        """
        self._buffer.clear()
        self._completed = True

    def teardown(self) -> None:
        """
        Tears down the session by flushing any buffered content and releasing resources.

        Examples:

            >>> from riko import get_temp_file
            >>>
            >>> with get_temp_file() as fp:
            ...     prepared = prepare_write(fp.name)
            ...     session = _FileWriteSession(prepared)
            ...     session.write({"x": 1})
            ...     session.teardown()
            ...     Path(fp.name).exists()
            True

        """
        if not self._completed:
            self.finalize()


def mint_write_resource(
    dest: Destination,
    *,
    mode: WriteMode | str = WriteMode.REPLACE,
    fmt: Formats | str | None = None,
    keys: KeyLike | None = None,
) -> OneShotResource[_FileWriteSession]:
    """
    Mints an anonymous, execution-local write-session resource from a destination.

    This is the mechanism the ``write("report.csv")`` surface desugars onto: the path
    string is the surface, the resource is the mechanism. It wraps the
    :func:`write_session` lifecycle in :meth:`riko.resources.Resource.from_lifecycle`,
    producing a one-shot resource the execution layer opens before the write and closes
    after. The resource is anonymous and execution-local — never stored in a ``Context``
    (a one-shot is un-reusable), so the caller declares nothing for the common case.

    Args:

        dest: A path, or a ``WriteTarget``.
        mode: ``append`` or ``replace`` for a file (default: ``replace``).
        keys: The match keys for a keyed record target.
        idempotency_key: The dedupe key for an ``append`` on a record target.
        fmt: A serialization format override, else derived from the extension.

    Returns:

        A one-shot resource whose value is the live write session.

    Examples:

        Once the execution layer drives the lifecycle, minting looks like::

            resource = mint_write_resource("report.csv")
            isinstance(resource, OneShotResource)  # -> True
            resource.reusable  # -> False

    """
    prepared = prepare_write(dest, mode, fmt=fmt, keys=keys)
    session = file_write_session(prepared)
    return Resource.from_lifecycle(session)


@contextmanager
def file_write_session(prepared: PreparedWrite) -> Iterator[_FileWriteSession]:
    """
    A context-managed lifecycle that yields a live file write session.

    Examples:

        >>> prepared = prepare_write(dest, mode=mode, fmt=fmt)
        >>>
        >>> with file_write_session(prepared) as session:
        ...     session.write({"x": 0})
        >>>
        >>> fp

    """
    session = _FileWriteSession(prepared)

    try:
        yield session
    except Exception:
        session.abort()
        raise
    else:
        session.finalize()
    finally:
        session.teardown()
