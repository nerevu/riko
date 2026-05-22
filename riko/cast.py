# -*- coding: utf-8 -*-
# vim: sw=4:ts=4:expandtab
"""
riko.cast
~~~~~~~~~
Provides type casting capabilities
"""
from decimal import Decimal, InvalidOperation
from json import loads
from operator import add, sub
from time import gmtime
from datetime import timedelta
from calendar import timegm
from typing import Any, Optional
from urllib.parse import quote, urlparse
from ast import literal_eval

from dateutil import parser
from meza.compat import decode
from riko.dates import TODAY, gen_tzinfos, get_date, normalize_date, get_tt
from riko.currencies import CURRENCY_CODES
from riko.locations import LOCATIONS

URL_SAFE = "%/:=&?~#+!$,;'@()*[]"
MATH_WORDS = {"seconds", "minutes", "hours", "days", "weeks", "months", "years"}
TEXT_WORDS = {"last", "next", "week", "month", "year"}
TT_KEYS = (
    "year",
    "month",
    "day",
    "hour",
    "minute",
    "second",
    "day_of_week",
    "day_of_year",
    "daylight_savings",
)

DATES = {
    "today": TODAY,
    "now": TODAY,
    "tomorrow": TODAY + timedelta(days=1),
    "yesterday": TODAY - timedelta(days=1),
}

TZINFOS = dict(gen_tzinfos())

url_quote = lambda url: quote(url, safe=URL_SAFE)


def literal_parse(content: str) -> Any:
    if content.lower() in {"true", "false"}:
        parsed = loads(content.lower())
    else:
        try:
            parsed = literal_eval(content)
        except (ValueError, SyntaxError):
            parsed = content

    return parsed


def cast_url(url_str):
    url = "http://%s" % url_str if "://" not in url_str else url_str
    quoted = url_quote(url)
    parsed = urlparse(quoted)
    response = parsed._asdict()
    response["url"] = parsed.geturl()
    return response


def lookup_street_address(address):
    location = {
        "lat": 0,
        "lon": 0,
        "country": "United States",
        "admin1": "state",
        "admin2": "county",
        "admin3": "city",
        "city": "city",
        "street": "street",
        "postal": "61605",
    }

    return location


def lookup_ip_address(address):
    location = {
        "country": "United States",
        "admin1": "state",
        "admin2": "county",
        "admin3": "city",
        "city": "city",
    }

    return location


def lookup_coordinates(lat, lon):
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


def cast_location(address, loc_type="street_address"):
    GEOLOCATERS = {
        "coordinates": lambda x: lookup_coordinates(*x),
        "street_address": lambda x: lookup_street_address(x),
        "ip_address": lambda x: lookup_ip_address(x),
        "currency": lambda x: CURRENCY_CODES.get(x, {}),
    }

    result = GEOLOCATERS[loc_type](address)

    if result.get("location"):
        extra = LOCATIONS.get(result["location"], {})
        result.update(extra)

    return result


# TODO: inherit from meza
def cast_date(date_str):
    try:
        words = date_str.split(" ")
    except AttributeError:
        date = gmtime(date_str) if hasattr(date_str, "real") else date_str
    else:
        mathish = set(words).intersection(MATH_WORDS)
        textish = set(words).intersection(TEXT_WORDS)

        if date_str[0] in {"+", "-"} and len(mathish) == 1:
            op = sub if date_str.startswith("-") else add
            date = get_date(mathish, words[0][1:], op)
        elif len(textish) == 2:
            date = get_date("%ss" % words[1], 1, add)
        elif date_str in DATES:
            date = DATES.get(date_str)
        else:
            date = parser.parse(date_str, tzinfos=TZINFOS)

    if date:
        normal = normalize_date(date)
        tt = get_tt(normal)

        # Make Sunday the first day of the week
        day_of_w = 0 if tt[6] == 6 else tt[6] + 1
        isdst = None if tt[8] == -1 else bool(tt[8])
        result = {"utime": timegm(tt), "timezone": "UTC", "date": normal}
        result.update(zip(TT_KEYS, tt))  # pylint: disable=W1637
        result.update({"day_of_week": day_of_w, "daylight_savings": isdst})
    else:
        result = {}

    return result


# TODO: see what I can use from meza
CAST_SWITCH = {
    "float": {"default": float("nan"), "func": float},
    "decimal": {"default": Decimal("NaN"), "func": Decimal},
    "int": {"default": 0, "func": lambda i: int(float(i))},
    "text": {"default": "", "func": decode},
    "datetime": {"default": {"date": TODAY}, "func": cast_date},
    # TODO: make this return date without time
    "date": {"default": {"date": TODAY}, "func": cast_date},
    "url": {"default": {}, "func": lambda i: i},
    "location": {"default": {}, "func": cast_location},
    "bool": {"default": False, "func": lambda i: bool(literal_parse(i))},
    "pass": {"default": None, "func": lambda i: i},
    "none": {"default": None, "func": lambda _: None},
}

# funcs = {
#     'num': utils.get_num,
#     'broadcast': utils.broadcast,
#     'dispatch': utils.dispatch,
#     'field': partial(utils.get_field, **kwargs),
#     'conf': partial(utils.parse_conf, **no_conf),
#     'params': partial(utils.parse_params, **no_conf),
#     'value': partial(utils.get_value, **no_conf),
#     'skip': partial(utils.get_skip, **kwargs),
#     'partial': partial,
# }
#
#
# def parse_params(params):
#     true_params = filter(all, params)
#     return dict((x.key, x.value) for x in true_params)
#
#
# def get_word(item):
#     try:
#         raw = ''.join(item.itervalues())
#     except AttributeError:
#         raw = item
#     except TypeError:
#         raw = None
#
#     return raw or ''
#
#
# def get_num(item):
#     try:
#         joined = ''.join(item.itervalues())
#     except AttributeError:
#         joined = item
#
#     try:
#         num = float(joined)
#     except (ValueError, TypeError):
#         num = 0.0
#
#     return num
#
#
# def passthrough(item):
#     return item
#
#
# def passnone(item):
#     return None


def cast(content: Optional[Any] = None, _type="text", **kwargs) -> Any:
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
    try:
        caster = CAST_SWITCH[_type.lower()]
    except KeyError:
        print(f"Unsupported type: {_type}. Returning '{content}' as is.")
        caster = CAST_SWITCH["pass"]

    default = caster["default"]

    if content is None and _type.lower() != "none":
        value = default
    else:
        try:
            value = caster["func"](content, **kwargs)
        except (InvalidOperation, ValueError) as e:
            print(f"Error casting '{content}' to {_type}: {e}. Defaulting to {default}.")
            value = default

    return value
