# -*- coding: utf-8 -*-
# vim: sw=4:ts=4:expandtab
"""
    pipe2py.modules.pipedateformat
    ~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
    Provides methods to format datetime values.

    http://pipes.yahoo.com/pipes/docs?doc=date#DateFormatter
"""

import time
from pipe2py.lib.dotdict import DotDict
from pipe2py import util


def pipe_dateformat(context=None, _INPUT=None, conf=None, **kwargs):
    """Formats a datetime value. Loopable.

    Parameters
    ----------
    context : pipe2py.Context object
    _INPUT : pipedatebuilder pipe like object (iterable of date timetuples)
    conf : {
        'format': {'value': <'%B %d, %Y'>},
        'timezone': {'value': <'EST'>}
    }

    Yields
    ------
    _OUTPUT : formatted dates
    """
    conf = DotDict(conf)
    date_format = conf.get('format', **kwargs)
    date = ()

    for item in _INPUT:
        if not hasattr(item, 'tm_year'):
            date = util.get_date(item)

        date = date.timetuple() if date else item

        if not date:
            raise Exception('Unexpected date format: %s' % date_format)

        try:
            # todo: check that all PHP formats are covered by Python
            date_string = time.strftime(date_format, date)
        except TypeError:
            # silent error handling e.g. if item is not a date
            continue
        else:
            yield date_string
