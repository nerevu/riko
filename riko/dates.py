# vim: sw=4:ts=4:expandtab
"""
riko.dates
~~~~~~~~~~
Provides date and time helpers
"""

from calendar import timegm
from collections.abc import Iterator
from datetime import UTC, date, timedelta, timezone, tzinfo
from datetime import datetime as dt
from time import strptime, struct_time
from zoneinfo import ZoneInfo, available_timezones

import pytz

from riko.types.general import DateDict

DATE_FORMAT = "%m/%d/%Y"
DATETIME_FORMAT = f"{DATE_FORMAT} %H:%M:%S"
TIMEOUT = 60 * 60 * 1
HALF_DAY = 60 * 60 * 12
TODAY = dt.now(UTC)
EPOCH_DATETIME = dt(1970, 1, 1, 0, 0, 0, tzinfo=UTC)
EPOCH_DATE = date(EPOCH_DATETIME.year, EPOCH_DATETIME.month, EPOCH_DATETIME.day)
ALTERNATIVE_DATE_FORMATS = (
    "%m-%d-%Y",
    "%m/%d/%y",
    "%m/%d/%Y",
    "%m-%d-%y",
    "%Y-%m-%dt%H:%M:%Sz",
    # todo more: whatever Yahoo can accept
)
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


def get_date(unit: str, count: int, op: callable) -> dt:
    new_month = op(TODAY.month, count) % 12 or 12

    DATES = {
        "seconds": op(TODAY, timedelta(seconds=count)),
        "minutes": op(TODAY, timedelta(minutes=count)),
        "hours": op(TODAY, timedelta(hours=count)),
        "days": op(TODAY, timedelta(days=count)),
        "weeks": op(TODAY, timedelta(weeks=count)),
        "months": TODAY.replace(month=new_month),
        "years": TODAY.replace(year=op(TODAY.year, count)),
    }

    return DATES[unit]


def parse_date(content: str) -> date | dt | None:
    # TODO: see how I do this in csv2ofx`
    parsed = None

    try:
        month, day, year = map(int, content.split("/"))
    except ValueError:
        for date_format in ALTERNATIVE_DATE_FORMATS:
            try:
                parsed = dt.strptime(content, date_format)
            except ValueError:
                pass
            else:
                break
    else:
        parsed = date(year, month, day)

    return parsed


def tzinfo_from_tt(tt: struct_time) -> ZoneInfo | tzinfo | timezone | None:
    """
    Try to get a ZoneInfo from struct_time's tm_zone name,
    falling back to a fixed-offset timezone from tm_gmtoff.
    """
    if tt.tm_zone and tt.tm_zone in available_timezones():
        _tzinfo = ZoneInfo(tt.tm_zone)
    elif tt.tm_zone and tt.tm_zone in TZINFOS:
        _tzinfo = TZINFOS[tt.tm_zone]
    elif tt.tm_gmtoff is not None:
        _tzinfo = timezone(timedelta(seconds=tt.tm_gmtoff), name=tt.tm_zone or "")
    else:
        _tzinfo = None

    return _tzinfo


def tt_to_datetime(tt: struct_time, as_date=False) -> date | dt:
    # convert and account for leapseconds
    _tzinfo = tzinfo_from_tt(tt)
    result = dt(*tt[:5] + (min(tt[5], 59),), tzinfo=_tzinfo)
    return result.date() if as_date else result


def tt_to_datedict(tt: struct_time, normal: date) -> DateDict:
    # Make Sunday the first day of the week
    day_of_w = 0 if tt[6] == 6 else tt[6] + 1
    isdst = None if tt[8] == -1 else bool(tt[8])
    result = {"utime": timegm(tt), "timezone": "UTC", "date": normal}
    result.update(zip(TT_KEYS, tt, strict=False))  # pylint: disable=W1637
    result.update({"day_of_week": day_of_w, "daylight_savings": isdst})
    return result


def date_to_tt(content: date | dt) -> struct_time:
    formatted = "".join(content.isoformat().rsplit(":", 1))
    sformat = "%Y-%m-%d" if len(formatted) == 10 else "%Y-%m-%dT%H:%M:%S%z"

    try:
        tt = strptime(formatted, sformat)
    except ValueError:
        tt = strptime(formatted[:19], "%Y-%m-%dT%H:%M:%S")

    return tt
