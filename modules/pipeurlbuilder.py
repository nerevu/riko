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
    url = conf['BASE']['value']
    
    #todo PATH (or PATH list)
    
    params = dict([(util.get_value(p['key'], kwargs), util.get_value(p['value'], kwargs)) for p in conf['PARAM']]) #todo use subkey?
    
    url += "?" + urllib.urlencode(params)
    
    while True:
        yield url

