# -*- coding: utf-8 -*-
# vim: sw=4:ts=4:expandtab
"""
    pipe2py.modules.pipeurlbuilder
    ~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

    http://pipes.yahoo.com/pipes/docs?doc=url#URLBuilder
"""

import urllib
from functools import partial
from itertools import imap, ifilter, repeat
from pipe2py.lib import utils
from pipe2py.lib.dotdict import DotDict

timeout = 60 * 60 * 1


@utils.memoize(timeout)
def parse_base(base, paths, params):
    url = '%s/' % base if not base.endswith('/') else base
    url += '/'.join(imap(str, ifilter(None, paths)))
    url = url.rstrip('/')
    url = utils.url_quote(url)  # Ensure url is valid
    url += '?%s' % urllib.urlencode(params) if params and url else ''
    return url


def pipe_urlbuilder(context=None, _INPUT=None, conf=None, **kwargs):
    """A url module that builds a url. Loopable.

    Parameters
    ----------
    context : pipe2py.Context object
    _INPUT : pipeforever pipe or an iterable of items or fields
    conf : {
        'PATH': {'type': 'text', 'value': <''>},
        'BASE': {'type': 'text', 'value': <'http://site.com/feed.xml'>},
        'PARAM': [
            {
                'key': {'value': <'order'>},
                'value': {'value': <'desc'>}
            }, {
                'key': {'value': <'page'>},
                'value': {'value': <'2'>}
            }
        ]
    }

    Yields
    ------
    _OUTPUT : url
    """
    conf = DotDict(conf)
    param_defs = map(DotDict, utils.listize(conf['PARAM']))
    get_value = partial(utils.get_value, **kwargs)
    parse_conf = partial(utils.parse_conf, parse_func=get_value, **kwargs)
    get_base = partial(utils.get_value, conf['BASE'], **kwargs)
    get_params = lambda i: imap(parse_conf, param_defs, repeat(i))
    funcs = [utils.passthrough, utils.passthrough, utils.parse_params]

    try:
        path_defs = map(DotDict, utils.listize(conf['PATH']))
    except KeyError:
        get_paths = lambda i: []
    else:
        get_paths = lambda i: imap(get_value, path_defs, repeat(i))

    inputs = imap(DotDict, _INPUT)
    splits = utils.broadcast(inputs, get_base, get_paths, get_params)
    parsed = utils.dispatch(splits, *funcs)
    _OUTPUT = utils.gather(parsed, parse_base)
    return _OUTPUT
