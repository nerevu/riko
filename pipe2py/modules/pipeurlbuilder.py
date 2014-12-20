# -*- coding: utf-8 -*-
# vim: sw=4:ts=4:expandtab
"""
    pipe2py.modules.pipeurlbuilder
    ~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

    http://pipes.yahoo.com/pipes/docs?doc=url#URLBuilder
"""

import urllib
from pipe2py import util
from pipe2py.lib.dotdict import DotDict


def _gen_params(param_defs, item, **kwargs):
    for p in param_defs:
        p = DotDict(p)
        key = util.get_value(p['key'], item, **kwargs)
        value = util.get_value(p['value'], item, **kwargs)
        yield (key, value)


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
    paths = util.listize(conf.get('PATH'))  # use .get() incase 'PATH' isnt set
    param_defs = util.listize(conf['PARAM'])
    url = None

    for item in _INPUT:
        # if _INPUT is pipeforever and not a loop, get values from cache
        if not url:
            item = DotDict(item)
            forever = item.get('forever')
            url = conf.get('BASE', **kwargs)
            url += '/' if not url.endswith('/') else url
            url += "/".join(str(p) for p in paths if p)
            url = url.rstrip("/")
            url = util.url_quote(url)  # Ensure url is valid
            params = dict(_gen_params(param_defs, item, **kwargs))

            if params and params.keys() != [u'']:
                url += "?" + urllib.urlencode(params)

        yield url
        url = url if forever else None
