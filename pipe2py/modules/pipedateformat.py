# pipedateformat.py
#

import time
from pipe2py.lib.dotdict import DotDict
from pipe2py import util


def pipe_dateformat(context=None, _INPUT=None, conf=None, **kwargs):
    """This source formats a date.

    Keyword arguments:
    context -- pipeline context
    _INPUT -- source generator
    conf:
        format -- date format

    Yields (_OUTPUT):
    formatted date
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
