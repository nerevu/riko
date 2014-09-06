# pipeyql.py
#

import urllib
import urllib2

from xml.etree import cElementTree as ElementTree

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
    
    for item in _INPUT:
        yql = util.get_value(conf['yqlquery'], item, **kwargs)
        
        query = urllib.urlencode({'q':yql,
                                  #note: we use the default format of xml since json loses some structure
                                  #todo diagnostics=true e.g. if context.test
                                  #todo consider paging for large result sets
                                 })
        req = urllib2.Request(url, query)    
        response = urllib2.urlopen(req)    
        
        #Parse the response
        ft = ElementTree.parse(response)
        if context.verbose:
            print "pipe_yql loading xml:", yql
        root = ft.getroot()
        #note: query also has row count
        results = root.find('results')
        #Convert xml into generation of dicts
        for element in results.getchildren():
            i = util.xml_to_dict(element)
            yield i
    
        if item == True: #i.e. this is being fed forever, i.e. not in a loop, so we just yield our item once
            break
    
