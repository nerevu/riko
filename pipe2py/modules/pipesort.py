# pipesort.py
#

from operator import itemgetter
from pipe2py import util
from pipe2py.lib.dotdict import DotDict


def _multikeysort(items, order):
    """Sorts a list of items by order

       (items in order preceded with a '-' will sort descending)
    """
    comparers = [
        (
            (itemgetter(x[1:].strip()), -1) if x.startswith('-') else (
                itemgetter(x.strip()), 1
            )
        ) for x in order
    ]

    def comparer(left, right):
        for fn, mult in comparers:
            try:
                result = cmp(fn(left), fn(right))
            except (KeyError, TypeError):
                # todo: perhaps care more if only one side has the missing key
                # todo: handle bool better?
                pass
            else:
                return mult * result

        return 0

    return sorted(items, cmp=comparer)


def _gen_order(keys, **kwargs):
    for key in keys:
        key = DotDict(key)
        field = key.get('field', **kwargs)
        sort_dir = key.get('dir', **kwargs)
        yield '%s%s' % (sort_dir == 'DESC' and '-' or '', field)


def pipe_sort(context=None, _INPUT=None, conf=None, **kwargs):
    """This operator sorts the input source according to the specified key.

    Keyword arguments:
    context -- pipeline context
    _INPUT -- source generator
    kwargs -- other inputs, e.g. to feed terminals for rule values
    conf:
        KEY -- list of fields to sort by

    Yields (_OUTPUT):
    source items sorted by key
    """
    keys = util.listize(conf['KEY'])
    order = _gen_order(keys, **kwargs)

    for item in _multikeysort(_INPUT, order):
        yield item
