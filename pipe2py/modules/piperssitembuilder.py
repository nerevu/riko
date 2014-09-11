# piperssitembuilder.py
#

from pipe2py import util
from pipe2py.lib.dotdict import DotDict

# map frontend names to rss items (use dots for sub-levels)
# todo: more?
RSS_SWITCH = {'mediaThumbURL': 'media:thumbnail.url'}

Y_SWITCH = {
    'title': 'y:title',
    'guid': 'y:id',
    # todo: any more??
}


def _gen_key_value(conf, item, **kwargs):
    for key in conf:
        # todo: really dereference item?
        # sample pipe seems to suggest so: surprising
        value = util.get_value(conf[key], item, **kwargs)

        if value:
            yield (RSS_SWITCH.get(key, key), value)

        if value and Y_SWITCH.get(key):
            yield (Y_SWITCH.get(key), value)


def pipe_rssitembuilder(context=None, _INPUT=None, conf=None, **kwargs):
    """This source builds an rss item.

    Keyword arguments:
    context -- pipeline context
    _INPUT -- source generator
    conf:
        dictionary of key/values
    Yields (_OUTPUT):
    item
    """
    conf = DotDict(conf)

    for item in _INPUT:
        d = DotDict(_gen_key_value(conf, DotDict(item), **kwargs))
        [d.set(k, v) for k, v in d.iteritems()]
        yield d

        if item.get('forever'):
            # _INPUT is pipeforever and not a loop,
            # so we just yield our item once
            break
