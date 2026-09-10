# vim: sw=4:ts=4:expandtab
"""
riko.targets
~~~~~~~~~~~~

Write target adapters (PRIVATE).

A ``WriteTarget`` is a destination the ``sink``/``write`` verbs deliver records to.
``File`` is the one built-in target. It serializes with the ``Targets`` converters
and writes to a path. External providers (Airtable, databases, …) supply their own
``WriteTarget`` implementations outside core. ``resolve_target`` normalizes a
destination argument (a path string or a target object) into a ``WriteTarget``.

The ``WriteMode`` axis differs by target: a keyed record store treats ``replace``/
``delete`` as match-on-``keys`` operations; but a ``File`` treats ``replace`` as
overwrite, and ``append`` as append. Files have no keys, so it builds a
``WriteOperation`` directly rather than through the keyed ``write_operation``
validator.

Delivery granularity (item-by-item vs buffered) is **not** caller-configured: it is
negotiated from the resolved ``(target × format)`` capabilities. A line-oriented
format (csv/jsonl) is written incrementally; a whole-document format (json/geojson)
buffers and writes one document. This resolved strategy is a private property of the
writer, never a public write parameter.

Examples:

    Basic usage::

        >>> from riko.targets import File, resolve_target
        >>>
        >>> resolve_target("out.csv")
        File(url='out.csv', format=None)

"""

import json
from dataclasses import dataclass, field
from enum import StrEnum
from pathlib import Path
from typing import Protocol, runtime_checkable

from riko.types._guards import is_mapping
from riko.types._io import IOFileLikeType
from riko.types._scalars import AnyStrType
from riko.types._streams import Item, RikoItems
from riko.types._wrappers import ConversionOutput
from riko.writes import KeyLike, WriteMode, WriteOperation, write_operation

type Destination = str | Path | "WriteTarget"


class Formats(StrEnum):
    """How a write serializes records to a destination."""

    CSV = "csv"
    GEOJSON = "geojson"
    JSON = "json"
    JSONL = "jsonl"
    OFX = "ofx"
    QIF = "qif"


FILE_OPEN_MODES: dict[WriteMode, str] = {
    WriteMode.APPEND: "ab",
    WriteMode.REPLACE: "wb+",
}
STREAMABLE_FORMATS: frozenset[Formats] = frozenset({Formats.CSV, Formats.JSONL})


@dataclass(frozen=True, slots=True)
class WriteResult:
    """
    What a write delivery did.

    Attributes:

        created: Records inserted (keyed record targets).
        updated: Records updated (keyed record targets).
        deleted: Records removed (keyed record targets).
        written: Bytes written (serializing file targets).

    """

    created: int = 0
    updated: int = 0
    deleted: int = 0
    written: int = 0


@dataclass(frozen=True, slots=True)
class WriteCapabilities:
    """
    What a write target supports.

    Attributes:

        modes: The ``WriteMode`` values the target accepts.
        serializes: Whether the target encodes records with a format (a file),
            as opposed to sending native records (a record store).

    """

    modes: frozenset[WriteMode]
    serializes: bool


@runtime_checkable
class WriteTarget(Protocol):
    """A destination that reports its capabilities and delivers records."""

    def capabilities(self, fmt: Formats | str | None = None) -> WriteCapabilities:
        """
        Reports the modes and serialization behavior the target supports.

        For a serializing target the supported modes depend on ``fmt``: only a
        line-oriented format (csv/jsonl) can be appended to; a whole-document
        format (json/geojson/…) supports ``replace`` only. Non-serializing
        targets ignore ``fmt``.
        """
        ...

    def deliver(
        self,
        records: RikoItems,
        write: WriteOperation,
        *,
        fmt: Formats | str | None = None,
    ) -> WriteResult:
        """Delivers ``records`` to the destination under ``write`` semantics."""
        ...

    async def adeliver(
        self,
        records: RikoItems,
        write: WriteOperation,
        *,
        fmt: Formats | str | None = None,
    ) -> WriteResult:
        """Asynchronously delivers ``records`` under ``write`` semantics."""
        ...


@dataclass(frozen=True, slots=True)
class File:
    """
    A file target: serialize records with a ``Targets`` converter and write a path.

    Supports ``replace`` for every format and ``append`` only for a line-oriented
    format (csv/jsonl); ``WriteMode`` maps to the file-open mode, which is no longer
    caller-visible. Appending to a whole-document format (json/geojson) is rejected
    at prepare rather than concatenating two documents into invalid output.

    Attributes:

        url: The destination path.
        format: The ``Targets`` converter name, or ``None`` to derive it from the
            path extension (falling back to ``json``).

    Examples:

        >>> from riko import get_temp_file
        >>> from riko.targets import File
        >>> from riko.writes import WriteMode, WriteOperation
        >>>
        >>> with get_temp_file() as fp:
        ...     result = File(fp.name).deliver([{"x": 1}], WriteOperation(WriteMode.REPLACE))
        ...     result.written > 0
        True

    """

    url: str | Path
    format: str | None = None

    def capabilities(self, fmt: Formats | str | None = None) -> WriteCapabilities:
        """
        Reports format-aware file capabilities.

        A line-oriented format (csv/jsonl) supports ``append`` and ``replace``;
        a whole-document format (json/geojson/ofx/qif) supports ``replace`` only,
        because appending would concatenate two documents into invalid output.
        """
        resolved = resolve_format(self.url, fmt or self.format)
        modes = frozenset({WriteMode.APPEND, WriteMode.REPLACE})
        replace_only = frozenset({WriteMode.REPLACE})
        supported = modes if resolved in STREAMABLE_FORMATS else replace_only
        return WriteCapabilities(modes=supported, serializes=True)

    def _encode(
        self, records: RikoItems, fmt: Formats | str | None
    ) -> ConversionOutput | None:
        """Serializes ``records`` with the resolved ``Targets`` converter."""
        from riko.collections import CONVERSION_FUNCS  # noqa: PLC0415
        from riko.modules.write import _resolve_target  # noqa: PLC0415

        items = [dict(item) for item in records if is_mapping(item)]
        target = _resolve_target(self.url, fmt or self.format, *CONVERSION_FUNCS)
        convert = CONVERSION_FUNCS.get(target)
        return convert(items) if convert else None

    def deliver(
        self,
        records: RikoItems,
        write: WriteOperation,
        *,
        fmt: Formats | str | None = None,
    ) -> WriteResult:
        """
        Serializes ``records`` and writes them to ``url``.

        Args:

            records: The records to serialize.
            write: The write spec; only ``mode`` is read (``append`` vs ``replace``).
            fmt: A ``Targets`` converter override; else ``format``, else derived
                from the path extension.

        Returns:

            A result carrying the number of bytes written.

        """
        from meza import io  # noqa: PLC0415

        content = self._encode(records, fmt)
        file_mode = FILE_OPEN_MODES[write.mode]
        written = (
            int(io.write(str(self.url), content, mode=file_mode) or 0) if content else 0
        )
        return WriteResult(written=written)

    async def adeliver(
        self,
        records: RikoItems,
        write: WriteOperation,
        *,
        fmt: Formats | str | None = None,
    ) -> WriteResult:
        """
        Asynchronously serializes ``records`` and writes them to ``url``.

        The async counterpart of :meth:`deliver`, writing through
        :func:`riko.bado.io.async_write`.

        Args:

            records: The records to serialize.
            write: The write spec; only ``mode`` is read (``append`` vs ``replace``).
            fmt: A ``Targets`` converter override; else ``format``, else derived
                from the path extension.

        Returns:

            A result carrying the number of bytes written.

        """
        from riko.bado.io import async_write  # noqa: PLC0415

        content = self._encode(records, fmt)

        if isinstance(content, AnyStrType + IOFileLikeType):
            file_mode = FILE_OPEN_MODES[write.mode]
            written = await async_write(str(self.url), content, mode=file_mode)
        else:
            written = 0

        return WriteResult(written=written)


def build_write(
    target: WriteTarget,
    mode: WriteMode | str,
    *,
    keys: KeyLike | None = None,
    idempotency_key: KeyLike | None = None,
    fmt: Formats | str | None = None,
) -> WriteOperation:
    """
    Validates ``mode`` against ``target``'s capabilities and builds a ``WriteOperation``.

    Whether a mode is keyed is a per-target property, not a mode-global one. A
    serializing target (e.g., ``File``) treats every mode as an unkeyed write and
    forbids ``keys``/``idempotency_key``. A record store routes through the keyed
    :func:`riko.writes.write_operation` validator. For a serializing target, the
    valid modes also depend on ``fmt``. Appending to a whole-document format (e.g.,
    json) is rejected here.

    Args:

        target: The resolved write target.
        mode: The write mode, as a ``WriteMode`` or its string value.
        keys: The match keys for a keyed record target.
        idempotency_key: The dedupe key for an ``append`` on a record target.
        fmt: The serialization format used to validate the mode.

    Returns:

        The normalized, validated write specification.

    Raises:

        ValueError: When ``mode`` is unsupported by the target, or a serializing
            target is given ``keys``/``idempotency_key``.

    Examples:

        >>> from riko.targets import File, build_write
        >>>
        >>> build_write(File("out.csv"), "append")
        WriteOperation(mode=<WriteMode.APPEND: 'append'>, keys=(), idempotency_key=())

    """
    caps = target.capabilities(fmt)
    resolved = WriteMode(mode)

    if resolved not in caps.modes:
        valid = ", ".join(sorted(m.value for m in caps.modes))
        raise ValueError(
            f"the write target does not support the '{resolved.value}' mode; "
            f"supported: {valid}"
        )
    elif caps.serializes and (keys is not None or idempotency_key is not None):
        raise ValueError(
            "a serializing write target forbids 'keys' and 'idempotency_key'"
        )
    elif caps.serializes:
        write = WriteOperation(resolved)
    else:
        write = write_operation(resolved, keys=keys, idempotency_key=idempotency_key)

    return write


def resolve_target(dest: Destination, **conf: object) -> WriteTarget:
    """
    Normalizes a destination argument into a ``WriteTarget``.

    A ``WriteTarget`` is returned unchanged; a path string or ``Path`` becomes a
    ``File``. Named registry targets are deferred until a second built-in target
    exists, so every string is currently treated as a file path.

    Args:

        dest: A ``WriteTarget``, or a path string/``Path``.
        conf: Extra keyword configuration for a constructed ``File`` (e.g.
            ``format``).

    Returns:

        The resolved write target.

    Raises:

        TypeError: When ``dest`` is neither a ``WriteTarget`` nor a path.

    Examples:

        >>> from riko.targets import File, resolve_target
        >>>
        >>> resolve_target("out.csv")
        File(url='out.csv', format=None)
        >>> resolve_target(File("out.json")).url
        'out.json'

    """
    if isinstance(dest, WriteTarget):
        target: WriteTarget = dest
    elif isinstance(dest, str | Path):
        target = File(dest, **conf)  # pyright: ignore[reportArgumentType]
    else:
        raise TypeError(f"cannot resolve a write target from {dest!r}")

    return target


def resolve_format(url: str | Path | None, fmt: Formats | str | None) -> Formats:
    """
    Resolves a serialization format from an explicit ``fmt``, else the extension.

    An explicit ``fmt`` wins. Otherwise the url's lowercased extension is used
    when it names a known format; anything else falls back to ``json``.

    Args:

        url: The destination path, or ``None``.
        fmt: The explicit format, or ``None`` to derive one.

    Returns:

        The resolved format name.

    Examples:

        >>> from riko.targets import resolve_format
        >>>
        >>> resolve_format("out.jsonl", None)
        <Formats.JSONL: 'jsonl'>
        >>> resolve_format("out", None)
        <Formats.JSON: 'json'>

    """
    if fmt:
        resolved = fmt
    else:
        ext = Path(str(url)).suffix.lstrip(".").lower()
        resolved = ext or Formats.JSON

    return Formats(resolved)


@dataclass(slots=True)
class _FileWriter:
    """
    A file writer driven by a subscriber's ``on_receive`` side-effect.

    A streamable format (``csv``/``jsonl``) is written incrementally as each item
    arrives; any other format buffers every item and writes one document when the
    publisher completes. ``stream`` is the resolved delivery strategy, negotiated
    from the format — not a caller-supplied option.

    Attributes:

        target: The resolved file target.
        mode: ``append`` or ``replace``.
        fmt: The resolved serialization format.
        stream: The resolved delivery strategy — whether items are written
            incrementally.

    """

    target: WriteTarget
    mode: WriteMode
    fmt: Formats
    stream: bool
    _buffer: list[Item] = field(default_factory=list)
    _started: bool = False
    _completed: bool = False

    def receive(self, item: Item) -> None:
        """Writes ``item`` now when streaming, else buffers it for completion."""
        if self.stream:
            self._write_one(item)
        else:
            self._buffer.append(item)

    def complete(self) -> None:
        """Writes the buffered document once, when the publisher signals completion."""
        if not self.stream and not self._completed:
            self._completed = True
            self.target.deliver(self._buffer, WriteOperation(self.mode), fmt=self.fmt)

    def _write_one(self, item: Item) -> None:
        """Appends a single item as a ``csv`` row or a ``jsonl`` line."""
        from meza import convert as cv  # noqa: PLC0415
        from meza import io  # noqa: PLC0415

        first = not self._started
        file_mode = FILE_OPEN_MODES[self.mode] if first else "ab"
        append_mode = self.mode == WriteMode.APPEND
        skip_header = not first or (append_mode and self._has_content())

        if self.fmt == Formats.CSV:
            content = cv.records2csv([dict(item)], skip_header=skip_header)
        else:
            content = json.dumps(dict(item), default=str) + "\n"

        io.write(str(self._url), content, mode=file_mode)
        self._started = True

    def _has_content(self) -> bool:
        """Whether the destination file already exists and is non-empty."""
        path = Path(str(self._url))
        return path.exists() and path.stat().st_size > 0

    @property
    def _url(self) -> str | Path:
        """The destination path of the underlying file target."""
        return getattr(self.target, "url", "")


def file_writer(
    dest: Destination,
    *,
    mode: WriteMode | str = WriteMode.REPLACE,
    fmt: Formats | str | None = None,
) -> _FileWriter:
    """
    Builds the ``on_receive`` file writer the ``write`` verb desugars onto.

    Delivery strategy (incremental vs buffered) is negotiated from the resolved
    format — a line-oriented format streams, a whole-document format buffers — and
    is never caller-configured.

    Args:

        dest: A path, or a ``WriteTarget``.
        mode: ``append`` or ``replace``; the keyed record modes are rejected.
        fmt: A serialization format override, else derived from the extension.

    Returns:

        The configured file writer.

    Raises:

        ValueError: When ``mode`` is not ``append`` or ``replace``, or ``append``
            is requested for a non-streamable format.

    Examples:

        >>> from riko.targets import file_writer
        >>>
        >>> file_writer("out.jsonl").stream
        True
        >>> file_writer("out.json").stream
        False

    """
    target = resolve_target(dest)
    resolved_mode = WriteMode(mode)
    resolved_fmt = resolve_format(getattr(target, "url", None), fmt)

    if resolved_mode not in FILE_OPEN_MODES:
        valid = ", ".join(m.value for m in FILE_OPEN_MODES)
        raise ValueError(f"the 'write' verb supports only the {valid} modes")
    elif resolved_mode == WriteMode.APPEND and resolved_fmt not in STREAMABLE_FORMATS:
        valid = ", ".join(sorted(STREAMABLE_FORMATS))
        raise ValueError(
            f"the '{resolved_fmt}' format cannot be appended to; "
            f"appendable formats: {valid}"
        )

    streaming = resolved_fmt in STREAMABLE_FORMATS
    return _FileWriter(target, resolved_mode, resolved_fmt, streaming)


__all__ = [
    "FILE_OPEN_MODES",
    "STREAMABLE_FORMATS",
    "Destination",
    "File",
    "Formats",
    "WriteCapabilities",
    "WriteResult",
    "WriteTarget",
    "build_write",
    "file_writer",
    "resolve_format",
    "resolve_target",
]
