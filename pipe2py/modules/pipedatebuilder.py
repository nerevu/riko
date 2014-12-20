# -*- coding: utf-8 -*-
# vim: sw=4:ts=4:expandtab
"""
    pipe2py.modules.pipedatebuilder
    ~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

    http://pipes.yahoo.com/docs?doc=date#DateBuilder
"""

from pipe2py import util
from pipe2py.lib.dotdict import DotDict
from datetime import timedelta, datetime as dt

SWITCH = {
    'today': dt.today(),
    'tomorrow': dt.today() + timedelta(days=1),
    'yesterday': dt.today() + timedelta(days=-1),

    # better to use utcnow?
    # todo: is this allowed by Yahoo?
    'now': dt.now(),
}


def pipe_datebuilder(context=None, _INPUT=None, conf=None, **kwargs):
    """A date module that converts a text string into a datetime value. Useful
    as terminal data. Loopable.

    Parameters
    ----------
    context : pipe2py.Context object
    _INPUT : pipeforever pipe or an iterable of items
    conf : {'DATE': {'type': 'datetime', 'value': '12/2/2014'}}

    Yields
    ------
    _OUTPUT : date timetuples
    """
    conf = DotDict(conf)
    date_format = conf.get('format', **kwargs)

    for item in _INPUT:
        date = util.get_value(conf['DATE'], DotDict(item), **kwargs).lower()

        if date.endswith(' day') or date.endswith(' days'):
            count = int(date.split(' ')[0])
            new_date = dt.today() + timedelta(days=count)
        elif date.endswith(' year') or date.endswith(' years'):
            count = int(date.split(' ')[0])
            new_date = dt.today().replace(year=dt.today().year + count)
        else:
            new_date = SWITCH.get(date)

        if not new_date:
            new_date = util.get_date(date)

        if not new_date:
            raise Exception('Unexpected date format: %s' % date_format)

        yield new_date.timetuple()
