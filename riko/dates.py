# -*- coding: utf-8 -*-
# vim: sw=4:ts=4:expandtab
"""
riko.dates
~~~~~~~~~~
Provides date and time helpers
"""
from __future__ import (
    absolute_import, division, print_function, unicode_literals)

from datetime import timedelta, time, datetime as dt
from time import gmtime
from calendar import timegm
from operator import add, sub
from time import strptime

import pytz

from pytz import utc
from dateutil import parser
from dateutil.tz import gettz, tzoffset

DATE_FORMAT = '%m/%d/%Y'
DATETIME_FORMAT = '{0} %H:%M:%S'.format(DATE_FORMAT)
TIMEOUT = 60 * 60 * 1
HALF_DAY = 60 * 60 * 12
TODAY = dt.utcnow()

DATES = {
    'today': TODAY,
    'now': TODAY,
    'tomorrow': TODAY + timedelta(days=1),
    'yesterday': TODAY - timedelta(days=1)}

MATH_WORDS = {'seconds', 'minutes', 'hours', 'days', 'weeks', 'months', 'years'}
TEXT_WORDS = {'last', 'next', 'week', 'month', 'year'}
TT_KEYS = (
    'year', 'month', 'day', 'hour', 'minute', 'second', 'day_of_week',
    'day_of_year', 'daylight_savings')


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


TZINFOS = dict(gen_tzinfos())


def get_date(unit, count, op):
    DATES = {
        'seconds': op(TODAY, timedelta(seconds=count)),
        'minutes': op(TODAY, timedelta(minutes=count)),
        'hours': op(TODAY, timedelta(hours=count)),
        'days': op(TODAY, timedelta(days=count)),
        'weeks': op(TODAY, timedelta(weeks=count)),
        # TODO: fix for when new month is not in 1..12
        'months': TODAY.replace(month=op(TODAY.month, count)),
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


def cast_date(date_str):
    try:
        words = date_str.split(' ')
    except AttributeError:
        date = gmtime(date_str) if hasattr(date_str, 'real') else date_str
    else:
        mathish = set(words).intersection(MATH_WORDS)
        textish = set(words).intersection(TEXT_WORDS)

        if date_str[0] in {'+', '-'} and len(mathish) == 1:
            op = sub if date_str.startswith('-') else add
            date = get_date(mathish, words[0][1:], op)
        elif len(textish) == 2:
            op = add if date_str.startswith('last') else add
            date = get_date('%ss' % words[1], 1, op)
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
        result = {'utime': timegm(tt), 'timezone': 'UTC', 'date': normal}
        result.update(zip(TT_KEYS, tt))  # pylint: disable=W1637
        result.update({'day_of_week': day_of_w, 'daylight_savings': isdst})
    else:
        result = {}

    return result
