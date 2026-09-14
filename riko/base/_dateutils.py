# vim: sw=4:ts=4:expandtab
"""
Provides date and time helpers
"""

from collections.abc import Iterator
from datetime import UTC, date, timedelta, timezone, tzinfo
from datetime import datetime as dt
from time import struct_time
from typing import Annotated
from zoneinfo import ZoneInfo, available_timezones

import pytz

TIMEOUT = 60 * 60 * 1
HALF_DAY = 60 * 60 * 12
NOW = dt.now(UTC)
TODAY = NOW.date()

AwareDT = Annotated[dt, "timezone-aware"]
NaiveDT = Annotated[dt, "timezone-naive"]
AwareST = Annotated[struct_time, "timezone-aware"]
NaiveST = Annotated[struct_time, "timezone-naive"]

# Sample a winter and a summer instant so both the standard and the daylight
# abbreviation of every zone are captured, independent of when the module is
# imported (a bare ``dt.now()`` only sees whichever is in effect today, so an
# import in July silently dropped every zone's standard-time name).
_SAMPLE_INSTANTS = (dt(2020, 1, 1, 12, tzinfo=UTC), dt(2020, 7, 1, 12, tzinfo=UTC))

_PREFERRED_ZONES = frozenset(
    {
        "UTC",
        "America/New_York",  # Eastern
        "America/Chicago",  # Cental
        "America/Denver",  # Mountain
        "America/Los_Angeles",  # Pacific
        "America/Anchorage",  # Alaska
        "Pacific/Honolulu",  # Hawaii
    }
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


def get_local_tz(
    try_local_tz: bool | None = True, fallback_tzinfo: tzinfo = UTC
) -> tzinfo:
    _tzinfo = dt.now(UTC).astimezone().tzinfo if try_local_tz else None
    return _tzinfo or fallback_tzinfo


def _add_zones(*zones: str) -> Iterator[tuple[str, tzinfo]]:
    for zone in zones:
        _tzinfo = ZoneInfo(zone)

        for instant in _SAMPLE_INSTANTS:
            if tzname := instant.astimezone(_tzinfo).tzname():
                yield tzname, _tzinfo


def gen_tzinfos() -> Iterator[tuple[str, tzinfo]]:
    # Cover the broad common set first, then re-add the US-preferred zones so a shared
    # abbreviation (``CST``/``EST``/...) resolves to its US zone rather than a foreign
    # one (e.g. Asia/Taipei).
    # TODO: replace with tzdata
    common = available_timezones().intersection(pytz.common_timezones)
    yield from _add_zones(*common.difference(_PREFERRED_ZONES))
    yield from _add_zones(*_PREFERRED_ZONES)


TZINFOS = dict(gen_tzinfos())


def get_tzname(
    _date: AwareDT | NaiveDT | AwareST | NaiveST | date | None,
) -> str | None:
    if isinstance(_date, struct_time):
        tzname = _date.tm_zone
    elif isinstance(_date, dt):
        tzname = _date.tzname()
    else:
        tzname = None

    return tzname


def tzinfo_from_tt(
    tt: AwareST | NaiveST, def_tzinfo: tzinfo | None = None
) -> ZoneInfo | tzinfo | timezone | None:
    """
    Try to get a ZoneInfo from struct_time's tm_zone name,
    falling back to a fixed-offset timezone from tm_gmtoff.
    """
    if tt.tm_zone and tt.tm_zone in TZINFOS:
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
