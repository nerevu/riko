# pipeurlbuilder.py
#

import urllib
from pipe2py import util

def pipe_urlbuilder(_INPUT, conf, verbose=False, **kwargs):
    """This source builds a url and yields it forever.
    
    Keyword arguments:
    _INPUT -- not used
    conf:
        BASE -- base
        PATH -- path elements
        PARAM -- query parameters
    
    Yields (_OUTPUT):
    url
    """
    url = util.get_value(conf['BASE'], kwargs)
    if not url.endswith('/'):
        url += '/'
    
    path = util.get_value(conf['PATH'], kwargs)
    if not isinstance(path, list):
        path = [path]
    
    url += "/".join(path)
    
    params = dict([(util.get_value(p['key'], kwargs), util.get_value(p['value'], kwargs)) for p in conf['PARAM']]) #todo use subkey?
    
    url += "?" + urllib.urlencode(params)
    
    while True:
        yield url

