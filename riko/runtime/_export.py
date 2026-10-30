# vim: sw=4:ts=4:expandtab
"""
Stream export and the serialization formats it supports.

Examples:

    Basic usage::

        >>> from riko import export
        >>>
        >>> items = [{"x": 1}, {"x": 2}]
        >>> export(items, "csv").getvalue().splitlines()
        ['x', '1', '2']

"""

from __future__ import annotations

from typing import TYPE_CHECKING, Literal, Never, TextIO, overload

from meza import io

from riko.base._config import ENCODING
from riko.base._sentinels import MISSING, MissingType
from riko.io._serialization import (
    CONVERSION_FUNCS,
    ENCODING_FORMATS,
    require_conversion_format,
    serialize_items,
)
from riko.types._enums import Formats

if TYPE_CHECKING:
    from collections.abc import Iterable
    from io import StringIO

    from riko.definitions._write import ExportType
    from riko.types._streams import Item, Items
    from riko.types._wrappers import ConversionOutput

type _Destination = str | TextIO

__all__ = ["Formats", "export", "list_formats"]


def list_formats() -> list[str]:
    """
    Collects every available serialization format, sorted.

    Only serialized representations are listed; the ``list``/``tuple`` collection
    materializations that ``export`` also accepts are not formats. ``ofx`` and
    ``qif`` are present only with the ``finance`` extra installed.

    Examples:

        >>> formats = list_formats()
        >>> formats[:4]
        ['csv', 'geojson', 'json', 'jsonl']

    """
    return sorted(map(str, CONVERSION_FUNCS))


def _resolve_option[T](value: T | MissingType, default: T) -> T:
    """Resolves an omitted writer option to its default."""
    return default if isinstance(value, MissingType) else value


def _validate_writer_options(f: _Destination | None, **options: object) -> None:
    """Validates that writer options are only given with a destination."""
    given = [name for name, value in options.items() if value is not MISSING]

    if f is None and given:
        msg = f"Writer option(s) given without a destination: {', '.join(given)}"
        raise TypeError(msg)


def _require_export_format(type_: str) -> Formats:
    """Requires ``type_`` to name an export serialization format."""
    try:
        fmt = require_conversion_format(type_, "export type")
    except ValueError as e:
        msg = str(e).replace("Expected one of ", "Expected one of list, tuple, ")
        raise ValueError(msg) from e

    return fmt


@overload
def export(
    items: Items,
    type_: Literal["list"] = ...,
    f: None = ...,
    *,
    mode: Never = ...,
    encoding: Never = ...,
    chunksize: Never = ...,
    length: Never = ...,
    bar_len: Never = ...,
    **options: object,
) -> list[Item]: ...
@overload
def export(
    items: Items,
    type_: Literal["tuple"],
    f: None = ...,
    *,
    mode: Never = ...,
    encoding: Never = ...,
    chunksize: Never = ...,
    length: Never = ...,
    bar_len: Never = ...,
    **options: object,
) -> tuple[Item]: ...
@overload
def export(
    items: Items,
    type_: Literal[
        "csv", "json", "geojson", Formats.CSV, Formats.JSON, Formats.GEOJSON
    ],
    f: _Destination,
    *,
    mode: str = ...,
    encoding: str = ...,
    chunksize: int | None = ...,
    length: int = ...,
    bar_len: int = ...,
    **options: object,
) -> int: ...
@overload
def export(
    items: Items,
    type_: Literal[
        "csv", "json", "geojson", Formats.CSV, Formats.JSON, Formats.GEOJSON
    ],
    f: None = ...,
    *,
    mode: Never = ...,
    encoding: Never = ...,
    chunksize: Never = ...,
    length: Never = ...,
    bar_len: Never = ...,
    **options: object,
) -> StringIO: ...
@overload
def export(
    items: Items,
    type_: Literal["ofx", "qif", Formats.OFX, Formats.QIF],
    f: _Destination,
    *,
    mode: str = ...,
    encoding: str = ...,
    chunksize: int | None = ...,
    length: int = ...,
    bar_len: int = ...,
    **options: object,
) -> int: ...
@overload
def export(
    items: Items,
    type_: Literal["ofx", "qif", Formats.OFX, Formats.QIF],
    f: None = ...,
    *,
    mode: Never = ...,
    encoding: Never = ...,
    chunksize: Never = ...,
    length: Never = ...,
    bar_len: Never = ...,
    **options: object,
) -> Iterable[str]: ...
@overload
def export(
    items: Items,
    type_: ExportType,
    f: _Destination,
    *,
    mode: str = ...,
    encoding: str = ...,
    chunksize: int | None = ...,
    length: int = ...,
    bar_len: int = ...,
    **options: object,
) -> int | Items: ...
@overload
def export(
    items: Items,
    type_: ExportType = ...,
    f: None = ...,
    *,
    mode: Never = ...,
    encoding: Never = ...,
    chunksize: Never = ...,
    length: Never = ...,
    bar_len: Never = ...,
    **options: object,
) -> ConversionOutput | Items: ...
def export(
    items: Items,
    type_: ExportType = "list",
    f: _Destination | None = None,
    *,
    mode: str | MissingType = MISSING,
    encoding: str | MissingType = MISSING,
    chunksize: int | MissingType | None = MISSING,
    length: int | MissingType = MISSING,
    bar_len: int | MissingType = MISSING,
    **options: object,
) -> int | ConversionOutput | Items:
    """
    Converts a stream to ``type_``, optionally writing it to ``f``.

    Args:

        items: The stream to convert.

        type_: The export type. ``list``/``tuple`` return ``items``. A ``Formats`` value
            serializes.

        f: The path or file the serialized output is written to.

    Kwargs:

        mode: The mode a destination path is opened in (default: "wb+"). Only valid with
            ``f``, like the other writer options below.

        encoding: The encoding of the written text (default: "utf-8"). A format whose
            converter takes an encoding, e.g. ``csv``, gets it too.

        chunksize: The number of characters written at a time (default: all).

        length: The expected output length used to log write progress (default: 0, no
            logging).

        bar_len: The width of the logged progress bar (default: 50).

        options: Passed through to the format's converter, e.g. ``skip_header`` for
            ``csv`` or ``indent`` for ``json``.

    Returns:

        The items for ``list``/``tuple``, a ``StringIO`` for a ``Formats`` value, or the
        number of bytes written when ``f`` is given.

    Raises:

        ValueError: If ``type_`` is neither ``list``/``tuple`` nor a known format.

        TypeError: If a writer option is given without ``f``.

    Examples:

        >>> items = [{"x": 1}, {"x": 2}]
        >>>
        >>> export(items)
        [{'x': 1}, {'x': 2}]
        >>> export(items, "csv").getvalue().splitlines()
        ['x', '1', '2']
        >>> export(items, "csv", skip_header=True).getvalue().splitlines()
        ['1', '2']
        >>> export(items, "csv", mode="w")
        Traceback (most recent call last):
        TypeError: Writer option(s) given without a destination: mode

    """
    result: int | ConversionOutput | Items
    kwargs = {"mode": mode, "encoding": encoding, "length": length, "bar_len": bar_len}
    _validate_writer_options(f, chunksize=chunksize, **kwargs)

    if type_ == "list":
        result = list(items)
    elif type_ == "tuple":
        result = tuple(items)
    elif f is None:
        result = serialize_items(items, _require_export_format(type_), **options)
    else:
        fmt = _require_export_format(type_)
        text_encoding = _resolve_option(encoding, ENCODING)

        if fmt in ENCODING_FORMATS:
            converter_options = {**options, "encoding": text_encoding}
        else:
            converter_options = options

        result = io.write(
            f,
            serialize_items(items, fmt, **converter_options),
            _resolve_option(mode, "wb+"),
            encoding=text_encoding,
            chunksize=_resolve_option(chunksize, None),
            length=_resolve_option(length, 0),
            bar_len=_resolve_option(bar_len, 50),
        )

    return result
