"""
String enums shared by Riko's stable, extension, and implementation APIs.

Examples:

    >>> from riko import Formats
    >>>
    >>> Formats.JSON.value
    'json'

"""

from collections.abc import Iterable
from enum import StrEnum
from typing import Literal, NewType

from typing_extensions import TypeIs

type ModuleNameLike = str | ModuleName
type StrLike = str | Iterable[str]
type FmtLike = Formats | str
type BackendLike = Backends | str
type ExecutorLike = Executor | str
type IdentityModeLike = IdentityMode | str
type DocumentShapeLike = DocumentShape | str
type ConcurrencyLike = int | Literal["auto"]
type UserAgentLike = UserAgent | CustomUserAgent | str
type FeedTypeLike = FeedType | str

CustomUserAgent = NewType("CustomUserAgent", str)


class ModuleName(StrEnum):
    """A type-safe module name base populated by module-name discovery."""


class Formats(StrEnum):
    """How a write serializes items to a destination."""

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
    """Cast types whose values are orderable for sort comparisons."""

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
    """Every cast type ``cast_value`` can dispatch to."""

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


class Executor(StrEnum):
    """
    Where a run executes per-item work.

    ``AUTO`` lets the run pick: items run sequentially inline unless a
    concurrency limit above one (or ``"auto"``) is set, in which case
    synchronous iteration uses a thread pool. Under asynchronous iteration,
    native async work runs inline and synchronous work runs on worker threads.
    ``INLINE`` never uses workers, while ``THREAD`` and ``PROCESS`` use a pool of
    threads or worker processes.

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
    result's identity from every item that contributed to it. A run carries each
    item's identity through the node according to its mode.

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

    """

    DAG = "dag"
    V1 = "v1"
    V2 = "v2"


class UserAgent(StrEnum):
    """
    A built-in choice of the HTTP ``User-Agent`` a fetch sends.

    ``DEFAULT`` sends riko's own ``riko/<version>`` agent, the same as leaving the
    choice unset. The others select a fresh agent for every request: ``DESKTOP`` from
    desktop browsers, ``MOBILE`` from phone browsers, and ``RANDOM`` from either. Any
    other non-empty string of printable ASCII with no leading or trailing whitespace (a
    ``CustomUserAgent``) is sent as is.

    """

    DEFAULT = "default"
    RANDOM = "random"
    DESKTOP = "desktop"
    MOBILE = "mobile"


class FeedType(StrEnum):
    """
    A link type feed discovery recognizes as a feed.

    Each value matches a link's ``type`` (whole or after its last ``/``). E.g., ``ATOM``
    matches ``application/atom+xml``. The declaration order is the default preference.

    """

    RSS = "rss+xml"
    ATOM = "atom+xml"
    RDF = "rdf+xml"
    JSON = "feed+json"
    TEXT_XML = "text/xml"
    XML = "xml"


def is_custom_user_agent(value: object) -> TypeIs[CustomUserAgent]:
    """
    Reports whether ``value`` is an agent sent as is rather than a UserAgent member.

    A custom agent is a non-empty string of printable ASCII, inner spaces included
    but none leading or trailing, that is not a ``UserAgent`` value.

    Examples:

        >>> is_custom_user_agent("riko/1.0")
        True
        >>> is_custom_user_agent("curl")
        True
        >>> is_custom_user_agent("bot\\r\\nX: 1")
        False
        >>> is_custom_user_agent(" bot/1.0")
        False
        >>> is_custom_user_agent("random")
        False

    """
    return (
        isinstance(value, str)
        and value.isascii()
        and value.isprintable()
        and bool(value)
        and value == value.strip()
        and value not in UserAgent
    )


def require_custom_user_agent(value: object) -> CustomUserAgent:
    """
    Requires ``value`` to be an agent string a request can send as is.

    Args:

        value: The agent to check.

    Returns:

        ``value`` narrowed to a ``CustomUserAgent``.

    Raises:

        ValueError: If ``value`` is empty, holds a control or non-ASCII character,
            starts or ends with whitespace, or is a ``UserAgent`` value.

    Examples:

        >>> require_custom_user_agent("riko/1.0")
        'riko/1.0'
        >>> require_custom_user_agent("")
        Traceback (most recent call last):
            ...
        ValueError: Invalid user agent ''. Use a UserAgent value...

    """
    if not is_custom_user_agent(value):
        msg = f"Invalid user agent {value!r}. Use a UserAgent value or a non-empty "
        raise ValueError(msg + "string of printable ASCII without surrounding spaces.")

    return value
