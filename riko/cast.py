# -*- coding: utf-8 -*-
# vim: sw=4:ts=4:expandtab
"""
riko.cast
~~~~~~~~~
Provides type casting capabilities
"""
from decimal import Decimal, InvalidOperation
from enum import StrEnum
from functools import partial
from json import loads
from operator import add, sub
from time import gmtime, struct_time
from datetime import date, datetime as dt, timedelta, UTC
from typing import Callable, Literal, Optional, TypeVar, overload
from urllib.parse import quote, urlparse
from ast import literal_eval
from typing import cast as cast_type

from dateutil import parser
from meza.compat import decode
from riko.dates import EPOCH_DATE, EPOCH_DATETIME, TODAY, TZINFOS, get_date, tt_to_datedict, tt_to_datetime, date_to_tt
from riko.currencies import CURRENCY_CODES
from riko.locations import LOCATIONS
from riko.types.general import BasicValue, ComplexArg, BasicArg, ComplexValue, DateDict, DateLike, IPAddress, IntermediateArg, Location, AnyLocation, PreCaster

URL_SAFE = "%/:=&?~#+!$,;'@()*[]"
MATH_WORDS = {"seconds", "minutes", "hours", "days", "weeks", "months", "years"}
TEXT_WORDS = {"last", "next", "week", "month", "year"}

DATES = {
    "today": TODAY,
    "now": TODAY,
    "tomorrow": TODAY + timedelta(days=1),
    "yesterday": TODAY - timedelta(days=1),
}


T = TypeVar("T", bound=ComplexArg)

url_quote = lambda url: quote(url, safe=URL_SAFE)


def literal_parse(content: BasicValue | bool) -> BasicArg:
    if isinstance(content, (bool, int)):
        parsed = content
    elif content.lower() in {"true", "false"}:
        parsed = loads(content.lower())
    else:
        try:
            parsed = literal_eval(content)
        except (ValueError, SyntaxError):
            parsed = content

    return parsed


def cast_url(url: str) -> str:
    url = "http://%s" % url if "://" not in url else url
    quoted = url_quote(url)
    parsed = urlparse(quoted)
    return parsed.geturl()


def lookup_street_address(_: str) -> Location:
    location = {
        "lat": 0.,
        "lon": 0.,
        "country": "United States",
        "admin1": "state",
        "admin2": "county",
        "admin3": "city",
        "city": "city",
        "street": "street",
        "postal": "61605",
    }

    return location


def lookup_ip_address(address: str) -> IPAddress:
    location = {
        "country": "United States",
        "admin1": "state",
        "admin2": "county",
        "admin3": "city",
        "city": "city",
    }

    return location


def lookup_coordinates(latlon="", lat: Optional[float] = None, lon: Optional[float] = None) -> Location:
    if "," in latlon:
        try:
            lat_str, lon_str = latlon.split(",")
            lat, lon = float(lat_str.strip()), float(lon_str.strip())
        except ValueError:
            lat, lon = 0., 0.
    else:
        lat, lon = lat or 0., lon or 0.

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


def cast_location(address: BasicValue, loc_type="street_address") -> AnyLocation:
    GEOLOCATERS: dict[str, Callable[[str], AnyLocation]] = {
        "coordinates": lambda x: lookup_coordinates(x),
        "street_address": lambda x: lookup_street_address(x),
        "ip_address": lambda x: lookup_ip_address(x),
        "currency": lambda x: CURRENCY_CODES.get(x, {}),
    }

    result = dict(GEOLOCATERS[loc_type](str(address)))

    if location := result.get("location"):
        # TODO: make location a typed dict
        extra = LOCATIONS.get(str(location), {})
        result.update(extra)

    return result


# TODO: inherit from meza


@overload
def cast_datetime(value: DateLike) -> Optional[dt]:
    ...
@overload  # noqa: E302
def cast_datetime(value: DateLike, as_date: Literal[True]) -> Optional[date]:
    ...
@overload  # noqa: E302
def cast_datetime(value: DateLike, as_date: Literal[False]) -> Optional[dt]:
    ...
@overload  # noqa: E302
def cast_datetime(value: DateLike, as_date: Literal[True], as_datedict: Literal[True]) -> Optional[DateDict]:
    ...
@overload  # noqa: E302
def cast_datetime(value: DateLike, as_date: Literal[False], as_datedict: Literal[True]) -> Optional[DateDict]:
    ...
def cast_datetime(  # noqa: E302
    value: DateLike,
    as_date=False,
    as_datedict=False,
) -> Optional[date | dt | DateDict]:
    tt = None

    if isinstance(value, date) and as_date:
        _date = value
    elif isinstance(value, date):
        tt = value.timetuple()
        _date = tt_to_datetime(tt, as_date=as_date)
    elif isinstance(value, dt) and as_date:
        _date = value.date()
    elif isinstance(value, dt):
        _date = value
    elif isinstance(value, int):
        tt = gmtime(value)
        _date = tt_to_datetime(tt, as_date=as_date)
    elif isinstance(value, struct_time):
        tt, _date = value, tt_to_datetime(value, as_date=as_date)
    else:
        words = value.split(" ")
        mathish = set(words).intersection(MATH_WORDS)
        textish = set(words).intersection(TEXT_WORDS)

        if value[0] in {"+", "-"} and len(mathish) == 1:
            op = sub if value.startswith("-") else add
            _date = get_date("".join(mathish), int(words[0][1:]), op)
        elif len(textish) == 2:
            _date = get_date(f"{words[1]}s", 1, add)
        elif value in DATES:
            _date = DATES.get(value)
        else:
            _date = parser.parse(value, tzinfos=TZINFOS)

        _date = _date.date() if _date and as_date else _date

    if isinstance(_date, dt) and not _date.tzname():
        _tzinfo = TODAY.astimezone().tzinfo or UTC
        tt, _date = None, _date.replace(tzinfo=_tzinfo)

    if _date and as_datedict:
        tt = tt or date_to_tt(_date)
        result = tt_to_datedict(tt, _date)
    else:
        result = _date

    return result


cast_date = cast_type(Callable[[DateLike], Optional[date]], partial(cast_datetime, as_date=True))


CAST_SWITCH: dict[str, PreCaster] = {
    "float": {"default": float("nan"), "func": float},
    "decimal": {"default": Decimal("NaN"), "func": Decimal},
    "int": {"default": 0, "func": lambda i: int(float(i))},
    "text": {"default": "", "func": decode},
    "datetime": {"default": EPOCH_DATETIME, "func": cast_datetime},
    # TODO: make this return date without time
    "date": {"default": EPOCH_DATE, "func": cast_date},
    "url": {"default": {}, "func": cast_url},
    "location": {"default": {}, "func": cast_location},
    "bool": {"default": False, "func": lambda i: bool(literal_parse(i))},
    "pass": {"default": None, "func": lambda i: i},
    "none": {"default": None, "func": lambda _: None},
}


class CastType(StrEnum):
    PASS = "pass"
    NONE = "none"
    TEXT = "text"
    FLOAT = "float"
    DECIMAL = "decimal"
    INT = "int"
    DATETIME = "datetime"
    DATE = "date"
    URL = "url"
    LOCATION = "location"
    BOOL = "bool"


@overload
def cast(content: ComplexArg) -> str:
    ...
@overload  # noqa: E302
def cast(content: T, _type: Literal[CastType.PASS], **kwargs) -> T:
    ...
@overload  # noqa: E302
def cast(content: ComplexArg, _type: Literal[CastType.NONE], **kwargs) -> None:
    ...
@overload  # noqa: E302
def cast(content: ComplexArg, _type: Literal[CastType.TEXT], **kwargs) -> str:
    ...
@overload  # noqa: E302
def cast(content: ComplexArg, _type: Literal[CastType.FLOAT], **kwargs) -> float:
    ...
@overload  # noqa: E302
def cast(content: ComplexArg, _type: Literal[CastType.DECIMAL], **kwargs) -> Decimal:
    ...
@overload  # noqa: E302
def cast(content: ComplexArg, _type: Literal[CastType.INT], **kwargs) -> int:
    ...
@overload  # noqa: E302
def cast(content: ComplexArg, _type: Literal[CastType.DATETIME], **kwargs) -> dt:
    ...
@overload  # noqa: E302
def cast(content: ComplexArg, _type: Literal[CastType.DATE], **kwargs) -> date:
    ...
@overload  # noqa: E302
def cast(content: ComplexArg, _type: Literal[CastType.URL], **kwargs) -> str:
    ...
@overload  # noqa: E302
def cast(content: ComplexArg, _type: Literal[CastType.LOCATION], **kwargs) -> AnyLocation:
    ...
@overload  # noqa: E302
def cast(content: ComplexArg, _type: Literal[CastType.BOOL], **kwargs) -> bool:
    ...
@overload  # noqa: E302
def cast(content: T, _type: CastType, **kwargs) -> T | ComplexValue:
    ...
def cast(content: T, _type: CastType = CastType.TEXT, **kwargs) -> T | ComplexValue:
    """Convert content from one type to another

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
    """
    if _type and _type in CAST_SWITCH:
        precaster = CAST_SWITCH[_type]
    else:
        if _type:
            print(f"Invalid cast {_type=}. Returning content as is.")

        precaster = CAST_SWITCH[CastType.PASS]

    default = precaster["default"]

    if content is None and _type != CastType.NONE:
        value = default
    elif content is None:
        value = None
    elif _type == CastType.NONE:
        value = None
    elif _type == CastType.PASS:
        value = content
    elif isinstance(content, (str, int)):
        caster = precaster["func"]

        try:
            value = caster(content, **kwargs)
        except TypeError:
            value = caster(content)
        except (InvalidOperation, ValueError):
            value = default
    elif isinstance(content, (int, float, Decimal)) and _type in {CastType.INT, CastType.FLOAT, CastType.DECIMAL}:
        caster = precaster["func"]
        value = caster(content)
    elif isinstance(content, (struct_time, dt, date)) and _type == CastType.DATE:
        value = cast_date(content)
    elif isinstance(content, (struct_time, dt, date)) and _type == CastType.DATETIME:
        value = cast_datetime(content)
    else:
        print(f"Casting a {type(content)} to _type={_type} is not supported. Returning {content=} as is.")
        value = content

    return value


cast_none = cast_type(Callable[[ComplexArg], None], partial(cast, _type=CastType.NONE))


cast_pass = cast_type(Callable[[T], T], partial(cast, _type=CastType.PASS))
