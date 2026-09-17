# vim: sw=4:ts=4:expandtab
"""
The built-in ``FileTarget`` and write preparation.

``FileTarget`` is the one built-in target that implements ``SupportsWrite``. It
serializes records with a ``Formats`` converter and writes a path.

``prepare_write`` resolves a destination to a target, reads the target's capabilities,
normalizes the keys, performs validation.

Examples:

    Basic usage::

        >>> from riko.definitions._targets import prepare_write
        >>>
        >>> prepared = prepare_write("out.csv")
        >>> prepared.fmt
        <Formats.CSV: 'csv'>
        >>> prepared.operation.mode
        <WriteMode.REPLACE: 'replace'>

"""

from dataclasses import dataclass
from pathlib import Path
from typing import ClassVar

from riko.types._enums import Backends, FmtLike, Formats, KeyLike
from riko.types._io import PathLike, PathLikeType
from riko.types._targets import SupportsWrite

from ._write import (
    Destination,
    PreparedWrite,
    WriteCapabilities,
    WriteMode,
    WriteOperation,
)

_FILE_APPEND_FORMATS: frozenset[Formats] = frozenset({Formats.CSV, Formats.JSONL})
_FILE_INCREMENTAL_FORMATS: frozenset[Formats] = frozenset({Formats.CSV, Formats.JSONL})


def resolve_keys(value: KeyLike | None) -> tuple[str, ...]:
    """
    Normalizes ``value`` into a tuple of keys.

    A bare string is wrapped; any iterable is materialized as-is.

    Args:

        value: One key, an iterable of keys, or ``None``.

    Returns:

        The keys as a tuple, empty when ``value`` is ``None``.

    Raises:

        ValueError: When a key is empty, or the keys contain a duplicate.

    Examples:

        >>> resolve_keys("id")
        ('id',)
        >>> resolve_keys(["a", "b"])
        ('a', 'b')
        >>> resolve_keys(None)
        ()

    """
    if value is None:
        keys: tuple[str, ...] = ()
    else:
        keys = (value,) if isinstance(value, str) else tuple(value)

        if any(not key for key in keys):
            raise ValueError("write keys must be non-empty strings")

        if len(set(keys)) != len(keys):
            raise ValueError(f"duplicate write keys are not allowed: {keys!r}")

    return keys


def validate_target_mode(
    target: SupportsWrite,
    mode: WriteMode,
    capabilities: WriteCapabilities,
    *,
    keys: tuple[str, ...] = (),
) -> None:
    """
    Validates the ``(target, mode, keys)`` triple against ``capabilities``.

    A match-keyed mode requires keys; a mode outside the keyed sets forbids them; an
    idempotent mode accepts keys but does not require them.

    Args:

        target: The resolved target, named in error messages.
        mode: The resolved write mode.
        capabilities: The resolved ``(target × fmt)`` capabilities.
        keys: The normalized keys.

    Raises:

        ValueError: When the mode is unsupported, keys are given for an unkeyed
            mode, or a match-keyed mode is missing keys.

    """
    name = target.__class__.__name__

    if mode not in capabilities.modes:
        supported = ", ".join(sorted(m.value for m in capabilities.modes))
        msg = f"{name} does not support the {mode.value!r} mode; {supported=}"
    elif keys and mode not in capabilities.keyed_modes:
        msg = f"{name} forbids 'keys' for the {mode.value!r} mode"
    elif mode in capabilities.match_keyed_modes and not keys:
        msg = f"{name} requires 'keys' for the {mode.value!r} mode"
    else:
        msg = ""

    if msg:
        raise ValueError(msg)


def prepare_write(
    dest: Destination,
    mode: WriteMode | str = WriteMode.REPLACE,
    *,
    fmt: FmtLike | None = None,
    keys: KeyLike | None = None,
) -> PreparedWrite:
    """
    Resolves, validates, and binds a write into a ``PreparedWrite``.

    The target reports its ``(target × fmt)`` capabilities; the keys are
    normalized; the ``(target, mode, keys)`` triple is validated; and the result is a
    fully validated, execution-ready specification.

    Args:

        dest: A path, ``Path``, or ``SupportsWrite`` target.
        mode: The write mode, as a ``WriteMode`` or its string value.
        fmt: The serialization format override for a serializing target.
        keys: The unified keys, interpreted per the target's capabilities.

    Returns:

        The target-bound, validated write specification.

    Raises:

        ValueError: For an invalid ``(dest, mode, keys, fmt)`` combination.

    Examples:

        >>> from riko.definitions._targets import FileTarget, prepare_write
        >>>
        >>> prepared = prepare_write(FileTarget("out.csv"), "append")
        >>> prepared.operation.mode
        <WriteMode.APPEND: 'append'>
        >>> prepared.fmt
        <Formats.CSV: 'csv'>

    """
    target = resolve_target(dest)
    resolved_mode = WriteMode(mode)
    capabilities = target.capabilities(fmt)
    normalized_keys = resolve_keys(keys)

    validate_target_mode(target, resolved_mode, capabilities, keys=normalized_keys)
    operation = WriteOperation(resolved_mode, keys=normalized_keys)
    return PreparedWrite(target, operation, capabilities)


def resolve_target(dest: Destination, **kwargs: str) -> SupportsWrite:
    """
    Normalizes a destination argument into a ``SupportsWrite`` target.

    A ``SupportsWrite`` target is returned unchanged; a path string or ``Path`` becomes
    a ``FileTarget``. Named registry targets are deferred until a second built-in target
    exists, so every string is currently treated as a file path.

    Args:

        dest: The destination location.
        kwargs: Extra keyword configuration for a constructed ``FileTarget``.

    Returns:

        The resolved ``SupportsWrite`` target.

    Raises:

        TypeError: When ``dest`` is neither a ``SupportsWrite`` target nor a path.

    Examples:

        >>> from riko.definitions._targets import resolve_target
        >>>
        >>> resolve_target("out.csv")
        FileTarget(dest='out.csv', fmt=None)

    """
    if isinstance(dest, SupportsWrite):
        target: SupportsWrite = dest
    elif isinstance(dest, PathLikeType):
        target = FileTarget(dest, **kwargs)
    else:
        raise TypeError(f"cannot resolve a target from {dest!r}")

    return target


def resolve_format(dest: PathLike | None, fmt: FmtLike | None) -> Formats:
    """
    Resolves a serialization format from an explicit ``fmt``.

    An explicit ``fmt`` wins. Otherwise the dest's lowercased extension is used.
    Anything else falls back to ``json``.

    Args:

        dest: The destination path, or ``None``.
        fmt: The explicit format, or ``None`` to derive one.

    Returns:

        The resolved format name.

    Raises:

        ValueError: When the resolved format is not a known Formats.

    Examples:

        >>> from riko.definitions._targets import resolve_format
        >>>
        >>> resolve_format("out.jsonl", None)
        <Formats.JSONL: 'jsonl'>
        >>> resolve_format("out", None)
        <Formats.JSON: 'json'>

    """
    if fmt:
        resolved = fmt
    else:
        ext = Path(str(dest)).suffix.lstrip(".").lower()
        resolved = ext or Formats.JSON

    return Formats(resolved)


@dataclass(frozen=True, slots=True)
class FileTarget:
    """
    A file target: serialize records with a ``Formats`` converter and write a path.

    The target owns its format-dependent behavior: a line-oriented format (csv/jsonl)
    is appendable and delivered incrementally; a whole-document format
    (json/geojson/ofx/qif) supports ``replace`` only and is delivered as one framed
    document. Those are ``target × fmt`` facts private to ``FileTarget``, not global
    properties of a ``Formats`` value.

    Attributes:

        backend: The backend this target serves.
        dest: The destination path.
        fmt: The ``Formats`` converter name, or ``None`` to derive it from the
            path extension (default: ``json``).

    Examples:

        >>> from riko.definitions._targets import FileTarget
        >>>
        >>> FileTarget("out.jsonl").capabilities().incremental
        True

    """

    backend: ClassVar[Backends] = Backends.FILE
    dest: PathLike
    fmt: FmtLike | None = None

    def capabilities(self, fmt: FmtLike | None = None) -> WriteCapabilities:
        """
        Reports format-aware file capabilities.

        A line-oriented format (csv/jsonl) supports ``append`` and ``replace`` and is
        incremental; a whole-document format supports ``replace`` only and is not,
        because appending would concatenate two documents into invalid output.

        Args:

            fmt: The serialization format override, else ``fmt``, else derived
                from the path extension.

        Returns:

            The file's supported modes and serialization behavior.

        Examples:

            >>> from riko.definitions._targets import FileTarget
            >>> from riko.definitions._write import WriteMode
            >>>
            >>> capabilities = FileTarget("out.jsonl").capabilities()
            >>> capabilities.serializes, capabilities.appendable
            (True, True)
            >>> WriteMode.APPEND in FileTarget("out.json").capabilities().modes
            False

        """
        resolved_fmt = resolve_format(self.dest, fmt or self.fmt)
        modes = {WriteMode.REPLACE}

        if resolved_fmt in _FILE_APPEND_FORMATS:
            modes.add(WriteMode.APPEND)

        return WriteCapabilities(
            modes=frozenset(modes),
            fmt=resolved_fmt,
            incremental=resolved_fmt in _FILE_INCREMENTAL_FORMATS,
        )


__all__ = [
    "FileTarget",
    "prepare_write",
    "resolve_format",
    "resolve_keys",
    "resolve_target",
    "validate_target_mode",
]
