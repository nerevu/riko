# vim: sw=4:ts=4:expandtab
"""
riko.targets
~~~~~~~~~~~~

Write target adapters (PRIVATE).

A ``WriteTarget`` is a destination that reports what it can write. ``File`` is the
one built-in target: it serializes records with a ``Formats`` converter and writes a
path. External providers (Airtable, databases, …) supply their own ``WriteTarget``
implementations outside core. ``resolve_target`` normalizes a destination argument
(a path string or a target object) into a ``WriteTarget``.

Preparation is generic over ``WriteTarget`` and validated in one place:
``prepare_write`` resolves the target, resolves its ``(target × fmt)``
capabilities, normalizes the keys, validates the ``(target, mode, keys)`` triple,
and returns a ``PreparedWrite``. What a mode's keys mean — record-match identity vs.
idempotency identity — is decided by the target's capabilities, so the caller passes
a single unified ``keys`` and never distinguishes the two.

Examples:

    Basic usage::

        >>> from riko.targets import File, resolve_target
        >>>
        >>> resolve_target("out.csv")
        File(url='out.csv', fmt=None)

"""

from dataclasses import dataclass
from pathlib import Path

from riko._formats import resolve_format
from riko.types._write import (
    Destination,
    Formats,
    KeyLike,
    PreparedWrite,
    WriteCapabilities,
    WriteMode,
    WriteOperation,
    WriteResult,
    WriteTarget,
)

_FILE_APPEND_FORMATS: frozenset[Formats] = frozenset({Formats.CSV, Formats.JSONL})
_FILE_INCREMENTAL_FORMATS: frozenset[Formats] = frozenset({Formats.CSV, Formats.JSONL})


def normalize_keys(value: KeyLike | None) -> tuple[str, ...]:
    """
    Normalizes ``value`` into a tuple of keys, preserving caller ordering.

    A bare string is wrapped; any iterable is materialized as-is.

    Args:

        value: One key, an iterable of keys, or ``None``.

    Returns:

        The keys as a tuple, empty when ``value`` is ``None``.

    Raises:

        ValueError: When a key is empty, or the keys contain a duplicate.

    Examples:

        >>> normalize_keys("id")
        ('id',)
        >>> normalize_keys(["a", "b"])
        ('a', 'b')
        >>> normalize_keys(None)
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
    target: WriteTarget,
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

        target: The resolved write target, named in error messages.
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
    fmt: Formats | str | None = None,
    keys: KeyLike | None = None,
) -> PreparedWrite:
    """
    Resolves, validates, and binds a write into a ``PreparedWrite``.

    The target reports its ``(target × fmt)`` capabilities; the keys are
    normalized; the ``(target, mode, keys)`` triple is validated; and the result is a
    fully validated, execution-ready specification.

    Args:

        dest: A path, ``Path``, or ``WriteTarget``.
        mode: The write mode, as a ``WriteMode`` or its string value.
        fmt: The serialization format override for a serializing target.
        keys: The unified keys, interpreted per the target's capabilities.

    Returns:

        The target-bound, validated write specification.

    Raises:

        ValueError: For an invalid ``(dest, mode, keys, fmt)`` combination.

    Examples:

        >>> from riko.targets import File, prepare_write
        >>>
        >>> prepared = prepare_write(File("out.csv"), "append")
        >>> prepared.operation.mode
        <WriteMode.APPEND: 'append'>
        >>> prepared.fmt
        <Formats.CSV: 'csv'>

    """
    target = resolve_target(dest)
    resolved_mode = WriteMode(mode)
    capabilities = target.capabilities(fmt)
    normalized_keys = normalize_keys(keys)

    validate_target_mode(target, resolved_mode, capabilities, keys=normalized_keys)
    operation = WriteOperation(resolved_mode, keys=normalized_keys)
    return PreparedWrite(target, operation, capabilities)


def resolve_target(dest: Destination, **kwargs: str) -> WriteTarget:
    """
    Normalizes a destination argument into a ``WriteTarget``.

    A ``WriteTarget`` is returned unchanged; a path string or ``Path`` becomes a
    ``File``. Named registry targets are deferred until a second built-in target
    exists, so every string is currently treated as a file path.

    Args:

        dest: The destination location.
        kwargs: Extra keyword configuration for a constructed ``File``.

    Returns:

        The resolved write target.

    Raises:

        TypeError: When ``dest`` is neither a ``WriteTarget`` nor a path.

    Examples:

        >>> from riko.targets import resolve_target
        >>>
        >>> resolve_target("out.csv")
        File(url='out.csv', fmt=None)

    """
    if isinstance(dest, WriteTarget):
        target: WriteTarget = dest
    elif isinstance(dest, str | Path):
        target = File(dest, **kwargs)
    else:
        raise TypeError(f"cannot resolve a write target from {dest!r}")

    return target


@dataclass(frozen=True, slots=True)
class File:
    """
    A file target: serialize records with a ``Formats`` converter and write a path.

    The target owns its format-dependent behavior: a line-oriented format (csv/jsonl)
    is appendable and delivered incrementally; a whole-document format
    (json/geojson/ofx/qif) supports ``replace`` only and is delivered as one framed
    document. Those are ``target × fmt`` facts private to ``File``, not global
    properties of a ``Formats`` value.

    Attributes:

        url: The destination path.
        fmt: The ``Formats`` converter name, or ``None`` to derive it from the
            path extension (default: ``json``).

    Examples:

        >>> from riko.targets import File
        >>>
        >>> File("out.jsonl").capabilities().incremental
        True

    """

    url: str | Path
    fmt: str | None = None

    def capabilities(self, fmt: Formats | str | None = None) -> WriteCapabilities:
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

            >>> from riko.targets import File
            >>> from riko.types._write import WriteMode
            >>>
            >>> capabilities = File("out.jsonl").capabilities()
            >>> capabilities.serializes, capabilities.appendable
            (True, True)
            >>> WriteMode.APPEND in File("out.json").capabilities().modes
            False

        """
        resolved_fmt = resolve_format(self.url, fmt or self.fmt)
        modes = {WriteMode.REPLACE}

        if resolved_fmt in _FILE_APPEND_FORMATS:
            modes.add(WriteMode.APPEND)

        return WriteCapabilities(
            modes=frozenset(modes),
            fmt=resolved_fmt,
            incremental=resolved_fmt in _FILE_INCREMENTAL_FORMATS,
        )


__all__ = [
    "Destination",
    "File",
    "Formats",
    "PreparedWrite",
    "WriteCapabilities",
    "WriteOperation",
    "WriteResult",
    "WriteTarget",
    "normalize_keys",
    "prepare_write",
    "resolve_format",
    "resolve_target",
    "validate_target_mode",
]
