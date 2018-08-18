# -*- coding: utf-8 -*-
# vim: sw=4:ts=4:expandtab
"""
riko.dates
~~~~~~~~~~
Provides date and time helpers
"""
from __future__ import (
    absolute_import, division, print_function, unicode_literals)

from datetime import timedelta, datetime as dt
from time import strptime

import pytz

from pytz import utc
from dateutil.tz import gettz, tzoffset

DATE_FORMAT = '%m/%d/%Y'
DATETIME_FORMAT = '{0} %H:%M:%S'.format(DATE_FORMAT)
TIMEOUT = 60 * 60 * 1
HALF_DAY = 60 * 60 * 12
TODAY = dt.utcnow()


def gen_tzinfos():
    for zone in pytz.common_timezones:
        try:
            tzdate = pytz.timezone(zone).localize(dt.utcnow(), is_dst=None)
        except pytz.NonExistentTimeError:
            pass
        else:
            tzinfo = gettz(zone)

            if tzinfo:
                yield tzdate.tzname(), tzinfo


def get_date(unit, count, op):
    new_month = op(TODAY.month, count) % 12 or 12

    DATES = {
        'seconds': op(TODAY, timedelta(seconds=count)),
        'minutes': op(TODAY, timedelta(minutes=count)),
        'hours': op(TODAY, timedelta(hours=count)),
        'days': op(TODAY, timedelta(days=count)),
        'weeks': op(TODAY, timedelta(weeks=count)),
        'months': TODAY.replace(month=new_month),
        'years': TODAY.replace(year=op(TODAY.year, count)),
    }

    return DATES[unit]


def normalize_date(date):
    try:
        # See if date is a `time.struct_time`
        # if so, convert it and account for leapseconds
        tt, date = date, dt(*date[:5] + (min(date[5], 59),))
    except TypeError:
        pass
    else:
        is_dst = None if tt[8] is -1 else tt[8]

        try:
            tm_zone = tt.tm_zone
        except AttributeError:
            tm_zone = None
            tm_gmtoff = None
        else:
            tm_gmtoff = tt.tm_gmtoff

        if tm_zone:
            date = pytz.timezone(tm_zone).localize(date, is_dst=is_dst)
        elif tm_gmtoff:
            offset = tzoffset(None, tm_gmtoff)
            date.replace(tzinfo=offset)

    # Set timezone to UTC
    try:
        tzdate = date.astimezone(utc) if date.tzinfo else utc.localize(date)
    except AttributeError:
        tzdate = date

    return tzdate


def get_tt(date):
    formatted = ''.join(date.isoformat().rsplit(':', 1))
    sformat = '%Y-%m-%d' if len(formatted) == 10 else '%Y-%m-%dT%H:%M:%S%z'

    try:
        tt = strptime(formatted, sformat)
    except ValueError:
        tt = strptime(formatted[:19], '%Y-%m-%dT%H:%M:%S')

    return tt
