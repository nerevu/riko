# vim: sw=4:ts=4:expandtab
"""
Provides date and time helpers
"""

from calendar import timegm
from collections.abc import Callable
from datetime import UTC, date, timedelta, tzinfo
from datetime import datetime as dt
from time import struct_time
from typing import Annotated, overload

from dateutil.relativedelta import relativedelta

from riko._date_utils import tzinfo_from_tt
from riko.types._scalars import DateDict

TIMEOUT = 60 * 60 * 1
HALF_DAY = 60 * 60 * 12
NOW = dt.now(UTC)
TODAY = NOW.date()

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


def get_date(unit: str, count: int, op: Callable) -> date | dt:
    """
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
