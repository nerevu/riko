# pipeurlbuilder.py
#

import urllib
import urllib2
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
        
        if 'PATH' in conf: 
            path = conf['PATH']
            if not isinstance(path, list):
                path = [path]
            path = [util.get_value(p, item, **kwargs) for p in path if p]

            url += "/".join(p for p in path if p)
        url = url.rstrip("/")
        
        #Ensure url is valid
        url = urllib2.quote(url, safe="%/:=&?~#+!$,;'@()*[]")
        
        params = dict([(util.get_value(p['key'], item, **kwargs), util.get_value(p['value'], item, **kwargs)) for p in conf['PARAM'] if p])
        if params and params.keys() != [u'']:
            url += "?" + urllib.urlencode(params)
        
        yield url

