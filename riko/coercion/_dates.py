"""Date/time parsing, normalization, and conversion helpers."""

from __future__ import annotations

from datetime import UTC, date, timedelta, tzinfo
from datetime import datetime as dt
from functools import cache
from time import struct_time
from typing import TYPE_CHECKING, Literal, overload

from dateutil import parser
from dateutil.relativedelta import relativedelta

from riko.base._dateutils import (
    TZINFOS,
    AwareDT,
    AwareST,
    NaiveDT,
    NaiveST,
    get_local_tz,
    get_tzname,
    tzinfo_from_tt,
)

if TYPE_CHECKING:
    from collections.abc import Callable

    from riko.types._scalars import DateDict

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


@cache
def _parse_date_cached(value: str) -> dt | BaseException:
    # cache doesn't work with exceptions, so we return the exception and raise it in the
    # caller
    try:
        result = parser.parse(value, tzinfos=TZINFOS)
    except Exception as e:  # noqa: BLE001
        result = e

    return result


def parse_date_string(value: str) -> dt:
    """
    Parses a date string into a datetime object.

    Examples:

        >>> from datetime import datetime
        >>>
        >>> _parse_date_cached.cache_clear()
        >>> isinstance(parse_date_string('2021-01-01'), datetime)
        True
        >>> _ = parse_date_string('2021-01-01')
        >>> _parse_date_cached.cache_info().hits
        1
        >>> _parse_date_cached.cache_clear()
        >>> isinstance(parse_date_string('foo'), datetime)
        Traceback (most recent call last):
            ...
        dateutil.parser._parser.ParserError: Unknown string format: foo
        >>> _ = parse_date_string('foo')
        Traceback (most recent call last):
            ...
        dateutil.parser._parser.ParserError: Unknown string format: foo
        >>> _parse_date_cached.cache_info().hits
        1

    """
    result = _parse_date_cached(value)

    if isinstance(result, BaseException):
        raise result

    return result


@overload
def date_to_datetime(content: None) -> None: ...  # noqa: E704
@overload  # noqa: E302
def date_to_datetime(  # noqa: E704
    content: date, try_local_tz: bool | None = ..., fallback_tzinfo: tzinfo = ...
) -> AwareDT: ...
def date_to_datetime(  # noqa: E302
    content: date | None,
    try_local_tz: bool | None = True,
    fallback_tzinfo: tzinfo = UTC,
) -> AwareDT | None:
    if content:
        _tzinfo = get_local_tz(try_local_tz, fallback_tzinfo)
        _date = dt(content.year, content.month, content.day, tzinfo=_tzinfo)
    else:
        _date = None

    return _date


@overload
def tt_to_datetime(  # noqa: E704
    tt: None, as_date: bool = ..., def_tzinfo: tzinfo | None = ...
) -> None: ...
@overload  # noqa: E302
def tt_to_datetime(  # noqa: E704
    tt: AwareST | NaiveST, as_date: Literal[True], def_tzinfo: tzinfo | None = ...
) -> date: ...
@overload  # noqa: E302
def tt_to_datetime(  # noqa: E704
    tt: AwareST | NaiveST,
    as_date: Literal[False] = ...,
    def_tzinfo: tzinfo | None = ...,
) -> AwareDT | NaiveDT: ...
def tt_to_datetime(  # noqa: E302
    tt: struct_time | None, as_date: bool = False, def_tzinfo: tzinfo | None = None
) -> date | dt | None:
    # convert and account for leapseconds
    if tt:
        _tzinfo = tzinfo_from_tt(tt, def_tzinfo=def_tzinfo)
        result = dt(*tt[:5] + (min(tt[5], 59),), tzinfo=_tzinfo)
        _date = result.date() if as_date else result
    else:
        _date = None

    return _date


@overload
def date_to_tt(content: None) -> None: ...  # noqa: E704
@overload  # noqa: E302
def date_to_tt(content: AwareDT) -> AwareST: ...  # noqa: E704
@overload  # noqa: E302
def date_to_tt(content: NaiveDT | date) -> NaiveST: ...  # noqa: E704
def date_to_tt(  # noqa: E302
    content: AwareDT | NaiveDT | date | None,
) -> AwareST | NaiveST | None:
    tzname = get_tzname(content)

    if isinstance(content, dt) and tzname:
        if utcoffset := content.utcoffset():
            tm_gmtoff = int(utcoffset.total_seconds())
        else:
            tm_gmtoff = 0

        tt = struct_time(content.timetuple() + (tzname, tm_gmtoff))
    elif content:
        tt = content.timetuple()
    else:
        tt = None

    return tt


@overload
def tt_to_datedict(  # noqa: E704
    tt: None, normal: date, def_tzinfo: tzinfo | None = ...
) -> None: ...
@overload  # noqa: E302
def tt_to_datedict(  # noqa: E704
    tt: AwareST | NaiveST, normal: date, def_tzinfo: tzinfo | None = ...
) -> DateDict: ...
def tt_to_datedict(  # noqa: E302
    tt: struct_time | None, normal: date, def_tzinfo: tzinfo | None = None
) -> DateDict | None:
    # Make Sunday the first day of the week
    if tt:
        day_of_w = 0 if tt[6] == 6 else tt[6] + 1
        isdst = None if tt[8] == -1 else bool(tt[8])
        _tzinfo = tzinfo_from_tt(tt, def_tzinfo=def_tzinfo)
        tm_zone = _tzinfo.tzname(None) if _tzinfo else None
        aware = dt(*tt[:5], min(tt[5], 59), tzinfo=_tzinfo or UTC)
        result = {"utime": int(aware.timestamp()), "timezone": tm_zone, "date": normal}
        result.update(zip(TT_KEYS, tt, strict=False))  # pylint: disable=W1637
        result.update({"day_of_week": day_of_w, "daylight_savings": isdst})
    else:
        result = None

    return result


@overload
def normalize_tzinfo(  # noqa: E704
    _date: None, try_local_tz: bool | None = ..., fallback_tzinfo: tzinfo = ...
) -> None: ...
@overload  # noqa: E302
def normalize_tzinfo(  # noqa: E704
    _date: AwareDT | NaiveDT | str,
    try_local_tz: bool | None = ...,
    fallback_tzinfo: tzinfo = ...,
) -> AwareDT: ...
@overload  # noqa: E302
def normalize_tzinfo(  # noqa: E704
    _date: AwareST | NaiveST,
    try_local_tz: bool | None = ...,
    fallback_tzinfo: tzinfo = ...,
) -> AwareST: ...
@overload  # noqa: E302
def normalize_tzinfo(  # noqa: E704
    _date: date, try_local_tz: bool | None = ..., fallback_tzinfo: tzinfo = ...
) -> date: ...
def normalize_tzinfo(  # noqa: E302
    _date: AwareDT | NaiveDT | AwareST | NaiveST | date | str | None,
    try_local_tz: bool | None = True,
    fallback_tzinfo: tzinfo = UTC,
) -> AwareDT | AwareST | date | None:
    """
    Ensures that a datetime or struct_time object has timezone information.

    Examples:

        >>> import time
        >>> from datetime import datetime
        >>>
        >>> st = time.struct_time((2020, 6, 15, 12, 0, 0, 0, 0, -1))
        >>> normalize_tzinfo(st, try_local_tz=False).tm_gmtoff
        0
        >>> local = datetime(2020, 6, 15, 12).astimezone().utcoffset().total_seconds()
        >>> normalize_tzinfo(st, try_local_tz=True).tm_gmtoff == local
        True

    """
    new_date = None

    if isinstance(_date, str):
        try:
            _date = dt.fromisoformat(_date)
        except (ValueError, TypeError):
            _date = parse_date_string(_date)

    if get_tzname(_date):
        new_date = _date
    else:
        _tzinfo = get_local_tz(try_local_tz, fallback_tzinfo)

        if isinstance(_date, struct_time):
            new_date = tt_to_datetime(_date, def_tzinfo=_tzinfo)
            new_date = date_to_tt(new_date)
        elif isinstance(_date, dt):
            new_date = dt.replace(_date, tzinfo=_tzinfo)
        elif isinstance(_date, date):
            new_date = _date

    return new_date


def get_date(unit: str, count: int, op: Callable) -> date | dt:
    """
    Converts a unit of time into a date or datetime object.

    Examples:

        >>> from datetime import datetime
        >>> from operator import add, sub
        >>> from dateutil.relativedelta import relativedelta
        >>>
        >>> today = datetime.now(UTC).date()
        >>> get_date('months', 1, add) == today + relativedelta(months=1)
        True
        >>> get_date('years', 1, sub) == today - relativedelta(years=1)
        True
        >>> isinstance(get_date('seconds', 30, add), datetime)
        True
        >>> get_date('seconds', 30, add) > datetime.now(UTC)
        True

    """
    now = dt.now(UTC)
    today = now.date()

    dates: dict[str, date | dt] = {
        "seconds": op(now, timedelta(seconds=count)),
        "minutes": op(now, timedelta(minutes=count)),
        "hours": op(now, timedelta(hours=count)),
        "days": op(today, timedelta(days=count)),
        "weeks": op(today, timedelta(weeks=count)),
        "months": op(today, relativedelta(months=count)),
        "years": op(today, relativedelta(years=count)),
    }

    return dates[unit]
