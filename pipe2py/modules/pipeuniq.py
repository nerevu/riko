# pipeuniq.py
#
from pipe2py.lib.dotdict import DotDict


def pipe_uniq(context=None, _INPUT=None, conf=None, **kwargs):
    """This operator filters out non unique items according to the specified
    field.

    Keyword arguments:
    context -- pipeline context
    _INPUT -- source generator
    kwargs -- other inputs, e.g. to feed terminals for rule values
    conf:
        field -- field to be unique

    Yields (_OUTPUT):
    source items, one per unique field value
    """
    seen = set()
    conf = DotDict(conf)
    field = conf.get('field', **kwargs)

    for item in _INPUT:
        value = DotDict(item).get(field)

        if value not in seen:
            seen.add(value)
            yield item
