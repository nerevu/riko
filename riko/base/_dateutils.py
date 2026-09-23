# vim: sw=4:ts=4:expandtab
"""
Date and timezone normalization helpers.

Attributes:

    TIMEOUT: One-hour timeout expressed in seconds.
    HALF_DAY: Twelve hours expressed in seconds.
    NOW: UTC datetime captured when the module is imported.
    TODAY: UTC calendar date captured when the module is imported.
    TT_KEYS: Field names used when working with ``struct_time`` values.
    TZINFOS: Timezone-abbreviation lookup built from common IANA zones.

"""

from __future__ import annotations

from datetime import UTC, date, timedelta, timezone, tzinfo
from datetime import datetime as dt
from time import struct_time
from typing import TYPE_CHECKING, Annotated
from zoneinfo import ZoneInfo, available_timezones

import pytz

if TYPE_CHECKING:
    from collections.abc import Iterator


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
    """
    Resolves the host's local timezone or a fallback timezone.

    Args:

        try_local_tz: Whether to inspect the host's local timezone.
        fallback_tzinfo: Timezone returned when local lookup is disabled or fails.

    Returns:

        The resolved local timezone, or ``fallback_tzinfo``.

    Examples:

        >>> from datetime import UTC
        >>>
        >>> get_local_tz(False) is UTC
        True

    """
    _tzinfo = dt.now(UTC).astimezone().tzinfo if try_local_tz else None
    return _tzinfo or fallback_tzinfo


def _add_zones(*zones: str) -> Iterator[tuple[str, tzinfo]]:
    for zone in zones:
        _tzinfo = ZoneInfo(zone)

        for instant in _SAMPLE_INSTANTS:
            if tzname := instant.astimezone(_tzinfo).tzname():
                yield tzname, _tzinfo


def gen_tzinfos() -> Iterator[tuple[str, tzinfo]]:
    """
    Generates timezone-abbreviation mappings from common IANA zones.

    Yields:

        Pairs of timezone abbreviation and corresponding ``ZoneInfo`` object.

    Examples:

        >>> dict(gen_tzinfos())["UTC"].key
        'UTC'

    """
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
    """
    Extracts a timezone name from a datetime or ``struct_time`` value.

    Args:

        _date: Date-like value whose timezone name should be inspected.

    Returns:

        The timezone name when available, otherwise ``None``.

    Examples:

        >>> from datetime import UTC, datetime
        >>>
        >>> get_tzname(datetime(2020, 1, 1, tzinfo=UTC))
        'UTC'
        >>> get_tzname(datetime(2020, 1, 1).date()) is None
        True

    """
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
    Resolves timezone information from a ``struct_time`` value.

    The timezone abbreviation is preferred when it maps to a known IANA zone;
    otherwise a fixed-offset timezone is built from ``tm_gmtoff`` when available.

    Args:

        tt: ``struct_time`` value to inspect.
        def_tzinfo: Fallback timezone when ``tt`` has no timezone information.

    Returns:

        A resolved timezone, fixed-offset timezone, or ``def_tzinfo``.

    Examples:

        >>> from datetime import UTC
        >>> from time import struct_time
        >>>
        >>> tt = struct_time((1970, 1, 1, 0, 0, 0, 3, 1, 0))
        >>> tzinfo_from_tt(tt, UTC) is UTC
        True

    """
    if tt.tm_zone and tt.tm_zone in TZINFOS:
        _tzinfo = TZINFOS[tt.tm_zone]
    elif tt.tm_gmtoff is None:
        _tzinfo = def_tzinfo
    else:
        _tzinfo = timezone(timedelta(seconds=tt.tm_gmtoff), name=tt.tm_zone or "")

    return _tzinfo


def get_tzinfo(
    _date: AwareDT | NaiveDT | AwareST | NaiveST | date,
    def_tzinfo: tzinfo | None = None,
) -> tzinfo | None:
    """
    Resolves timezone information from a datetime or ``struct_time`` value.

    Args:

        _date: Date-like value to inspect.
        def_tzinfo: Fallback timezone for naive datetime or ``struct_time`` values.

    Returns:

        The value's timezone, ``def_tzinfo`` when applicable, or ``None``.

    Examples:

        >>> from datetime import UTC, datetime
        >>>
        >>> get_tzinfo(datetime(2020, 1, 1, tzinfo=UTC)) is UTC
        True
        >>> get_tzinfo(datetime(2020, 1, 1), UTC) is UTC
        True

    """
    _tzinfo = None

    if isinstance(_date, struct_time):
        _tzinfo = tzinfo_from_tt(_date, def_tzinfo=def_tzinfo)
    elif isinstance(_date, dt):
        _tzinfo = _date.tzinfo or def_tzinfo

    return _tzinfo
