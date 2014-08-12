# pipeurlbuilder.py
# vim: sw=4:ts=4:expandtab

import urllib
from pipe2py import util
from pipe2py.dotdict import DotDict


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
    url = None

    for item in _INPUT:
        item = DotDict(item)
        #note: we could cache get_value results if item==True
        url = conf.get('BASE', **kwargs)
        url += '/' if not url.endswith('/') else url

        if 'PATH' in conf:
            path = conf['PATH']
            if not isinstance(path, list):
                path = [path]
            path = [util.get_value(DotDict(p), item, **kwargs) for p in path if p]

            url += "/".join(str(p) for p in path if p)
        url = url.rstrip("/")

        # Ensure url is valid
        url = util.url_quote(url)

        param_defs = conf['PARAM']
        if not isinstance(param_defs, list):
            param_defs = [param_defs]

        params = dict([(util.get_value(DotDict(p['key']), item, **kwargs), util.get_value(DotDict(p['value']), item, **kwargs)) for p in param_defs if p])
        if params and params.keys() != [u'']:
            url += "?" + urllib.urlencode(params)

        yield url
