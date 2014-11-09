# pipeunion.py
#

from pipe2py import util


def pipe_union(context=None, _INPUT=None, conf=None, **kwargs):
    """This operator merges up to 5 source together.

    Keyword arguments:
    context -- pipeline context
    _INPUT -- source generator
    kwargs -- _OTHER1 - another source generator
              _OTHER2 etc.

    Yields (_OUTPUT):
    union of all source items
    """
    for item in _INPUT:
        # this is being fed forever, i.e. not a real source so just use _OTHERs
        if item.get('forever'):
            break

        yield item

    # todo: can the multiple sources should be pulled over multiple servers?
    sources = (
        items for src, items in kwargs.items() if src.startswith('_OTHER')
    )

    for item in util.multiplex(sources):
        yield item
