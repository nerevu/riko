# -*- coding: utf-8 -*-
# vim: sw=4:ts=4:expandtab
"""
    pipe2py.modules.pipefetchdata
    ~~~~~~~~~~~~~~
    Provides methods for fetching XML and JSON data sources.

    http://pipes.yahoo.com/pipes/docs?doc=sources#FetchData
"""
import urllib2
from xml.etree import cElementTree as ElementTree

try:
    import json
    json.loads # test access to the attributes of the right json module
except (ImportError, AttributeError):
    import simplejson as json

from pipe2py import util
from pipe2py.lib.dotdict import DotDict


def pipe_fetchdata(context=None, _INPUT=None, conf=None, **kwargs):
    """Fetches and parses an XML or JSON file.

    Parameters
    ----------
    context : pipe2py.Context object
    _INPUT : source generator of dicts
    conf : dict
        {
            'URL': {'value': url},
            'path': {'value': dot separated path to data list}
        }

    Yields
    ------
    _OUTPUT : pipe items fetched from source

    Examples
    --------
    >>> from os import path as p
    >>> from pipe2py.modules.pipeforever import pipe_forever
    >>> parent = p.dirname(p.dirname(__file__))
    >>> file_name = p.abspath(p.join(parent, 'data', 'gigs.json'))
    >>> path = 'value.items'
    >>> url = "file://%s" % file_name
    >>> conf = {'URL': {'value': url}, 'path': {'value': path}}
    >>> pipe_fetchdata(_INPUT=pipe_forever(), conf=conf).next().keys()[:5]
    [u'y:repeatcount', u'description', u'pubDate', u'title', u'y:published']
    >>> file_name = p.abspath(p.join(parent, 'data', 'places.xml'))
    >>> path = 'appointment'
    >>> url = "file://%s" % file_name
    >>> conf = {'URL': {'value': url}, 'path': {'value': path}}
    >>> pipe_fetchdata(_INPUT=pipe_forever(), conf=conf).next().keys()
    ['begin', 'uid', 'places', 'alarmTime', 'duration', 'subject']
    >>> conf = {'URL': {'value': url}, 'path': {'value': ''}}
    >>> pipe_fetchdata(_INPUT=pipe_forever(), conf=conf).next().keys()
    ['reminder', 'appointment']
    """
    conf = DotDict(conf)
    urls = util.listize(conf['URL'])

    for item in _INPUT:
        for item_url in urls:
            item = DotDict(item)
            url = util.get_value(DotDict(item_url), item, **kwargs)
            path = util.get_value(conf['path'], item, **kwargs)
            match = None

            #Parse the file into a dictionary
            try:
                f = urllib2.urlopen(url)
                ft = ElementTree.parse(f)
                if context and context.verbose:
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
                    if context and context.verbose:
                        print "pipe_fetchdata loading json:", url
                    if path:
                        for i in path.split(".")[:-1]:
                            d = d.get(i)
                        match = path.split(".")[-1]
                    if match and d is not None:
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
                    if context and context.verbose:
                        print "xml and json both failed:"

                    raise


        if item.get('forever'):
            # _INPUT is pipeforever and not a loop,
            # so we just yield our item once
            break
