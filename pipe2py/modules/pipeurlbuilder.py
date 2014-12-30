# -*- coding: utf-8 -*-
# vim: sw=4:ts=4:expandtab
"""
    pipe2py.modules.pipeurlbuilder
    ~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

    http://pipes.yahoo.com/pipes/docs?doc=url#URLBuilder
"""

import urllib
from itertools import imap, ifilter
from pipe2py.lib import utils
from pipe2py.lib.dotdict import DotDict



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
    path_defs = map(DotDict, utils.listize(conf['PATH']))

    for item in _INPUT:
        _input = DotDict(item)
        base = utils.get_value(conf['BASE'], _input, **kwargs)
        pairs = (utils.parse_conf(p, _input, **kwargs) for p in param_defs)
        paths = (utils.get_value(p, _input, **kwargs) for p in path_defs)
        true_params = ifilter(all, pairs)
        real_params = dict((p.key, p.value) for p in true_params)
        _output = parse_base(base, paths, real_params)
        yield _output
