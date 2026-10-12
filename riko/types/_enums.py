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
from typing import Literal, overload

from riko.base.exceptions import InvalidPipelineError


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
    How a write serializes items to a destination.

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
    Every cast type ``cast_value`` can dispatch to.

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
    Whether a workflow module's pipe runs its workflow or only describes it.

    A ``Pipeline`` ignores the describe modes and always runs.

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


class Executor(StrEnum):
    """
    Where a run executes per-item work.

    ``AUTO`` lets the run pick: items run sequentially inline unless a
    concurrency limit above one (or ``"auto"``) is set, in which case
    synchronous iteration uses a thread pool. Under asynchronous iteration,
    native async work runs inline and synchronous work runs on worker threads.
    ``INLINE`` never uses workers, while ``THREAD`` and ``PROCESS`` use a pool of
    threads or worker processes.

    Examples:

        >>> from riko import Executor
        >>>
        >>> Executor("thread") is Executor.THREAD, Executor.AUTO.value
        (True, 'auto')

    """

    AUTO = "auto"
    INLINE = "inline"
    THREAD = "thread"
    PROCESS = "process"


@overload
def resolve_enum[E: StrEnum](  # noqa: E704
    enum: type[E],
    value: E | str | None,
    what: str | None = ...,
    *,
    default: E | None = ...,
    strict: Literal[True] = ...,
    error: type[Exception] = ...,
) -> E: ...
@overload  # noqa: E302
def resolve_enum[E: StrEnum](  # noqa: E704
    enum: type[E],
    value: E | str | None,
    what: str | None = ...,
    *,
    default: E | None = ...,
    strict: Literal[False],
    error: type[Exception] = ...,
) -> E | None: ...
@overload  # noqa: E302
def resolve_enum[E: StrEnum](  # noqa: E704
    enum: type[E],
    value: E | str | None,
    what: str | None = ...,
    *,
    default: E | None = ...,
    strict: bool,
    error: type[Exception] = ...,
) -> E | None: ...
def resolve_enum[E: StrEnum](  # noqa: E302
    enum: type[E],
    value: E | str | None,
    what: str | None = None,
    *,
    default: E | None = None,
    strict: bool = True,
    error: type[Exception] = InvalidPipelineError,
) -> E | None:
    """
    Resolves a member or member value into the given string enum.

    A missing ``value`` resolves to ``default``; with no default, it is an error
    unless ``strict`` is off, in which case it resolves to ``None``.

    Args:

        enum: The string enum to resolve into.
        value: A member or member value, or ``None`` when absent.
        what: How error messages name the value; defaults to the enum's name.
        default: The member a missing ``value`` resolves to.
        strict: Whether a missing ``value`` with no ``default`` raises.
        error: The exception class raised for a missing or invalid ``value``.

    Returns:

        The resolved member, or ``None`` when ``value`` is missing, there is no
        ``default``, and ``strict`` is off.

    Raises:

        error: ``value`` is not one of the enum's values, or is missing while
            required. The invalid-value message lists every accepted value.

    Examples:

        >>> from riko import Executor
        >>> from riko.types._enums import resolve_enum
        >>>
        >>> resolve_enum(Executor, "thread")
        <Executor.THREAD: 'thread'>
        >>> resolve_enum(Executor, "bogus", error=ValueError)
        Traceback (most recent call last):
        ...
        ValueError: Invalid Executor: 'bogus'; expected one of auto, inline, thread, ...

    """
    what = enum.__name__ if what is None else what

    if value is None and default is None and strict:
        raise error(f"missing required {what}")
    elif value is None:
        result = default
    else:
        try:
            result = value if isinstance(value, enum) else enum(value)
        except ValueError as e:
            accepted = ", ".join(member.value for member in enum)
            raise error(f"Invalid {what}: {value!r}; expected one of {accepted}") from e

    return result


type ModuleNameLike = str | ModuleName
type StrLike = str | Iterable[str]
type FmtLike = Formats | str
type BackendLike = Backends | str
type ExecutorLike = Executor | str
type ConcurrencyLike = int | Literal["auto"]
