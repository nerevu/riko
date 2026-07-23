# vim: sw=4:ts=4:expandtab
"""
Provides type casting capabilities
"""

from ast import literal_eval
from collections.abc import Callable
from datetime import UTC, date, timedelta
from datetime import datetime as dt
from decimal import Decimal, InvalidOperation
from enum import StrEnum
from functools import partial
from json import loads
from operator import add, sub
from time import gmtime, struct_time
from typing import Literal, TypeVar, overload
from typing import cast as cast_type
from urllib.parse import quote, urlparse

import pygogo as gogo

from riko.currencies import CURRENCY_CODES
from riko.dates import (
    EPOCH_DATE,
    EPOCH_DATETIME,
    date_to_tt,
    ensure_tzinfo,
    get_date,
    parse_date_string,
    tt_to_datedict,
    tt_to_datetime,
)
from riko.locations import LOCATIONS
from riko.types.general import Opts, PreCaster
from riko.types.values import (
    AnyLocation,
    BasicArg,
    BasicValue,
    DateDict,
    DateLike,
    IPAddress,
    Location,
    PrimitiveValue,
)

URL_SAFE = "%/:=&?~#+!$,;'@()*[]"
MATH_WORDS = {"seconds", "minutes", "hours", "days", "weeks", "months", "years"}
TEXT_WORDS = {"last", "next", "week", "month", "year"}
GEOLOCATERS: dict[str, Callable[[str], AnyLocation]] = {
    "coordinates": lambda x: lookup_coordinates(x),
    "street_address": lambda x: lookup_street_address(x),
    "ip_address": lambda x: lookup_ip_address(x),
    "currency": lambda x: CURRENCY_CODES.get(x, {}),
}

T = TypeVar("T")

url_quote = lambda url: quote(url, safe=URL_SAFE)
logger = gogo.Gogo(__name__, monolog=True).logger


class LocationType(StrEnum):
    COORDINATES = "coordinates"
    CURRENCY = "currency"
    IP_ADDRESS = "ip_address"
    STREET_ADDRESS = "street_address"


class BasicCastType(StrEnum):
    DATE = "date"
    DECIMAL = "decimal"
    FLOAT = "float"
    INT = "int"
    NONE = "none"
    PASS = "pass"  # noqa: S105
    TEXT = "text"


class SortableCastType(StrEnum):
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


def cast_url(url: str | int) -> str:
    url = f"http://{url}" if "://" not in str(url) else url
    quoted = url_quote(url)
    parsed = urlparse(quoted)
    return parsed.geturl()


def lookup_street_address(_: str) -> Location:
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
    location = {
        "country": "United States",
        "admin1": "state",
        "admin2": "county",
        "admin3": "city",
        "city": "city",
    }

    return location


def lookup_coordinates(
    latlon="", lat: float | None = None, lon: float | None = None
) -> Location:
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
    result = dict(GEOLOCATERS[loc_type](str(address)))

    if location := result.get("location"):
        # TODO: make location a typed dict
        extra = LOCATIONS.get(str(location), {})
        result.update(extra)

    return result


# TODO: inherit from meza
@overload
def cast_datetime(value: DateLike) -> dt | None: ...  # noqa: E704
@overload  # noqa: E302
def cast_datetime(  # noqa: E704
    value: DateLike, as_date: Literal[True]
) -> date | None: ...
@overload  # noqa: E302
def cast_datetime(  # noqa: E704
    value: DateLike, as_date: Literal[False] = ...
) -> dt | None: ...
@overload  # noqa: E302
def cast_datetime(  # noqa: E704
    value: DateLike, as_date: Literal[True], as_datedict: Literal[True]
) -> DateDict | None: ...
@overload  # noqa: E302
def cast_datetime(  # noqa: E704
    value: DateLike, *, as_date: Literal[False] = ..., as_datedict: Literal[True]
) -> DateDict | None: ...
def cast_datetime(  # noqa: E302
    value: DateLike,
    as_date=False,
    as_datedict=False,
    try_local_tz=False,
) -> date | dt | DateDict | None:
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
        mathish = set(words).intersection(MATH_WORDS)
        textish = set(words).intersection(TEXT_WORDS)
        today = dt.now(UTC).date()
        named = {
            "today": today,
            "now": today,
            "tomorrow": today + timedelta(days=1),
            "yesterday": today - timedelta(days=1),
        }

        if value and value[0] in {"+", "-"} and len(mathish) == 1:
            op = sub if value.startswith("-") else add
            _date = get_date("".join(mathish), int(words[0][1:]), op)
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


cast_date = cast_type(
    Callable[[DateLike], date | None], partial(cast_datetime, as_date=True)
)


CAST_SWITCH: dict[str, PreCaster] = {
    "float": {"default": float("nan"), "func": float},
    "decimal": {"default": Decimal("NaN"), "func": Decimal},
    "int": {"default": 0, "func": lambda i: int(float(i))},
    "text": {"default": "", "func": str},
    "datetime": {"default": EPOCH_DATETIME, "func": cast_datetime},
    "date": {"default": EPOCH_DATE, "func": cast_date},
    "url": {"default": {}, "func": cast_url},
    "location": {"default": {}, "func": cast_location},
    "bool": {"default": False, "func": lambda i: bool(literal_parse(i))},
    "pass": {"default": None, "func": lambda i: i},
    "none": {"default": None, "func": lambda _: None},
}


@overload
def cast(content: object) -> str: ...  # noqa: E704
@overload  # noqa: E302
def cast[T](  # noqa: E704
    content: T,
    _type: Literal[CastType.PASS],
    **kwargs,
) -> T: ...
@overload  # noqa: E302
def cast(  # noqa: E704
    content: object,
    _type: Literal[CastType.NONE],
    **kwargs,
) -> None: ...
@overload  # noqa: E302
def cast(  # noqa: E704
    content: object,
    _type: Literal[CastType.TEXT],
    **kwargs,
) -> str: ...
@overload  # noqa: E302
def cast(  # noqa: E704
    content: object,
    _type: Literal[CastType.FLOAT],
    **kwargs,
) -> float: ...
@overload  # noqa: E302
def cast(  # noqa: E704
    content: object, _type: Literal[CastType.DECIMAL], **kwargs
) -> Decimal: ...
@overload  # noqa: E302
def cast(  # noqa: E704
    content: object, _type: Literal[CastType.INT], **kwargs
) -> int: ...
@overload  # noqa: E302
def cast(  # noqa: E704
    content: object, _type: Literal[CastType.DATETIME], **kwargs
) -> dt: ...
@overload  # noqa: E302
def cast(  # noqa: E704
    content: object, _type: Literal[CastType.DATE], **kwargs
) -> date: ...
@overload  # noqa: E302
def cast(  # noqa: E704
    content: object, _type: Literal[CastType.URL], **kwargs
) -> str: ...
@overload  # noqa: E302
def cast(  # noqa: E704
    content: object, _type: Literal[CastType.LOCATION], **kwargs
) -> AnyLocation: ...
@overload  # noqa: E302
def cast(  # noqa: E704
    content: object, _type: Literal[CastType.BOOL], **kwargs
) -> bool: ...
@overload  # noqa: E302
def cast[T](  # noqa: E704
    content: T, _type: CastType, **kwargs
) -> T | PrimitiveValue: ...
def cast[T](  # noqa: E302
    content: T, _type: CastType = CastType.TEXT, **kwargs
) -> T | PrimitiveValue | AnyLocation:
    """
    Convert content from one type to another

    Args:
        content: The entry to convert

    Kwargs:
        _type (str): The type to convert to

    Returns:
        any: The converted content

    Examples:
        >>> content = '12.25'
        >>> cast(content, 'float')
        12.25
        >>> cast(content, 'decimal')
        Decimal('12.25')
        >>> cast(content, 'int')
        12
        >>> cast(content, 'text')
        '12.25'
        >>> cast(content, 'bool')
        True
        >>> cast('foo', 'float')
        nan
        >>> cast('foo', 'decimal')
        Decimal('NaN')
        >>> cast('foo', 'int')
        0
        >>> cast(12.25, 'text')
        '12.25'
        >>> cast(Decimal('12.25'), 'text')
        '12.25'
        >>> cast(12.25, 'int')
        12

    """
    if _type and _type in CAST_SWITCH:
        precaster = CAST_SWITCH[_type]
    else:
        if _type:
            logger.warning(f"Invalid cast {_type=}. Returning content as is.")

        precaster = CAST_SWITCH[CastType.PASS]

    caster = precaster["func"]
    default = precaster["default"]

    if content is None and _type != CastType.NONE:
        value = default
    elif content is None or _type == CastType.NONE:
        value = None
    elif _type == CastType.PASS:
        value = content
    elif _type in KWARG_TYPES:
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


cast_none = cast_type(Callable[..., None], partial(cast, _type=CastType.NONE))


cast_pass = cast_type(Callable[[T], T], partial(cast, _type=CastType.PASS))
