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


class LocationType(StrEnum):
    """The kind of lookup ``cast_location`` performs."""

    COORDINATES = "coordinates"
    CURRENCY = "currency"
    IP_ADDRESS = "ip_address"
    STREET_ADDRESS = "street_address"


class BasicCastType(StrEnum):
    """Cast types a module may set as its ``ftype``/``ptype``."""

    DATE = "date"
    DATETIME = "datetime"
    DECIMAL = "decimal"
    FLOAT = "float"
    INT = "int"
    NONE = "none"
    PASS = "pass"  # noqa: S105
    TEXT = "text"
    URL = "url"


class SortableCastType(StrEnum):
    """Cast types whose values are orderable, for sort comparisons."""

    BOOL = "bool"
    DATE = "date"
    DATETIME = "datetime"
    DECIMAL = "decimal"
    FLOAT = "float"
    INT = "int"
    PASS = "pass"  # noqa: S105
    TEXT = "text"
    URL = "url"


class CastType(StrEnum):
    """Every destination type ``cast_value`` can dispatch to."""

    BOOL = "bool"
    DATE = "date"
    DATETIME = "datetime"
    DECIMAL = "decimal"
    FLOAT = "float"
    INT = "int"
    LOCATION = "location"
    NONE = "none"
    PASS = "pass"  # noqa: S105
    TEXT = "text"
    URL = "url"


class ExecutionMode(StrEnum):
    """Whether a run executes the pipeline or only describes it."""

    RUN = "run"
    DESCRIBE_INPUTS = "describe_inputs"
    DESCRIBE_DEPENDENCIES = "describe_dependencies"
    DESCRIBE = "describe"


type ModuleNameLike = str | ModuleName
type KeyLike = str | Iterable[str]
type FmtLike = Formats | str
