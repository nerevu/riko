# -*- coding: utf-8 -*-
# vim: sw=4:ts=4:expandtab
"""
    pipe2py.modules.piperssitembuilder
    ~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

    http://pipes.yahoo.com/pipes/docs?doc=sources#RSSItemBuilder
"""

from pipe2py.lib import utils
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
        value = utils.get_value(conf[key], item, **kwargs)

        if value:
            yield (RSS_SWITCH.get(key, key), value)

        if value and Y_SWITCH.get(key):
            yield (Y_SWITCH.get(key), value)


def pipe_rssitembuilder(context=None, _INPUT=None, conf=None, **kwargs):
    """A source that builds an rss item. Loopable.

    Parameters
    ----------
    context : pipe2py.Context object
    _INPUT : pipeforever asyncPipe or an iterable of items or fields
    conf : {
        'mediaContentType': {'type': 'text', 'value': ''},
        'mediaContentHeight': {'type': 'text', 'value': ''},
        'mediaContentWidth': {'type': 'text', 'value': ''},
        'mediaContentURL': {'type': 'text', 'value': 'url'},
        'mediaThumbHeight': {'type': 'text', 'value': ''},
        'mediaThumbWidth': {'type': 'text', 'value': ''},
        'mediaThumbURL': {'type': 'text', 'value': 'url'},
        'description': {'type': 'text', 'value': 'description'},
        'pubdate': {'type': 'text', 'value': 'pubdate'},
        'author': {'type': 'text', 'value': 'author'},
        'title': {'type': 'text', 'value': 'title'},
        'link': {'type': 'text', 'value': 'url'},
        'guid': {'type': 'text', 'value': 'guid'},
    }

    Yields
    ------
    _OUTPUT : items
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
