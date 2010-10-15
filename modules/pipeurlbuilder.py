# pipeurlbuilder.py
#

import urllib
from pipe2py import util

def pipe_urlbuilder(context, _INPUT, conf, **kwargs):
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
    url = util.get_value(conf['BASE'], None, **kwargs)
    if not url.endswith('/'):
        url += '/'
    
    path = util.get_value(conf['PATH'], None, **kwargs)
    if not isinstance(path, list):
        path = [path]
    
    url += "/".join(path)
    
    params = dict([(util.get_value(p['key'], None, **kwargs), util.get_value(p['value'], None, **kwargs)) for p in conf['PARAM']]) #todo use subkey?   
    if params:
        url += "?" + urllib.urlencode(params)
    
    while True:
        yield url

