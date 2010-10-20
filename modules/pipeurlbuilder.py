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
    
    for item in _INPUT:
        #note: we could cache get_value results if item==True
        url = util.get_value(conf['BASE'], item, **kwargs)
        if not url.endswith('/'):
            url += '/'
        
        path = util.get_value(conf['PATH'], item, **kwargs)
        if not isinstance(path, list):
            path = [path]
        
        url += "/".join(path)
        
        params = dict([(util.get_value(p['key'], item, **kwargs), util.get_value(p['value'], item, **kwargs)) for p in conf['PARAM']])
        if params:
            url += "?" + urllib.urlencode(params)
        
        yield url

