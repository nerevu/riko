# pipefetchdata.py
#

import urllib2
from xml.etree import cElementTree as ElementTree

try:
    import json
    json.loads # test access to the attributes of the right json module
except (ImportError, AttributeError):
    import simplejson as json

from pipe2py import util

def pipe_fetchdata(context, _INPUT, conf,  **kwargs):
    """This source fetches and parses any XML or JSON file (todo iCal or KML) to yield a list of elements.
    
    Keyword arguments:
    context -- pipeline context
    _INPUT -- not used
    conf:
        URL -- url
        path -- path to list
    
    Yields (_OUTPUT):
    elements
    """
    urls = conf['URL']
    if not isinstance(urls, list):
        urls = [urls]
    
    for item in _INPUT:
        for item_url in urls:
            url = util.get_value(item_url, item, **kwargs)
        
            if not '://' in url:
                url = 'http://' + url
            path = util.get_value(conf['path'], item, **kwargs)
            match = None
            
            #Parse the file into a dictionary
            try:
                f = urllib2.urlopen(url)
                ft = ElementTree.parse(f)
                if context.verbose:
                    print "pipe_fetchdata loading xml:", url
                root = ft.getroot()
                #Move to the point referenced by the path
                #todo lxml would simplify and speed up this
                if path:
                    if root.tag[0] == '{':
                        namespace = root.tag[1:].split("}")[0]
                        for i in path.split(".")[:-1]:
                            root = root.find("{%s}%s" % (namespace, i))
                            if root is None:
                                return
                        match = "{%s}%s" % (namespace, path.split(".")[-1])
                    else:
                        match = "%s" % (path.split(".")[-1])
                #Convert xml into generation of dicts
                if match:
                    for element in root.findall(match):
                        i = util.etree_to_pipes(element)           
                        yield i
                else:
                    i = util.etree_to_pipes(root)
                    yield i
                    
            except Exception, e:
                try:
                    f = urllib2.urlopen(url)
                    d = json.load(f)
                    #todo test:-
                    if context.verbose:
                        print "pipe_fetchdata loading json:", url
                    if path:
                        for i in path.split(".")[:-1]:
                            d = d.get(i)
                        match = path.split(".")[-1]
                    if match:
                        for itemd in d:
                            if not match or itemd == match:
                                if isinstance(d[itemd], list):
                                    for nested_item in d[itemd]:
                                        yield nested_item
                                else:
                                    yield [d[itemd]]
                    else:
                        yield d
                except Exception, e:
                    #todo try iCal and yield
                    #todo try KML and yield
                    if context.verbose:
                        print "xml and json both failed:"
        
                    raise
        
        if item == True: #i.e. this is being fed forever, i.e. not in a loop, so we just yield our item once
            break
            
