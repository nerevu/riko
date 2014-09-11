# pipedatebuilder.py
#

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
    """This source builds a date and yields it forever.

    Keyword arguments:
    context -- pipeline context
    _INPUT -- XXX
    conf:
        DATE -- date

    Yields (_OUTPUT):
    date
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
