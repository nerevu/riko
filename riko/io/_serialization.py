"""Serializes record streams into supported output formats."""

from __future__ import annotations

from functools import partial
from itertools import chain
from typing import TYPE_CHECKING

from meza import convert as cv

from riko.coercion._mapping import validate_dict
from riko.types._enums import Formats

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

    from riko.types._streams import RikoItems
    from riko.types._wrappers import ConversionFunc, ConversionOutput


def records2ofx(items: RikoItems, **_: object) -> Iterable[str]:
    """Serializes records as OFX. Registered only with the ``finance`` extra."""
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


def records2qif(items: RikoItems, **_: object) -> Iterable[str]:
    """Serializes records as QIF. Registered only with the ``finance`` extra."""
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


records2json = lambda items, **kwargs: cv.records2json(list(items), **kwargs)

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


def convert_records(
    records: RikoItems, fmt: Formats, **kwargs: object
) -> ConversionOutput:
    """Serializes ``records`` with the resolved ``Formats`` converter."""
    items = map(validate_dict, records)

    try:
        result = CONVERSION_FUNCS[fmt](items, **kwargs)
    except StopIteration:
        result = iter("")
    except KeyError as e:
        valid = ", ".join([*map(str, CONVERSION_FUNCS), "list", "tuple"])
        msg = f"Unsupported export format: {fmt}. Must be one of: {valid}."
        raise ValueError(msg) from e

    return result
