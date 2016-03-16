# -*- coding: utf-8 -*-
# vim: sw=4:ts=4:expandtab
"""
    pipe2py.modules.pipeurlbuilder
    ~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

    http://pipes.yahoo.com/pipes/docs?doc=url#URLBuilder
"""

from __future__ import (
    absolute_import, division, print_function, with_statement,
    unicode_literals)

import urllib
from itertools import imap, ifilter, starmap

from pipe2py.lib import utils
from pipe2py.lib.utils import combine_dicts as cdicts

opts = {'parse': False}


@utils.memoize(utils.TIMEOUT)
def parse_result(params, paths, base):
    url = '%s/' % base if not base.endswith('/') else base
    url += '/'.join(imap(str, ifilter(None, paths)))
    url = url.rstrip('/')
    url = utils.url_quote(url)  # Ensure url is valid
    url += '?%s' % urllib.urlencode(params) if params and url else ''
    return url


def pipe_urlbuilder(context=None, item=None, conf=None, **kwargs):
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
    pkwargs = cdicts(opts, kwargs)
    get_params = get_funcs(conf.get('PARAM', []), **kwargs)[0]
    get_paths = get_funcs(conf.get('PATH', []), **pkwargs)[0]
    get_base = get_funcs(conf['BASE'], listize=False, **pkwargs)[0]
    parse_params = utils.parse_params
    split = get_split(item, funcs=[get_params, get_paths, get_base])
    parsed = utils.dispatch(split, *get_dispatch_funcs('pass', parse_params))
    return starmap(parse_result, parsed)
