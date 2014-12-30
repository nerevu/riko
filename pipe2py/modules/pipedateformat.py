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
from pipe2py.lib import utils


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
    loop_with = kwargs.pop('with', None)
    date_format = conf.get('format', **kwargs)
    # timezone = conf.get('timezone', **kwargs)

    for item in _INPUT:
        _with = item.get(loop_with, **kwargs) if loop_with else item

        try:
            # todo: check that all PHP formats are covered by Python
            date_string = time.strftime(date_format, _with)
        except TypeError as e:
            if context and context.verbose:
                print 'Error formatting date: %s' % item
                print e

            continue
        else:
            yield date_string
