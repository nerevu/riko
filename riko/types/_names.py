from collections.abc import Iterable
from enum import StrEnum


class ModuleName(StrEnum):
    """A type-safe module name."""


class Formats(StrEnum):
    """How a write serializes records to a destination."""

    CSV = "csv"
    GEOJSON = "geojson"
    JSON = "json"
    JSONL = "jsonl"
    OFX = "ofx"
    QIF = "qif"


type ModuleNameLike = str | ModuleName
type KeyLike = str | Iterable[str]
type FmtLike = Formats | str
