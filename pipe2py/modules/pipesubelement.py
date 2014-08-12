# pipesubelement.py
#

from pipe2py import util
from pipe2py.dotdict import DotDict


def pipe_subelement(context=None, _INPUT=None, conf=None, **kwargs):
    """Returns a subelement.

    Keyword arguments:
    context -- pipeline context
    _INPUT -- source generator
    conf:
        path -- contains the value and type to select

    Yields (_OUTPUT):
    subelement of source item
    """
    conf = DotDict(conf)
    path = conf['path']
    path['subkey'] = path['value']  #switch to using as a reference
    del path['value']

    for item in _INPUT:
        item = DotDict(item)
        t = util.get_value(path, item)
        if t:
            if isinstance(t, list):
                for nested_item in t:
                    yield nested_item
            else:
                yield t

        if item.get('forever'):
            # _INPUT is pipeforever and not a loop,
            # so we just yield our item once
            break
