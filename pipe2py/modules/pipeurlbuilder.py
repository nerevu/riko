# pipeurlbuilder.py
# vim: sw=4:ts=4:expandtab

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
    """This source builds a url and yields it forever.

    Keyword arguments:
    context -- pipeline context
    _INPUT -- not used
    conf:
        BASE -- base
        PATH -- path elements
        PARAM -- query parameters

    Yields (_OUTPUT):
    url
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
