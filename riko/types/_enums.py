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
from typing import Literal


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

        >>> from riko import CastType
        >>>
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


class IdentityMode(StrEnum):
    """
    How a callable node's results relate to the identity of the items it receives.

    ``PRESERVE`` keeps each input item's identity on its one result. ``DERIVE`` gives
    each result a child identity derived from its input item. ``COMBINE`` builds a
    result's identity from every item that contributed to it. A node carries the mode
    it declares, but no run acts on it yet.

    Examples:

        >>> from riko import IdentityMode
        >>>
        >>> IdentityMode("derive") is IdentityMode.DERIVE, IdentityMode.COMBINE.value
        (True, 'combine')

    """

    PRESERVE = "preserve"
    DERIVE = "derive"
    COMBINE = "combine"


class DocumentShape(StrEnum):
    """
    The three JSON shapes a workflow input may take.

    ``DAG`` is a bare-bones DAG (``PipeDag``), ``V1`` a serialized pipe definition
    (``PipeDef``), and ``V2`` a workflow document (``WorkflowDocument``, a serialized
    ``Workflow``).

    Examples:

        >>> from riko import DocumentShape
        >>>
        >>> DocumentShape.DAG.value
        'dag'

    """

    DAG = "dag"
    V1 = "v1"
    V2 = "v2"


type ModuleNameLike = str | ModuleName
type StrLike = str | Iterable[str]
type FmtLike = Formats | str
type BackendLike = Backends | str
type ExecutorLike = Executor | str
type IdentityModeLike = IdentityMode | str
type DocumentShapeLike = DocumentShape | str
type ConcurrencyLike = int | Literal["auto"]
