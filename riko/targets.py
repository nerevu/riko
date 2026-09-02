# vim: sw=4:ts=4:expandtab
"""
riko.targets
~~~~~~~~~~~~

Sink target adapters (PRIVATE).

A ``SinkTarget`` is a destination the ``sink``/``write`` verbs deliver records to.
``File`` is the one built-in target. It serializes with the ``Targets`` converters
and writes to a path. External providers (Airtable, databases, …) supply their own
``SinkTarget`` implementations outside core. ``resolve_target`` normalizes a
destination argument (a path string or a target object) into a ``SinkTarget``.

The ``SinkMode`` axis differs by target: a keyed record store treats ``replace``/
``delete`` as match-on-``keys`` operations; but a ``File`` treats ``replace`` as
overwrite, and ``append`` as append. Files have no keys, so it builds a ``SinkWrite``
directly rather than through the keyed ``sink_write`` validator.

Examples:
    Basic usage::

        >>> from riko.targets import File, resolve_target
        >>>
        >>> resolve_target("out.csv")
        File(url='out.csv', format=None)

"""

import json
from collections.abc import Iterable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Protocol, runtime_checkable

from riko.sinks import KeyLike, SinkMode, SinkWrite, sink_write
from riko.types._io import IOFileLikeType
from riko.types._scalars import AnyStrType
from riko.types._streams import Item
from riko.types._wrappers import ConversionOutput

type Destination = str | Path | "SinkTarget"

FILE_OPEN_MODES: dict[SinkMode, str] = {SinkMode.APPEND: "ab", SinkMode.REPLACE: "wb+"}
STREAMABLE_FORMATS: frozenset[str] = frozenset({"csv", "jsonl"})
_KNOWN_FORMATS: frozenset[str] = frozenset(
    {"csv", "geojson", "json", "jsonl", "ofx", "qif"}
)


@dataclass(frozen=True, slots=True)
class SinkResult:
    """
    What a sink delivery did.

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
class SinkCapabilities:
    """
    What a sink target supports.

    Attributes:
        modes: The ``SinkMode`` values the target accepts.
        serializes: Whether the target encodes records with a format (a file),
            as opposed to sending native records (a record store).

    """

    modes: frozenset[SinkMode]
    serializes: bool


@runtime_checkable
class SinkTarget(Protocol):
    """A destination that reports its capabilities and delivers records."""

    def capabilities(self) -> SinkCapabilities:
        """Returns the modes and serialization behavior the target supports."""
        ...

    def deliver(
        self, records: Iterable[Item], write: SinkWrite, *, fmt: str | None = None
    ) -> SinkResult:
        """Delivers ``records`` to the destination under ``write`` semantics."""
        ...

    async def adeliver(
        self, records: Iterable[Item], write: SinkWrite, *, fmt: str | None = None
    ) -> SinkResult:
        """Asynchronously delivers ``records`` under ``write`` semantics."""
        ...


@dataclass(frozen=True, slots=True)
class File:
    """
    A file sink: serialize records with a ``Targets`` converter and write a path.

    Supports ``append`` (open mode ``ab``) and ``replace`` (open mode ``wb+``); the
    ``SinkMode`` maps to the file-open mode, which is no longer caller-visible.

    Attributes:
        url: The destination path.
        format: The ``Targets`` converter name, or ``None`` to derive it from the
            path extension (falling back to ``json``).

    Examples:
        >>> from riko import get_temp_file
        >>> from riko.sinks import SinkMode, SinkWrite
        >>> from riko.targets import File
        >>>
        >>> with get_temp_file() as fp:
        ...     result = File(fp.name).deliver([{"x": 1}], SinkWrite(SinkMode.REPLACE))
        ...     result.written > 0
        True

    """

    url: str | Path
    format: str | None = None

    def capabilities(self) -> SinkCapabilities:
        """Returns file capabilities: ``append``/``replace``, serializing."""
        modes = frozenset({SinkMode.APPEND, SinkMode.REPLACE})
        return SinkCapabilities(modes=modes, serializes=True)

    def _encode(
        self, records: Iterable[Item], fmt: str | None
    ) -> ConversionOutput | None:
        """Serializes ``records`` with the resolved ``Targets`` converter."""
        from riko.collections import CONVERSION_FUNCS  # noqa: PLC0415
        from riko.modules.write import _resolve_target  # noqa: PLC0415

        items = [dict(item) for item in records]
        target = _resolve_target(self.url, fmt or self.format, *CONVERSION_FUNCS)
        convert = CONVERSION_FUNCS.get(target)
        return convert(items) if convert else None

    def deliver(
        self, records: Iterable[Item], write: SinkWrite, *, fmt: str | None = None
    ) -> SinkResult:
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
        return SinkResult(written=written)

    async def adeliver(
        self, records: Iterable[Item], write: SinkWrite, *, fmt: str | None = None
    ) -> SinkResult:
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

        return SinkResult(written=written)


def build_write(
    target: SinkTarget,
    mode: SinkMode | str,
    *,
    keys: KeyLike | None = None,
    idempotency_key: KeyLike | None = None,
) -> SinkWrite:
    """
    Validates ``mode`` against ``target``'s capabilities and builds a ``SinkWrite``.

    Whether a mode is keyed is a per-target property, not a mode-global one: a
    serializing target (a ``File``) treats every mode as an unkeyed file write and
    forbids ``keys``/``idempotency_key``, while a record store routes through the
    keyed :func:`riko.sinks.sink_write` validator.

    Args:
        target: The resolved sink target.
        mode: The sink mode, as a ``SinkMode`` or its string value.
        keys: The match keys for a keyed record target.
        idempotency_key: The dedupe key for an ``append`` on a record target.

    Returns:
        The normalized, validated write specification.

    Raises:
        ValueError: When ``mode`` is unsupported by the target, or a serializing
            target is given ``keys``/``idempotency_key``.

    Examples:
        >>> from riko.targets import File, build_write
        >>>
        >>> build_write(File("out.csv"), "append")
        SinkWrite(mode=<SinkMode.APPEND: 'append'>, keys=(), idempotency_key=())

    """
    caps = target.capabilities()
    resolved = SinkMode(mode)

    if resolved not in caps.modes:
        valid = ", ".join(sorted(m.value for m in caps.modes))
        raise ValueError(
            f"the sink target does not support the '{resolved.value}' mode; "
            f"supported: {valid}"
        )
    elif caps.serializes and (keys is not None or idempotency_key is not None):
        raise ValueError(
            "a serializing sink target forbids 'keys' and 'idempotency_key'"
        )
    elif caps.serializes:
        write = SinkWrite(resolved)
    else:
        write = sink_write(resolved, keys=keys, idempotency_key=idempotency_key)

    return write


def resolve_target(dest: Destination, **conf: object) -> SinkTarget:
    """
    Normalizes a destination argument into a ``SinkTarget``.

    A ``SinkTarget`` is returned unchanged; a path string or ``Path`` becomes a
    ``File``. Named registry sinks are deferred until a second built-in sink
    exists, so every string is currently treated as a file path.

    Args:
        dest: A ``SinkTarget``, or a path string/``Path``.
        conf: Extra keyword configuration for a constructed ``File`` (e.g.
            ``format``).

    Returns:
        The resolved sink target.

    Raises:
        TypeError: When ``dest`` is neither a ``SinkTarget`` nor a path.

    Examples:
        >>> from riko.targets import File, resolve_target
        >>>
        >>> resolve_target("out.csv")
        File(url='out.csv', format=None)
        >>> resolve_target(File("out.json")).url
        'out.json'

    """
    if isinstance(dest, SinkTarget):
        target: SinkTarget = dest
    elif isinstance(dest, str | Path):
        target = File(dest, **conf)  # pyright: ignore[reportArgumentType]
    else:
        raise TypeError(f"cannot resolve a sink target from {dest!r}")

    return target


def resolve_format(url: str | Path | None, fmt: str | None) -> str:
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
        'jsonl'
        >>> resolve_format("out.txt", None)
        'json'

    """
    if fmt:
        resolved = fmt
    else:
        ext = Path(str(url)).suffix.lstrip(".").lower()
        resolved = ext if ext in _KNOWN_FORMATS else "json"

    return resolved


@dataclass(slots=True)
class _FileWriter:
    """
    A file writer driven by a subscriber's ``on_receive`` side-effect.

    A streamable format (``csv``/``jsonl``) is written incrementally as each item
    arrives; any other format buffers every item and writes one document when the
    publisher completes.

    Attributes:
        target: The resolved file target.
        mode: ``append`` or ``replace``.
        fmt: The resolved serialization format.
        stream: Whether items are written incrementally.

    """

    target: SinkTarget
    mode: SinkMode
    fmt: str
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
            self.target.deliver(self._buffer, SinkWrite(self.mode), fmt=self.fmt)

    def _write_one(self, item: Item) -> None:
        """Appends a single item as a ``csv`` row or a ``jsonl`` line."""
        from meza import convert as cv  # noqa: PLC0415
        from meza import io  # noqa: PLC0415

        file_mode = FILE_OPEN_MODES[self.mode] if not self._started else "ab"

        if self.fmt == "csv":
            content = cv.records2csv([dict(item)], skip_header=self._started)
        else:
            content = json.dumps(dict(item), default=str) + "\n"

        io.write(str(self._url), content, mode=file_mode)
        self._started = True

    @property
    def _url(self) -> str | Path:
        """The destination path of the underlying file target."""
        return getattr(self.target, "url", "")


def file_writer(
    dest: Destination,
    *,
    mode: SinkMode | str = SinkMode.APPEND,
    fmt: str | None = None,
    stream: bool | None = None,
) -> _FileWriter:
    """
    Builds the ``on_receive`` file writer the ``write`` verb desugars onto.

    Streamability is inferred from the resolved format (and therefore the
    extension) unless ``stream`` overrides it.

    Args:
        dest: A path, or a ``SinkTarget``.
        mode: ``append`` or ``replace``; the keyed record modes are rejected.
        fmt: A serialization format override, else derived from the extension.
        stream: Forces incremental (``True``) or buffered (``False``) writes;
            ``None`` infers it from the format.

    Returns:
        The configured file writer.

    Raises:
        ValueError: When ``mode`` is not ``append`` or ``replace``.

    Examples:
        >>> from riko.targets import file_writer
        >>>
        >>> file_writer("out.jsonl").stream
        True
        >>> file_writer("out.json").stream
        False

    """
    target = resolve_target(dest)
    resolved_mode = SinkMode(mode)

    if resolved_mode not in FILE_OPEN_MODES:
        valid = ", ".join(m.value for m in FILE_OPEN_MODES)
        raise ValueError(f"the 'write' verb supports only the {valid} modes")

    resolved_fmt = resolve_format(getattr(target, "url", None), fmt)
    streaming = stream if stream is not None else resolved_fmt in STREAMABLE_FORMATS
    return _FileWriter(target, resolved_mode, resolved_fmt, streaming)


__all__ = [
    "FILE_OPEN_MODES",
    "STREAMABLE_FORMATS",
    "Destination",
    "File",
    "SinkCapabilities",
    "SinkResult",
    "SinkTarget",
    "build_write",
    "file_writer",
    "resolve_format",
    "resolve_target",
]
