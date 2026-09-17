"""
String enums shared by Riko's stable, extension, and implementation APIs.

Examples:

    >>> from riko import ExecutionMode, Formats
    >>>
    >>> Formats.JSON.value, ExecutionMode.RUN.value
    ('json', 'run')

"""

from collections.abc import Iterable
from enum import StrEnum


class ModuleName(StrEnum):
    """
    A type-safe module name base populated by module-name discovery.

    Examples:

        >>> from riko.ext import ModuleName
        >>>
        >>> issubclass(ModuleName, str)
        True

    """


class Formats(StrEnum):
    """
    How a write serializes records to a destination.

    Examples:

        >>> from riko import Formats
        >>>
        >>> Formats.JSON.value
        'json'

    """

    CSV = "csv"
    GEOJSON = "geojson"
    JSON = "json"
    JSONL = "jsonl"
    OFX = "ofx"
    QIF = "qif"


class Backends(StrEnum):
    """The kind of backend a write reaches."""

    FILE = "file"
    HTTP = "http"
    S3 = "s3"
    POSTGRES = "postgres"
    AIRTABLE = "airtable"
    INTUNE = "intune"


class LocationType(StrEnum):
    """
    The kind of lookup ``cast_location`` performs.

    Examples:

        >>> LocationType.CURRENCY.value
        'currency'

    """

    COORDINATES = "coordinates"
    CURRENCY = "currency"
    IP_ADDRESS = "ip_address"
    STREET_ADDRESS = "street_address"


class BasicCastType(StrEnum):
    """
    Cast types a module may set as its ``ftype``/``ptype``.

    Examples:

        >>> BasicCastType.INT.value
        'int'

    """

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
    """
    Cast types whose values are orderable for sort comparisons.

    Examples:

        >>> SortableCastType.BOOL.value
        'bool'

    """

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
    """
    Every destination type ``cast_value`` can dispatch to.

    Examples:

        >>> CastType.LOCATION.value
        'location'

    """

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
    """
    Whether a run executes the pipeline or only describes it.

    Examples:

        >>> from riko import ExecutionMode
        >>>
        >>> ExecutionMode.DESCRIBE_INPUTS.value
        'describe_inputs'

    """

    RUN = "run"
    DESCRIBE_INPUTS = "describe_inputs"
    DESCRIBE_DEPENDENCIES = "describe_dependencies"
    DESCRIBE = "describe"


type ModuleNameLike = str | ModuleName
type KeyLike = str | Iterable[str]
type FmtLike = Formats | str
type BackendLike = Backends | str
