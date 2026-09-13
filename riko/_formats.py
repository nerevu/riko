from collections.abc import Iterable
from functools import partial
from itertools import chain
from pathlib import Path

from meza import convert as cv

from riko.types._guards import is_mapping
from riko.types._streams import RikoItems
from riko.types._wrappers import ConversionFunc, ConversionOutput
from riko.types._write import Formats

try:
    from csv2ofx.ofx import OFX
except ModuleNotFoundError:
    mapping = OFX = QIF = gen_data = None
else:
    from csv2ofx.mappings.default import mapping
    from csv2ofx.qif import QIF
    from csv2ofx.utils import gen_data


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


CONVERSION_FUNCS: dict[Formats, ConversionFunc] = {
    # "array": cv.records2array,
    Formats.CSV: cv.records2csv,
    # "dataframe": cv.records2df,
    Formats.GEOJSON: cv.records2geojson,
    # 'ical': cv.records2ical,
    Formats.JSON: cv.records2json,
    Formats.JSONL: partial(cv.records2json, newline=True),
    # 'kml': cv.records2kml,
}


if OFX is not None:
    CONVERSION_FUNCS[Formats.OFX] = records2ofx
    CONVERSION_FUNCS[Formats.QIF] = records2qif


def resolve_format(url: str | Path | None, fmt: Formats | str | None) -> Formats:
    """
    Resolves a serialization format from an explicit ``fmt``.

    An explicit ``fmt`` wins. Otherwise the url's lowercased extension is used.
    Anything else falls back to ``json``.

    Args:

        url: The destination path, or ``None``.
        fmt: The explicit format, or ``None`` to derive one.

    Returns:

        The resolved format name.

    Raises:

        ValueError: When the resolved format is not a known Formats.

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


def convert_records(
    records: RikoItems, fmt: Formats, **kwargs: object
) -> ConversionOutput:
    """Serializes ``records`` with the resolved ``Formats`` converter."""
    items = [dict(item) for item in records if is_mapping(item)]

    try:
        result = CONVERSION_FUNCS[fmt](items, **kwargs)
    except StopIteration:
        result = iter("")

    return result
