# pipeyql.py
#

import urllib
import urllib2

try:
    import json
except ImportError:
    import simplejson as json

from pipe2py import util

def pipe_yql(context, _INPUT, conf,  **kwargs):
    """This source issues YQL queries.
    
    Keyword arguments:
    context -- pipeline context
    _INPUT -- not used
    conf:
        yqlquery -- YQL query
        #todo handle envURL
    
    Yields (_OUTPUT):
    query results
    """
    url = "http://query.yahooapis.com/v1/public/yql" #todo get from a config/env file
    
    yql = util.get_value(conf['yqlquery'], kwargs)
    
    query = urllib.urlencode({'q':yql,
                              'format':'json', #todo do we need to handle xml?
                              #todo diagnostics=true e.g. if context.test
                             })
    req = urllib2.Request(url, query)    
    response = urllib2.urlopen(req)    
    
    #Parse the response
    d = json.load(response)
    if context.verbose:
        print "pipe_yql loading json:", yql
    #note: query also has row count
    for item in d['query']['results']['a']:
        yield item
    
