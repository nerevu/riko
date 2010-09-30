# pipefetchdata.py
#

import urllib2
from xml.etree import cElementTree as ElementTree

try:
    import wingdbstub
except:
    pass

try:
    import json
except ImportError:
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
    url = util.get_value(conf['URL'], kwargs) #todo use subkey?
    path = util.get_value(conf['path'], kwargs) #todo use subkey?
    match = None
    
    f = urllib2.urlopen(url)
    
    #Parse the file into a dictionary
    try:
        ft = ElementTree.parse(f)
        if context.verbose:
            print "pipe_fetchdata loading xml:", url
        root = ft.getroot()
        #Move to the point referenced by the path
        #todo lxml would simplify and speed up this
        if path:
            namespace = root.tag[1:].split("}")[0]
            for i in path.split(".")[:-1]:
                root = root.find("{%s}%s" % (namespace, i))
                if root is None:
                    return
            match = "{%s}%s" % (namespace, path.split(".")[-1])
        #Convert xml into generation of dicts
        for element in root.findall(match):
            if element.getchildren():
                i = {}
                for c in element.getchildren():
                    tag = c.tag.split('}', 1)[-1]
                    i[tag] = c.text
            else:
                i = dict(element.items())
                i['content'] = element.text
            yield i
            
    except Exception, e:
        try:
            d = json.load(f)
            #todo test:-
            if context.verbose:
                print "pipe_fetchdata loading json:", url
            if path:
                for i in path.split(".")[:-1]:
                    d = d.get(i)
                match = path.split(".")[-1]
            for item in d:
                if not match or item == match:
                    yield d[item]
        except Exception, e:
            #todo try iCal and yield
            #todo try KML and yield
            raise
    
