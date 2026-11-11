"""Date/time parsing, normalization, and conversion helpers."""

from __future__ import annotations

from datetime import UTC, date, timedelta, timezone, tzinfo
from datetime import datetime as dt
from functools import lru_cache
from time import struct_time
from typing import TYPE_CHECKING, overload
from zoneinfo import ZoneInfo

from dateutil import parser
from dateutil.relativedelta import relativedelta

from riko.base._config import settings as config
from riko.base._dateutils import (
    TZINFOS,
    AwareDT,
    AwareST,
    NaiveDT,
    NaiveST,
    get_tzname,
    load_local_tz,
    resolve_tt_tzinfo,
    resolve_tzinfo,
)

if TYPE_CHECKING:
    from riko.types._scalars import DateDict
    from riko.types._wrappers import Func


@lru_cache(maxsize=config.parsed_date_cache_size)
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
def date_to_datetime(content: None) -> None: ...
@overload
def date_to_datetime(
    content: date, try_local_tz: bool | None = ..., fallback_tzinfo: tzinfo = ...
) -> AwareDT: ...
def date_to_datetime(
    content: date | None,
    try_local_tz: bool | None = True,
    fallback_tzinfo: tzinfo = UTC,
) -> AwareDT | None:
    if content:
        _tzinfo = load_local_tz(try_local_tz, fallback_tzinfo)
        _date = dt(content.year, content.month, content.day, tzinfo=_tzinfo)
    else:
        _date = None

    return _date


@overload
def tt_to_datetime(tt: None, *, def_tzinfo: tzinfo | None = ...) -> None: ...
@overload
def tt_to_datetime(
    tt: AwareST | NaiveST, *, def_tzinfo: tzinfo | None = ...
) -> AwareDT | NaiveDT: ...
def tt_to_datetime(
    tt: struct_time | None, *, def_tzinfo: tzinfo | None = None
) -> dt | None:
    # convert and account for leapseconds
    if tt is None:
        result = None
    else:
        _tzinfo = resolve_tt_tzinfo(tt, def_tzinfo=def_tzinfo)
        result = dt(*tt[:5] + (min(tt[5], 59),), tzinfo=_tzinfo)

    return result


@overload
def date_to_tt(content: None) -> None: ...
@overload
def date_to_tt(content: AwareDT) -> AwareST: ...
@overload
def date_to_tt(content: NaiveDT | date) -> NaiveST: ...
def date_to_tt(content: AwareDT | NaiveDT | date | None) -> AwareST | NaiveST | None:
    tzname = get_tzname(content)

    if isinstance(content, dt) and tzname:
        tm_gmtoff = int((content.utcoffset() or timedelta(0)).total_seconds())
        tt = struct_time(content.timetuple() + (tzname, tm_gmtoff))
    elif content:
        tt = content.timetuple()
    else:
        tt = None

    return tt


def _get_zone_label(moment: AwareDT) -> str:
    if isinstance(moment.tzinfo, ZoneInfo) and "/" in moment.tzinfo.key:
        label = moment.tzinfo.key
    else:
        label = timezone(moment.utcoffset() or timedelta(0)).tzname(None)

    return label


def datetime_to_datedict(moment: dt) -> DateDict:
    """
    Builds a ``datebuilder`` date dict from a datetime.

    A naive datetime is read as UTC. Sub-second precision is dropped.

    Examples:

        >>> from datetime import datetime, timezone, timedelta
        >>>
        >>> moment = datetime(2014, 12, 3, 9, tzinfo=timezone(timedelta(hours=8)))
        >>> built = datetime_to_datedict(moment)
        >>> built["utime"], built["utc_offset"], built["timezone"], built["hour"]
        (1417568400, 28800, 'UTC+08:00', 9)

    """
    aware = resolve_aware_datetime(moment, try_local_tz=False).replace(microsecond=0)
    offset = aware.utcoffset() or timedelta(0)
    dst = aware.dst()

    return {
        "utime": int(aware.timestamp()),
        "utc_offset": int(offset.total_seconds()),
        "timezone": _get_zone_label(aware),
        "year": aware.year,
        "month": aware.month,
        "day": aware.day,
        "hour": aware.hour,
        "minute": aware.minute,
        "second": aware.second,
        "day_of_week": aware.isoweekday() % 7,
        "day_of_year": aware.timetuple().tm_yday,
        "daylight_savings": None if dst is None else bool(dst),
    }


def datedict_to_datetime(value: DateDict) -> AwareDT:
    """
    Converts a ``datebuilder`` date dict back into the aware datetime it describes.

    Only ``utime`` and ``utc_offset`` are read.

    Examples:

        >>> from datetime import datetime, timezone, timedelta
        >>>
        >>> moment = datetime(2020, 6, 15, 9, tzinfo=timezone(timedelta(hours=3)))
        >>> datedict_to_datetime(datetime_to_datedict(moment)).isoformat()
        '2020-06-15T09:00:00+03:00'

    """
    offset = timezone(timedelta(seconds=value["utc_offset"]))
    return dt.fromtimestamp(value["utime"], offset)


@overload
def resolve_aware_datetime(
    _date: None, try_local_tz: bool | None = ..., fallback_tzinfo: tzinfo = ...
) -> None: ...
@overload
def resolve_aware_datetime(
    _date: AwareDT | NaiveDT | str,
    try_local_tz: bool | None = ...,
    fallback_tzinfo: tzinfo = ...,
) -> AwareDT: ...
@overload
def resolve_aware_datetime(
    _date: AwareST | NaiveST,
    try_local_tz: bool | None = ...,
    fallback_tzinfo: tzinfo = ...,
) -> AwareST: ...
@overload
def resolve_aware_datetime(
    _date: date, try_local_tz: bool | None = ..., fallback_tzinfo: tzinfo = ...
) -> date: ...
def resolve_aware_datetime(
    _date: AwareDT | NaiveDT | AwareST | NaiveST | date | str | None,
    try_local_tz: bool | None = True,
    fallback_tzinfo: tzinfo = UTC,
) -> AwareDT | AwareST | date | None:
    """
    Resolves a timezone-aware form of a datetime, struct_time, or date string.

    Examples:

        >>> import time
        >>> from datetime import datetime
        >>>
        >>> st = time.struct_time((2020, 6, 15, 12, 0, 0, 0, 0, -1))
        >>> resolve_aware_datetime(st, try_local_tz=False).tm_gmtoff
        0
        >>> local = datetime.now().astimezone().utcoffset().total_seconds()
        >>> resolve_aware_datetime(st, try_local_tz=True).tm_gmtoff == local
        True

    """
    new_date = None

    if isinstance(_date, str):
        try:
            _date = dt.fromisoformat(_date)
        except (ValueError, TypeError):
            _date = parse_date_string(_date)

    if _date is not None and resolve_tzinfo(_date) is not None:
        new_date = _date
    else:
        _tzinfo = load_local_tz(try_local_tz, fallback_tzinfo)

        if isinstance(_date, struct_time):
            new_date = tt_to_datetime(_date, def_tzinfo=_tzinfo)
            new_date = date_to_tt(new_date)
        elif isinstance(_date, dt):
            new_date = dt.replace(_date, tzinfo=_tzinfo)
        elif isinstance(_date, date):
            new_date = _date

    return new_date


def get_relative_date(unit: str, count: int, op: Func[date], now: dt) -> date | dt:
    """
    Offsets ``now`` (or its date) by ``count`` units of time.

    Args:

        unit: What to offset by: ``seconds``, ``minutes``, or ``hours`` offset ``now``.
            ``days``, ``weeks``, ``months``, or ``years`` offset its date.

        count: How many units to offset by.

        op: ``operator.add`` to move forward or ``operator.sub`` to move back.

        now: The moment to offset from.

    Returns:

        Datetime for sub-day units, and date otherwise.

    Examples:

        >>> from datetime import datetime
        >>> from operator import add, sub
        >>>
        >>> now = datetime(2024, 1, 31, 12, tzinfo=UTC)
        >>> get_relative_date('months', 1, add, now)
        datetime.date(2024, 2, 29)
        >>> get_relative_date('years', 1, sub, now)
        datetime.date(2023, 1, 31)
        >>> get_relative_date('seconds', 30, add, now)
        datetime.datetime(2024, 1, 31, 12, 0, 30, tzinfo=datetime.timezone.utc)

    """
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
