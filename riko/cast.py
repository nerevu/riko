# vim: sw=4:ts=4:expandtab
"""
riko.cast
~~~~~~~~~

Provides type casting capabilities.

Dispatch is by destination type; ``CAST_SWITCH`` maps each type to its caster
and default.

Examples:
    Basic usage::

        >>> from riko.cast import cast_value
        >>>
        >>> cast_value("12.25", "float")
        12.25
        >>> cast_value("12.25", "int")
        12

Attributes:
    CAST_SWITCH: Destination type to caster and default mapping.

"""

from ast import literal_eval
from collections.abc import Callable
from datetime import date, timedelta
from datetime import datetime as dt
from decimal import Decimal, InvalidOperation
from enum import StrEnum
from functools import partial
from json import loads
from logging import Logger
from operator import add, sub
from time import gmtime, struct_time
from typing import Literal, cast, overload
from urllib.parse import quote, urlparse

import pygogo as gogo

from riko._date_utils import (
    date_to_tt,
    ensure_tzinfo,
    get_local_tz,
    parse_date_string,
    tt_to_datetime,
)
from riko.currencies import CURRENCY_CODES
from riko.dates import get_date, tt_to_datedict
from riko.locations import LOCATIONS
from riko.types._collections import BasicArg
from riko.types._locations import AnyLocation, IPAddress, Location
from riko.types._options import Opts
from riko.types._scalars import BasicValue, DateDict, DateLike, PrimitiveValue
from riko.types._wrappers import PreCaster

URL_SAFE = "%/:=&?~#+!$,;'@()*[]"
MATH_WORDS = {"seconds", "minutes", "hours", "days", "weeks", "months", "years"}
TEXT_WORDS = {"last", "next", "week", "month", "year"}
GEOLOCATERS: dict[str, Callable[[str], AnyLocation]] = {
    "coordinates": lambda x: lookup_coordinates(x),  # noqa: PLW0108
    "street_address": lambda x: lookup_street_address(x),  # noqa: PLW0108
    "ip_address": lambda x: lookup_ip_address(x),  # noqa: PLW0108
    "currency": lambda x: CURRENCY_CODES.get(x, {}),
}


logger: Logger = gogo.Gogo(__name__, monolog=True).logger


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


KWARG_TYPES = {CastType.DATE, CastType.DATETIME, CastType.LOCATION}
SourceOpts: Opts = {"ftype": BasicCastType.NONE}


def literal_parse(content: BasicValue | bool) -> BasicArg:
    """
    Parses a string into the Python literal it denotes.

    A non-string is returned unchanged; ``"true"``/``"false"`` (any case)
    become booleans; anything else is parsed via ``ast.literal_eval``, falling
    back to the original string when it is not a valid literal.

    Args:
        content: The value to parse.

    Returns:
        The parsed literal, or ``content`` unchanged when it is not a string or
        not a valid literal.

    Examples:
        >>> literal_parse("true")
        True
        >>> literal_parse("[1, 2]")
        [1, 2]
        >>> literal_parse("foo")
        'foo'

    """
    if isinstance(content, (bool, int, float, Decimal)):
        parsed = content
    elif content.lower() in {"true", "false"}:
        parsed = loads(content.lower())
    else:
        try:
            parsed = literal_eval(content)
        except (ValueError, SyntaxError):
            parsed = content

    return parsed


def url_quote(url: str | int) -> str:
    """
    Percent-encodes a URL while leaving URL-syntax characters intact.

    Args:
        url: The URL (or numeric host) to encode.

    Returns:
        The encoded URL, with the characters in ``URL_SAFE`` left unescaped.

    Examples:
        >>> url_quote("a b/c")
        'a%20b/c'

    """
    return quote(url, safe=URL_SAFE)  # type: ignore[arg-type]


def cast_url(url: str | int) -> str:
    """
    Normalizes a value into a percent-encoded URL.

    Prepends ``http://`` when no scheme is present, then encodes it and
    round-trips it through ``urlparse``.

    Args:
        url: The URL (or numeric host) to normalize.

    Returns:
        The normalized, encoded URL string.

    Examples:
        >>> cast_url("example.com/a b")
        'http://example.com/a%20b'

    """
    url = f"http://{url}" if "://" not in str(url) else url
    quoted = url_quote(url)
    parsed = urlparse(quoted)
    return parsed.geturl()


def lookup_street_address(_: str) -> Location:
    """
    Returns a placeholder street-address location.

    A fixed stub standing in for a real geocoder; the input is ignored.

    Args:
        _: Ignored; accepted for interface parity with a real geocoder.

    Returns:
        A ``Location`` with placeholder address fields.

    Examples:
        >>> lookup_street_address("1600 Pennsylvania Ave")["postal"]
        '61605'

    """
    location = {
        "lat": 0.0,
        "lon": 0.0,
        "country": "United States",
        "admin1": "state",
        "admin2": "county",
        "admin3": "city",
        "city": "city",
        "street": "street",
        "postal": "61605",
    }

    return location


def lookup_ip_address(_: str) -> IPAddress:
    """
    Returns a placeholder IP-address location.

    A fixed stub standing in for a real geolocator; the input is ignored.

    Args:
        _: Ignored; accepted for interface parity with a real geolocator.

    Returns:
        An ``IPAddress`` location with placeholder fields.

    Examples:
        >>> lookup_ip_address("8.8.8.8")["country"]
        'United States'

    """
    location = {
        "country": "United States",
        "admin1": "state",
        "admin2": "county",
        "admin3": "city",
        "city": "city",
    }

    return location


def lookup_coordinates(
    latlon: str = "", lat: float | None = None, lon: float | None = None
) -> Location:
    """
    Builds a location from a coordinate pair.

    Parses ``"lat,lon"`` when given, otherwise uses the ``lat``/``lon``
    arguments; unparseable or missing coordinates default to ``0.0``.

    Args:
        latlon: A ``"lat,lon"`` string; used when it contains a comma.
        lat: The latitude used when ``latlon`` has no comma.
        lon: The longitude used when ``latlon`` has no comma.

    Returns:
        A ``Location`` with the resolved ``lat``/``lon`` and placeholder fields.

    Examples:
        >>> lookup_coordinates("1.5, 2.5")["lat"]
        1.5
        >>> lookup_coordinates(lat=1.0, lon=2.0)["lon"]
        2.0

    """
    if "," in latlon:
        try:
            lat_str, lon_str = latlon.split(",")
            lat, lon = float(lat_str.strip()), float(lon_str.strip())
        except ValueError:
            lat, lon = 0.0, 0.0
    else:
        lat, lon = lat or 0.0, lon or 0.0

    location = {
        "lat": lat,
        "lon": lon,
        "country": "United States",
        "admin1": "state",
        "admin2": "county",
        "admin3": "city",
        "city": "city",
        "street": "street",
        "postal": "61605",
    }

    return location


def cast_location(
    address: BasicValue, loc_type: LocationType = LocationType.STREET_ADDRESS
) -> AnyLocation:
    """
    Resolves an address or code into a location and enriches it from ``LOCATIONS``.

    Dispatches to the geocoder for ``loc_type``; when the result names a ``location``,
    its entry from ``LOCATIONS`` is merged in.

    Args:
        address: The address, coordinate, IP, or currency code to look up.
        loc_type: Which kind of lookup to perform.

    Returns:
        The resolved location mapping.

    Examples:
        >>> cast_location("123 Main St")["city"]
        'city'
        >>> cast_location("USD", "currency")["name"]
        'US Dollar'

    """
    result = GEOLOCATERS[loc_type](str(address))

    if location := result.get("location"):
        extra = LOCATIONS.get(str(location), cast(dict[str, str], {}))
        result = cast(AnyLocation, {**result, **extra})

    return result


# TODO: inherit from meza
@overload
def cast_datetime(  # noqa: E704
    value: DateLike, *, try_local_tz: bool = ...
) -> dt | None: ...
@overload  # noqa: E302
def cast_datetime(  # noqa: E704
    value: DateLike, as_date: Literal[True], *, try_local_tz: bool = ...
) -> date | None: ...
@overload  # noqa: E302
def cast_datetime(  # noqa: E704
    value: DateLike, as_date: Literal[False] = ..., *, try_local_tz: bool = ...
) -> dt | None: ...
@overload  # noqa: E302
def cast_datetime(  # noqa: E704
    value: DateLike,
    as_date: Literal[True],
    as_datedict: Literal[True],
    *,
    try_local_tz: bool = ...,
) -> DateDict | None: ...
@overload  # noqa: E302
def cast_datetime(  # noqa: E704
    value: DateLike,
    *,
    as_date: Literal[False] = ...,
    as_datedict: Literal[True],
    try_local_tz: bool = ...,
) -> DateDict | None: ...
def cast_datetime(  # noqa: E302
    value: DateLike, as_date=False, as_datedict=False, *, try_local_tz=False
) -> date | dt | DateDict | None:
    """
    Normalizes a date-like value to a ``datetime`` (or ``date``/``DateDict``).

    Accepts real ``date``/``datetime``/``struct_time``/epoch-``int`` values and
    string shorthands. Named days (``"now"``/``"today"``/``"yesterday"``), counted
    offsets (``"3 days"``/``"-1 month"``), and ``next``/``last`` word forms resolve
    against the current time.

    Args:
        value: The date-like value or string shorthand to normalize.
        as_date: Whether to return a ``date`` rather than a ``datetime``.
        as_datedict: Whether to return a ``DateDict`` of date components.
        try_local_tz: Whether to assume the local timezone for naive values.

    Returns:
        The normalized value, or ``None`` when it cannot be parsed.

    Examples:
        >>> type(cast_datetime('now')).__name__
        'datetime'
        >>> type(cast_datetime('today')).__name__
        'date'
        >>> cast_datetime('-1 day') == cast_datetime('yesterday')
        True
        >>> cast_datetime('1 week') == cast_datetime('+7 days')
        True
        >>> cast_datetime('next month') == cast_datetime('1 month')
        True

    """
    tt = None

    if isinstance(value, dt) and as_date:
        _date = value.date()
    elif isinstance(value, dt) or isinstance(value, date) and as_date:
        _date = value
    elif isinstance(value, date):
        tt = value.timetuple()
        _date = tt_to_datetime(tt, as_date=as_date)
    elif isinstance(value, int):
        tt = gmtime(value)
        _date = tt_to_datetime(tt, as_date=as_date)
    elif isinstance(value, struct_time):
        tt, _date = value, tt_to_datetime(value, as_date=as_date)
    else:
        words = value.split(" ")
        count = words[0].lstrip("+-")
        unit = f"{words[-1].rstrip('s')}s" if len(words) == 2 else ""
        textish = set(words).intersection(TEXT_WORDS)
        now = dt.now(get_local_tz(try_local_tz=try_local_tz))
        today = now.date()
        named = {
            "today": today,
            "now": now,
            "tomorrow": today + timedelta(days=1),
            "yesterday": today - timedelta(days=1),
        }

        if unit in MATH_WORDS and count.isdigit():
            op = sub if value.startswith("-") else add
            _date = get_date(unit, int(count), op)
        elif len(textish) == 2:
            op = sub if words[0] == "last" else add
            _date = get_date(f"{words[1]}s", 1, op)
        elif value in named:
            _date = named[value]
        else:
            _date = parse_date_string(value)

        if isinstance(_date, dt) and as_date:
            _date = _date.date()

    if isinstance(_date, dt):
        _date = ensure_tzinfo(_date, try_local_tz=try_local_tz)

    if _date and as_datedict:
        tt = tt or date_to_tt(_date)
        result = tt_to_datedict(tt, _date)
    else:
        result = _date

    return result


def cast_date(value: DateLike) -> date | None:
    return cast_datetime(value, as_date=True)


CAST_SWITCH: dict[str, PreCaster] = {
    "float": {"default": float("nan"), "func": float},
    "decimal": {"default": Decimal("NaN"), "func": Decimal},
    "int": {"default": 0, "func": lambda i: int(float(i))},
    "text": {"default": "", "func": str},
    "datetime": {"default": None, "func": cast_datetime},
    "date": {"default": None, "func": cast_date},
    "url": {"default": "", "func": cast_url},
    "location": {"default": {}, "func": cast_location},
    "bool": {"default": False, "func": lambda i: bool(literal_parse(i))},
    "pass": {"default": None, "func": lambda i: i},
    "none": {"default": None, "func": lambda _: None},
}


@overload
def cast_value(content: object) -> str: ...  # noqa: E704
@overload  # noqa: E302
def cast_value[T](  # noqa: E704
    content: T, type_: Literal[CastType.PASS], **kwargs: object
) -> T: ...
@overload  # noqa: E302
def cast_value(  # noqa: E704
    content: object, type_: Literal[CastType.NONE], **kwargs: object
) -> None: ...
@overload  # noqa: E302
def cast_value(  # noqa: E704
    content: object, type_: Literal[CastType.TEXT], **kwargs: object
) -> str: ...
@overload  # noqa: E302
def cast_value(  # noqa: E704
    content: object, type_: Literal[CastType.FLOAT], **kwargs: object
) -> float: ...
@overload  # noqa: E302
def cast_value(  # noqa: E704
    content: object, type_: Literal[CastType.DECIMAL], **kwargs: object
) -> Decimal: ...
@overload  # noqa: E302
def cast_value(  # noqa: E704
    content: object, type_: Literal[CastType.INT], **kwargs: object
) -> int: ...
@overload  # noqa: E302
def cast_value(  # noqa: E704
    content: object, type_: Literal[CastType.DATETIME], **kwargs: object
) -> dt: ...
@overload  # noqa: E302
def cast_value(  # noqa: E704
    content: object, type_: Literal[CastType.DATE], **kwargs: object
) -> date: ...
@overload  # noqa: E302
def cast_value(  # noqa: E704
    content: object, type_: Literal[CastType.URL], **kwargs: object
) -> str: ...
@overload  # noqa: E302
def cast_value(  # noqa: E704
    content: object, type_: Literal[CastType.LOCATION], **kwargs: object
) -> AnyLocation: ...
@overload  # noqa: E302
def cast_value(  # noqa: E704
    content: object, type_: Literal[CastType.BOOL], **kwargs: object
) -> bool: ...
@overload  # noqa: E302
def cast_value[T](  # noqa: E704
    content: T, type_: CastType, **kwargs: object
) -> T | PrimitiveValue: ...
def cast_value[T](  # noqa: E302
    content: T, type_: CastType = CastType.TEXT, **kwargs: object
) -> T | PrimitiveValue | AnyLocation:
    """
    Converts content from one type to another.

    Args:
        content: The entry to convert.
        type_: The type to convert to.

    Returns:
        The converted content.

    Examples:
        >>> content = '12.25'
        >>> cast_value(content, 'float')
        12.25
        >>> cast_value(content, 'decimal')
        Decimal('12.25')
        >>> cast_value(content, 'int')
        12
        >>> cast_value(content, 'text')
        '12.25'
        >>> cast_value(content, 'bool')
        True
        >>> cast_value('foo', 'float')
        nan
        >>> cast_value('foo', 'decimal')
        Decimal('NaN')
        >>> cast_value('foo', 'int')
        0
        >>> cast_value(12.25, 'text')
        '12.25'
        >>> cast_value(Decimal('12.25'), 'text')
        '12.25'
        >>> cast_value(12.25, 'int')
        12
        >>> cast_value(None, 'url')
        ''

    """
    if type_ and type_ in CAST_SWITCH:
        precaster = CAST_SWITCH[type_]
    else:
        if type_:
            logger.warning(f"Invalid cast {type_=}. Returning content as is.")

        precaster = CAST_SWITCH[CastType.PASS]

    caster = precaster["func"]
    default = precaster["default"]

    if content is None and type_ != CastType.NONE:
        value = default
    elif content is None or type_ == CastType.NONE:
        value = None
    elif type_ == CastType.PASS:
        value = content
    elif type_ in KWARG_TYPES:
        try:
            value = caster(content, **kwargs)  # pyright: ignore[reportArgumentType]
        except (TypeError, InvalidOperation, ValueError):
            value = default
    else:
        try:
            value = caster(content)  # pyright: ignore[reportArgumentType]
        except (TypeError, InvalidOperation, ValueError):
            value = default

    return value


cast_none: Callable[..., None] = partial(cast_value, type_=CastType.NONE)


def cast_pass[T](content: T, **_: object) -> T:
    """
    Passes content through unchanged.

    A thin wrapper over ``cast_value`` with ``type_=PASS`` for use as a caster.

    Args:
        content: The value to pass through.

    Returns:
        ``content`` unchanged.

    Examples:
        >>> cast_pass(5)
        5
        >>> cast_pass("x")
        'x'

    """
    return cast_value(content, type_=CastType.PASS)
