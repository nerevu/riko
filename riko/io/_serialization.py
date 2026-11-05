"""Serializes item streams into supported output formats."""

from __future__ import annotations

from functools import partial
from inspect import signature
from io import StringIO
from itertools import chain
from json import dumps
from typing import TYPE_CHECKING, Final

from meza import convert as cv
from meza import fntools as ft

from riko.base._guards import require_mapping
from riko.base._iterutils import sort_stably
from riko.base._typing import resolve_enum
from riko.types._enums import Formats
from riko.types._frozendict import thaw

try:
    from csv2ofx.ofx import OFX
except ModuleNotFoundError:
    mapping = OFX = QIF = gen_data = None
else:
    from csv2ofx.mappings.default import mapping
    from csv2ofx.qif import QIF
    from csv2ofx.utils import gen_data

if TYPE_CHECKING:
    from collections.abc import Iterable

    from riko.types._streams import Items
    from riko.types._wrappers import ConversionFunc, ConversionOutput


def records2ofx(items: Items, **_: object) -> Iterable[str]:
    """Serializes items as OFX. Registered only with the ``finance`` extra."""
    if not (OFX and gen_data):
        raise RuntimeError(
            "The ofx converter is unavailable. Install riko with the 'finance' extra."
        )

    ofx = OFX(mapping)
    groups = ofx.gen_groups(items)
    trxns = ofx.gen_trxns(groups)
    cleaned_trxns = ofx.clean_trxns(trxns)
    data = gen_data(cleaned_trxns)
    return chain(ofx.header(), ofx.gen_body(data), ofx.footer())


def records2qif(items: Items, **_: object) -> Iterable[str]:
    """Serializes items as QIF. Registered only with the ``finance`` extra."""
    if not (QIF and gen_data):
        raise RuntimeError(
            "The qif converter is unavailable. Install riko with the 'finance' extra."
        )

    qif = QIF(mapping)
    groups = qif.gen_groups(items)
    trxns = qif.gen_trxns(groups)
    cleaned_trxns = qif.clean_trxns(trxns)
    data = gen_data(cleaned_trxns)
    return chain(qif.gen_body(data), qif.footer())


class _SortedSetEncoder(ft.CustomEncoder):
    """Encodes a set as a sorted array, so output does not depend on hash order."""

    def default(self, obj: object) -> object:
        if isinstance(obj, (set, frozenset)):
            result = sort_stably(obj)
        else:
            result = super().default(obj)

        return result


def records2json(items: Items, *, newline: bool = False, **kwargs: object) -> StringIO:
    """
    Serializes items as a JSON array, or as JSON lines when ``newline`` is set.

    Keys are sorted, non-ASCII text is kept as is, a set is written as a sorted
    array, and a date as its ISO string.

    Args:

        items: The items to serialize.
        newline: Whether to write one JSON object per line instead of an array.
        **kwargs: Extra keyword arguments forwarded to ``json.dumps``.

    Returns:

        A buffer holding the serialized items.

    Examples:

        >>> from datetime import date
        >>>
        >>> records2json([{"tags": {"b", "a"}}]).read()
        '[{"tags": ["a", "b"]}]'
        >>> records2json([{"x": 1}, {"x": 2}], newline=True).read()
        '{"x": 1}\\n{"x": 2}'
        >>> records2json([{"on": date(2026, 10, 15)}]).read()
        '[{"on": "2026-10-15"}]'

    """
    options = {"sort_keys": True, "ensure_ascii": False, **kwargs}
    dump = partial(dumps, cls=_SortedSetEncoder, **options)
    return StringIO("\n".join(map(dump, items)) if newline else dump(list(items)))


CONVERSION_FUNCS: dict[Formats, ConversionFunc] = {
    # "array": cv.records2array,
    Formats.CSV: cv.records2csv,
    # "dataframe": cv.records2df,
    Formats.GEOJSON: cv.records2geojson,
    # 'ical': cv.records2ical,
    Formats.JSON: records2json,
    Formats.JSONL: partial(records2json, newline=True),
    # 'kml': cv.records2kml,
    **({Formats.OFX: records2ofx, Formats.QIF: records2qif} if OFX is not None else {}),
}

ENCODING_FORMATS: Final[frozenset[Formats]] = frozenset(
    fmt
    for fmt, convert in CONVERSION_FUNCS.items()
    if "encoding" in signature(convert).parameters
)

GEOJSON_CRS = "urn:ogc:def:crs:OGC:1.3:CRS84"


def _require_converter(fmt: Formats) -> ConversionFunc:
    """Requires a converter to be registered for ``fmt``."""
    if (convert := CONVERSION_FUNCS.get(fmt)) is None:
        raise ValueError(f"the {fmt} format requires the finance extra")

    return convert


def require_conversion_format(fmt: str, what: str = "conversion format") -> Formats:
    """
    Requires ``fmt`` to name a format with a registered converter.

    Args:

        fmt: A format name or ``Formats`` member.
        what: How error messages name the value.

    Returns:

        The matching ``Formats`` member.

    Raises:

        ValueError: If ``fmt`` names no format, or its converter needs an extra that
            is not installed.

    Examples:

        >>> require_conversion_format("csv")
        <Formats.CSV: 'csv'>
        >>> require_conversion_format("xml")
        Traceback (most recent call last):
        ValueError: Invalid conversion format: 'xml'. Expected one of ...

    """
    member = resolve_enum(Formats, fmt, what, error=ValueError)
    _require_converter(member)
    return member


def build_empty_geojson(*, crs: object = GEOJSON_CRS, **_: object) -> StringIO:
    """
    Builds a GeoJSON feature collection with no features.

    Kwargs:

        crs: The coordinate reference system name.

    Returns:

        A buffer holding the serialized, featureless collection.

    Examples:

        >>> from json import loads
        >>>
        >>> collection = loads(build_empty_geojson().read())
        >>> collection["features"]
        []
        >>> collection["crs"]["properties"]["name"]
        'urn:ogc:def:crs:OGC:1.3:CRS84'

    """
    crs_name = {"type": "name", "properties": {"name": crs}}
    output = {"type": "FeatureCollection", "features": [], "crs": crs_name}
    return StringIO(dumps(output))


def serialize_items(items: Items, fmt: Formats, **kwargs: object) -> ConversionOutput:
    """
    Serializes ``items`` with the converter registered for ``fmt``.

    An empty stream serializes as nothing, except GeoJSON, which becomes a collection
    with no features.

    Args:

        items: The items to serialize.
        fmt: The output format.
        **kwargs: Extra keyword arguments forwarded to the converter.

    Returns:

        The serialized items.

    Raises:

        ValueError: If no converter is registered for ``fmt``.

    Examples:

        >>> from json import loads
        >>>
        >>> serialize_items([{"x": 1}], Formats.JSON).read()
        '[{"x": 1}]'
        >>> loads(serialize_items([], Formats.GEOJSON).read())["features"]
        []

    """
    convert = _require_converter(fmt)
    require = partial(require_mapping, what="item", error=TypeError)
    thawed = map(thaw, map(require, items))
    first = next(thawed, None)

    if first is None and fmt == Formats.GEOJSON:
        result = build_empty_geojson(**kwargs)
    else:
        stream = thawed if first is None else chain([first], thawed)

        try:
            result = convert(stream, **kwargs)
        except StopIteration:
            result = iter("")

    return result
