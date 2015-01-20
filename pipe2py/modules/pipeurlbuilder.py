# -*- coding: utf-8 -*-
# vim: sw=4:ts=4:expandtab
"""
    pipe2py.modules.pipeurlbuilder
    ~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

    http://pipes.yahoo.com/pipes/docs?doc=url#URLBuilder
"""

import urllib
from itertools import imap, ifilter, starmap
from . import _get_broadcast_funcs as get_funcs, get_dispatch_funcs, get_splits
from pipe2py.lib import utils
from pipe2py.lib.utils import combine_dicts as cdicts

opts = {'parse': False}
timeout = 60 * 60 * 1


@utils.memoize(timeout)
def parse_result(params, paths, base):
    print (params, base, paths)
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
        'PARAM': [
            {'key': {'value': <'order'>}, 'value': {'value': <'desc'>}},
            {'key': {'value': <'page'>}, 'value': {'value': <'2'>}}
        ]
        'PATH': {'type': 'text', 'value': <''>},
        'BASE': {'type': 'text', 'value': <'http://site.com/feed.xml'>},
    }

    Yields
    ------
    _OUTPUT : url
    """
    get_params = get_funcs(conf['PARAM'], **kwargs)[0]
    get_paths = get_funcs(conf.get('PATH', {}), **cdicts(opts, kwargs))[0]
    get_base = get_funcs(conf['BASE'], listize=False, **cdicts(opts, kwargs))[0]
    parse_params = utils.parse_params
    splits = get_splits(_INPUT, funcs=[get_params, get_paths, get_base])
    parsed = utils.dispatch(splits, *get_dispatch_funcs('pass', parse_params))
    _OUTPUT = starmap(parse_result, parsed)
    return _OUTPUT
