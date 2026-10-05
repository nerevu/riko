# vim: sw=4:ts=4:expandtab
"""
Stream export and the catalog of serialization formats.

Examples:

    Basic usage::

        >>> from riko import export
        >>>
        >>> items = [{"x": 1}, {"x": 2}]
        >>> export(items, "csv").getvalue().splitlines()
        ['x', '1', '2']

"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, Literal, TextIO, cast, overload

from meza import io

from riko.io._serialization import CONVERSION_FUNCS, serialize_records
from riko.types._enums import Formats

if TYPE_CHECKING:
    from collections.abc import Iterable
    from io import StringIO

    from riko.definitions._write import ExportType
    from riko.types._streams import Item, Items
    from riko.types._wrappers import ConversionOutput

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


@overload
def export(items: Items) -> list[Item]: ...  # noqa: E704
@overload
def export(items: Items, **kwargs: Any) -> list[Item]: ...  # noqa: E704
@overload  # noqa: E302
def export(  # noqa: E704
    items: Items, type_: Literal["list"], **kwargs: Any
) -> list[Item]: ...
@overload  # noqa: E302
def export(  # noqa: E704
    items: Items, type_: Literal["tuple"], **kwargs: Any
) -> tuple[Item]: ...
@overload  # noqa: E302
def export(  # noqa: E704
    items: Items,
    type_: Literal[
        "csv", "json", "geojson", Formats.CSV, Formats.JSON, Formats.GEOJSON
    ],
    f: str,
    **kwargs: Any,
) -> int: ...
@overload  # noqa: E302
def export(  # noqa: E704
    items: Items,
    type_: Literal[
        "csv", "json", "geojson", Formats.CSV, Formats.JSON, Formats.GEOJSON
    ],
    f: None = ...,
    **kwargs: Any,
) -> StringIO: ...
@overload  # noqa: E302
def export(  # noqa: E704
    items: Items,
    type_: Literal["ofx", "qif", Formats.OFX, Formats.QIF],
    f: str,
    **kwargs: Any,
) -> int: ...
@overload  # noqa: E302
def export(  # noqa: E704
    items: Items,
    type_: Literal["ofx", "qif", Formats.OFX, Formats.QIF],
    f: None = ...,
    **kwargs: Any,
) -> Iterable[str]: ...
@overload  # noqa: E302
def export(  # noqa: E704
    items: Items, type_: ExportType = ..., **kwargs: Any
) -> StringIO | Items | Iterable[str] | None: ...
def export(  # noqa: E302
    items: Items,
    type_: ExportType = "list",
    f: str | TextIO | None = None,
    **kwargs: Any,
) -> int | ConversionOutput | Items | None:
    """
    Converts a stream to ``type_``, optionally writing it to ``f``.

    Args:

        items: The stream to convert.

        type_: An ``export`` target. ``list``/``tuple`` return the records
            themselves; a ``Formats`` value serializes.

        f: Destination path or file object. When given, the serialized output is
            written there and the byte count is returned instead.

        kwargs: Passed through to the underlying converter and writer.

    Returns:

        The records for ``list``/``tuple``, a ``StringIO`` for a serializing
        target, or the number of bytes written when ``f`` is given.

    Raises:

        ValueError: If ``type_`` is not a known target.

    Examples:

        >>> items = [{"x": 1}, {"x": 2}]
        >>>
        >>> export(items)
        [{'x': 1}, {'x': 2}]
        >>> export(items, "csv").getvalue().splitlines()
        ['x', '1', '2']

    """
    result: int | ConversionOutput | Items | None

    if type_ in {"list", "tuple"}:
        result = tuple(items) if type_ == "tuple" else list(items)
    else:
        fmt = cast("Formats", type_)
        serialized = serialize_records(items, fmt, **kwargs)
        result = cast("int", io.write(f, serialized, **kwargs)) if f else serialized

    return result
