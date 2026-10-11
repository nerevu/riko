"""Serializes item streams into supported output formats."""

from __future__ import annotations

from functools import partial
from io import StringIO
from itertools import chain
from json import dumps
from typing import TYPE_CHECKING

from meza import convert as cv
from meza import fntools as ft

from riko.base._iterutils import sort_stably
from riko.types._collections import thaw
from riko.types._enums import Formats
from riko.types._guards import require_mapping

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
}


if OFX is not None:
    CONVERSION_FUNCS[Formats.OFX] = records2ofx
    CONVERSION_FUNCS[Formats.QIF] = records2qif


def serialize_items(items: Items, fmt: Formats, **kwargs: object) -> ConversionOutput:
    """Serializes ``items`` with the resolved ``Formats`` converter."""
    thawed = (thaw(require_mapping(item, "item", error=TypeError)) for item in items)

    try:
        result = CONVERSION_FUNCS[fmt](thawed, **kwargs)
    except StopIteration:
        result = iter("")
    except KeyError as e:
        valid = ", ".join([*map(str, CONVERSION_FUNCS), "list", "tuple"])
        msg = f"Unsupported export format: {fmt}. Must be one of: {valid}."
        raise ValueError(msg) from e

    return result
