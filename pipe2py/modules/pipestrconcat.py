# pipestrconcat.py  #aka stringbuilder
#

from pipe2py import util
from pipe2py.lib.dotdict import DotDict


def _gen_string(parts, item, context=None, **kwargs):
    for part in parts:
        try:
            yield util.get_value(DotDict(part), item, **kwargs)
        except AttributeError:
            # ignore if the item is referenced but doesn't have our source
            # field
            # todo: issue a warning if debugging?
            continue
        except TypeError:
            if context and context.verbose:
                print "pipe_strconcat: TypeError"


def pipe_strconcat(context=None, _INPUT=None, conf=None, **kwargs):
    """This source builds a string.

    Keyword arguments:
    context -- pipeline context
    _INPUT -- source generator
    conf:
        part -- parts

    Yields (_OUTPUT):
    string
    """
    conf = DotDict(conf)
    parts = util.listize(conf['part'])

    for item in _INPUT:
        yield ''.join(_gen_string(parts, DotDict(item), context, **kwargs))
