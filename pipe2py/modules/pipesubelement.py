# pipesubelement.py
#

from pipe2py import util
from pipe2py.lib.dotdict import DotDict


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
    for item in _INPUT:
        path = DotDict(item).get(conf['path'], **kwargs)

        for res in path:
            for i in util.gen_items(res, True):
                yield i

        yield util.gen_items()

        if item.get('forever'):
            # _INPUT is pipeforever and not a loop,
            # so we just yield our item once
            break
