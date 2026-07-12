# vim: sw=4:ts=4:expandtab
"""
Provides date and time helpers
"""

from calendar import timegm
from collections.abc import Callable, Iterator
from datetime import UTC, date, timedelta, timezone, tzinfo
from datetime import datetime as dt
from functools import cache
from time import strptime, struct_time
from typing import Annotated, Literal, cast, overload
from zoneinfo import ZoneInfo, available_timezones

import pytz
from dateutil import parser

from riko.types.values import DateDict

TIMEOUT = 60 * 60 * 1
HALF_DAY = 60 * 60 * 12
NOW = dt.now(UTC)
TODAY = NOW.date()
EPOCH_DATETIME = dt(1970, 1, 1, 0, 0, 0, tzinfo=UTC)
EPOCH_DATE = date(EPOCH_DATETIME.year, EPOCH_DATETIME.month, EPOCH_DATETIME.day)

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

AwareDT = Annotated[dt, "timezone-aware"]
NaiveDT = Annotated[dt, "timezone-naive"]
AwareST = Annotated[struct_time, "timezone-aware"]
NaiveST = Annotated[struct_time, "timezone-naive"]


@cache
def _parse_date_cached(value: str) -> dt | BaseException:
    # cache doesn't work with exceptions, so we return the exception and raise it in the
    # caller
    try:
        return parser.parse(value, tzinfos=TZINFOS)
    except Exception as e:  # noqa: BLE001
        return e


def parse_date_string(value: str) -> dt:
    """
    Examples:
        >>> _parse_date_cached.cache_clear()
        >>> from datetime import datetime
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

    return cast(dt, result)


def gen_tzinfos() -> Iterator[tuple[str, tzinfo]]:
    # TODO: replace with tzdata
    for zone in pytz.common_timezones:
        _tzinfo = ZoneInfo(zone)

        try:
            tzdate = dt.now(UTC).astimezone(_tzinfo)
        except pytz.NonExistentTimeError:
            pass
        else:
            tzname = tzdate.tzname()

            if _tzinfo and tzname:
                yield tzname, _tzinfo


TZINFOS = dict(gen_tzinfos())


def get_tzname(
    _date: AwareDT | NaiveDT | AwareST | NaiveST | date | None,
) -> str | None:
    tzname = None

    if isinstance(_date, struct_time):
        tzname = _date.tm_zone
    elif isinstance(_date, dt):
        tzname = _date.tzname()

    return tzname


def tzinfo_from_tt(
    tt: AwareST | NaiveST, def_tzinfo: tzinfo | None = None
) -> ZoneInfo | tzinfo | timezone | None:
    """
    Try to get a ZoneInfo from struct_time's tm_zone name,
    falling back to a fixed-offset timezone from tm_gmtoff.
    """
    if not tt:
        _tzinfo = None
    elif tt.tm_zone and tt.tm_zone in available_timezones():
        _tzinfo = ZoneInfo(tt.tm_zone)
    elif tt.tm_zone and tt.tm_zone in TZINFOS:
        _tzinfo = TZINFOS[tt.tm_zone]
    elif tt.tm_gmtoff is not None:
        _tzinfo = timezone(timedelta(seconds=tt.tm_gmtoff), name=tt.tm_zone or "")
    else:
        _tzinfo = def_tzinfo

    return _tzinfo


def get_tzinfo(
    _date: AwareDT | NaiveDT | AwareST | NaiveST | date,
    def_tzinfo: tzinfo | None = None,
) -> tzinfo | None:
    _tzinfo = None

    if isinstance(_date, struct_time):
        _tzinfo = tzinfo_from_tt(_date, def_tzinfo=def_tzinfo)
    elif isinstance(_date, dt):
        _tzinfo = _date.tzinfo or def_tzinfo

    return _tzinfo


def get_date(unit: str, count: int, op: Callable) -> date:
    today = dt.now(timezone.utc).date()
    new_month = op(today.month, count) % 12 or 12

    dates: dict[str, date] = {
        "seconds": op(today, timedelta(seconds=count)),
        "minutes": op(today, timedelta(minutes=count)),
        "hours": op(today, timedelta(hours=count)),
        "days": op(today, timedelta(days=count)),
        "weeks": op(today, timedelta(weeks=count)),
        "months": today.replace(month=new_month),
        "years": today.replace(year=op(today.year, count)),
    }

    return dates[unit]


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
    tt: struct_time | None,
    as_date: bool = False,
    def_tzinfo: tzinfo | None = None,
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
        result = {"utime": timegm(tt), "timezone": tm_zone, "date": normal}
        result.update(zip(TT_KEYS, tt, strict=False))  # pylint: disable=W1637
        result.update({"day_of_week": day_of_w, "daylight_savings": isdst})
    else:
        result = None

    return result


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
        formatted = content.isoformat()
        sformat = "%Y-%m-%dT%H:%M:%S%z"
        tt = strptime(formatted[:19] + formatted[-6:], sformat)
    elif isinstance(content, dt):
        sformat = "%Y-%m-%dT%H:%M:%S"
        tt = strptime(content.isoformat()[:19], sformat)
    elif content:
        sformat = "%Y-%m-%d"
        tt = strptime(content.isoformat(), sformat)
    else:
        tt = None

    return tt


@overload
def ensure_tzinfo(  # noqa: E704
    _date: None, try_local_tz: bool = ..., fallback_tzinfo: tzinfo = ...
) -> None: ...
@overload  # noqa: E302
def ensure_tzinfo(  # noqa: E704
    _date: str, try_local_tz: bool = ..., fallback_tzinfo: tzinfo = ...
) -> AwareDT: ...
@overload  # noqa: E302
def ensure_tzinfo(  # noqa: E704
    _date: AwareDT | NaiveDT, try_local_tz: bool = ..., fallback_tzinfo: tzinfo = ...
) -> AwareDT: ...
@overload  # noqa: E302
def ensure_tzinfo(  # noqa: E704
    _date: AwareST | NaiveST, try_local_tz: bool = ..., fallback_tzinfo: tzinfo = ...
) -> AwareST: ...
@overload  # noqa: E302
def ensure_tzinfo(  # noqa: E704
    _date: date, try_local_tz: bool = ..., fallback_tzinfo: tzinfo = ...
) -> date: ...
def ensure_tzinfo(  # noqa: E302
    _date: AwareDT | NaiveDT | AwareST | NaiveST | date | str | None,
    try_local_tz: bool = True,
    fallback_tzinfo: tzinfo = UTC,
) -> AwareDT | AwareST | date | None:
    now = dt.now(UTC)
    _tzinfo = None
    new_date = None

    if isinstance(_date, str):
        try:
            _date = dt.fromisoformat(_date)
        except (ValueError, TypeError):
            _date = parse_date_string(_date)

    if get_tzname(_date):
        new_date = _date
    else:
        if try_local_tz:
            _tzinfo = now.astimezone().tzinfo

        if not _tzinfo:
            _tzinfo = fallback_tzinfo

        if isinstance(_date, struct_time):
            new_date = tt_to_datetime(_date, def_tzinfo=fallback_tzinfo)
            new_date = date_to_tt(new_date)
        elif isinstance(_date, dt):
            new_date = dt.replace(_date, tzinfo=_tzinfo)
        elif isinstance(_date, date):
            new_date = _date

    return new_date
