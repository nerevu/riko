# -*- coding: utf-8 -*-
# vim: sw=4:ts=4:expandtab
"""
    pipe2py.modules.piperssitembuilder
    ~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

    http://pipes.yahoo.com/pipes/docs?doc=sources#RSSItemBuilder
"""
from __future__ import (
    absolute_import, division, print_function, with_statement,
    unicode_literals)

from functools import partial
from itertools import imap, starmap
from pipe2py.lib import utils
from pipe2py.lib.dotdict import DotDict

# map frontend names to rss items (use dots for sub-levels)
# todo: more?
RSS = {'mediaThumbURL': 'media:thumbnail.url'}
YAHOO = {'title': 'y:title', 'guid': 'y:id'}


def pipe_rssitembuilder(context=None, item=None, conf=None, **kwargs):
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
    get_value = partial(utils.get_value, **kwargs)
    pkwargs = utils.combine_dicts({'parse_func': get_value}, kwargs)
    parse_conf = partial(utils.parse_conf, DotDict(conf), **pkwargs)
    get_RSS = lambda key, value: (RSS.get(key, key), value)
    get_YAHOO = lambda key, value: (YAHOO.get(key), value)
    make_dict = lambda func, conf: dict(starmap(func, conf.iteritems()))
    clean_dict = lambda d: dict(i for i in d.items() if all(i))
    funcs = [partial(make_dict, get_RSS), partial(make_dict, get_YAHOO)]

    finite = utils.finitize(_INPUT)
    inputs = imap(DotDict, finite)
    confs = imap(parse_conf, inputs)
    splits = utils.broadcast(confs, *funcs)
    combined = starmap(utils.combine_dicts, splits)
    result = imap(clean_dict, combined)
    _OUTPUT = imap(DotDict, result)
    return _OUTPUT
