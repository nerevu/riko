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
``WriteOperation`` directly rather than through the keyed ``???`` validator.

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

Attributes:

    FILE_OPEN_MODES: Maps each file ``WriteMode`` to its file-open mode string.
    STREAMABLE_FORMATS: The line-oriented formats written incrementally.

"""

from dataclasses import dataclass
from pathlib import Path

from riko._formats import resolve_format
from riko._iterutils import listize
from riko.types._write import (
    APPENDABLE_FORMATS,
    STREAMABLE_FORMATS,
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


def normalize_keys(value: KeyLike | None) -> tuple[str, ...]:
    """Normalizes ``value`` into a tuple of names, wrapping a bare string."""
    empty_value: tuple[str, ...] = ()
    return tuple(listize(empty_value if value is None else value))


def validate_target_mode(
    target: WriteTarget,
    mode: WriteMode,
    capabilities: WriteCapabilities,
    *,
    keys: tuple[str, ...] = (),
) -> None:
    """
    Validates ``mode`` against ``target``'s capabilities.

    Raises:

        ValueError when ``mode`` is unsupported by the target, or a non-keyed mode is
            given ``key``/``key``.

    """
    keyed = mode in capabilities.keyed_modes
    match_keyed = mode in capabilities.match_keyed_modes
    target_name = target.__class__.__name__

    if mode not in capabilities.modes:
        supported = ", ".join(sorted(m.value for m in capabilities.modes))
        msg = f"{target_name} does not support '{mode.value}' mode; {supported=}"
    elif keys and not keyed:
        msg = f"{target_name} does not support {keys=} for '{mode.value}' mode"
    elif match_keyed and not keys:
        msg = f"{target_name} '{mode.value}' mode requires keys"
    else:
        msg = ""

    if msg:
        raise ValueError(msg)


def prepare_write(
    dest: Destination,
    *,
    mode: WriteMode | str = WriteMode.REPLACE,
    fmt: Formats | str | None = None,
    key: KeyLike | None = None,
) -> PreparedWrite:
    """
    Validates ``mode`` against ``target``' and builds a ``PreparedWrite``.

    Whether a mode is keyed is a per-target property, not a mode-global one. A
    serializing target (e.g., ``File``) treats every mode as an unkeyed write and
    forbids ``keys``/``key``. A record store routes through the keyed
    :func:`riko.???` validator. For a serializing target, the
    valid modes also depend on ``fmt``. Appending to a whole-document format (e.g.,
    json) is rejected here.

    Args:

        target: The resolved write target.
        mode: The write mode, as a ``WriteMode`` or its string value.
        key: The dedupe key used for match_keyed or idempotent modes.
        fmt: The serialization format used to validate the mode.

    Returns:

        The normalized, validated write specification.

    Raises:

        ValueError: for invalid ``mode``/``target``/``fmt`` combinations

    Examples:

        >>> from riko.targets import File, build_write
        >>>
        >>> prepare_write(File("out.csv"), "append")
        PreparedWrite()

    """
    target = resolve_target(dest)
    resolved_mode = WriteMode(mode)
    capabilities = target.capabilities(fmt)
    keys = normalize_keys(key)

    validate_target_mode(target, resolved_mode, capabilities, keys=keys)
    operation = WriteOperation(resolved_mode, keys=keys)
    return PreparedWrite(target, operation, capabilities)


def resolve_target(dest: Destination, **kwargs: str) -> WriteTarget:
    """
    Normalizes a destination argument into a ``WriteTarget``.

    A ``WriteTarget`` is returned unchanged; a path string or ``Path`` becomes a
    ``File``. Named registry targets are deferred until a second built-in target
    exists, so every string is currently treated as a file path.

    Args:

        dest: The destination location.
        kwargs: Extra keyword configuration for a constructed ``File`` (e.g. ``format``).

    Returns:

        The resolved write target.

    Raises:

        TypeError: When ``dest`` is neither a ``WriteTarget`` nor a path.

    Examples:

        >>> from riko.targets import File, resolve_target
        >>>
        >>> target = resolve_target("out.csv")
        >>> target
        File(url='out.csv', format=None)
        >>> target.url
        'out.json'

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

        >>> from riko import get_temp_file
        >>> from riko.targets import File
        >>> from riko.types._write import WriteMode, WriteOperation
        >>>
        >>> with get_temp_file() as fp:
        ...     op = WriteOperation(WriteMode.REPLACE)
        ...     result = File(fp.name).deliver([{"x": 1}], op)
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

        Args:

            fmt: The serialization format override, else ``format``, else derived
                from the path extension.

        Returns:

            The file's supported modes and serialization behavior.

        Examples:

            >>> from riko.targets import File
            >>> from riko.types._write import WriteMode
            >>>
            >>> capabilities = File("out.jsonl").capabilities()
            >>> capabilities.serializes
            True
            >>> WriteMode.APPEND in capabilities.modes
            True
            >>> WriteMode.APPEND in File("out.json").capabilities().modes
            False

        """
        resolved_fmt = resolve_format(self.url, fmt or self.format)
        modes = {WriteMode.REPLACE}

        if resolved_fmt in APPENDABLE_FORMATS:
            modes.add(WriteMode.APPEND)

        return WriteCapabilities(
            modes=frozenset(modes),
            fmt=resolved_fmt,
            serializes=True,
            streamable=resolved_fmt in STREAMABLE_FORMATS,
            appendable=resolved_fmt in APPENDABLE_FORMATS,
        )


__all__ = [
    "Destination",
    "File",
    "Formats",
    "WriteCapabilities",
    "WriteResult",
    "WriteTarget",
    "normalize_keys",
    "prepare_write",
    "resolve_format",
    "resolve_target",
    "validate_target_mode",
]
