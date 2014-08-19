# pipeyql.py
#

import urllib
import urllib2

from xml.etree import cElementTree as ElementTree
from pipe2py import util
from pipe2py.lib.dotdict import DotDict


def pipe_yql(context=None, _INPUT=None, conf=None, **kwargs):
    """This source issues YQL queries.

    Keyword arguments:
    context -- pipeline context
    _INPUT -- not used
    conf:
        yqlquery -- YQL query
        # todo: handle envURL

    Yields (_OUTPUT):
    query results
    """
    # todo: get from a config/env file
    url = "http://query.yahooapis.com/v1/public/yql"
    conf = DotDict(conf)
    query = conf['yqlquery']

    for item in _INPUT:
        item = DotDict(item)
        yql = util.get_value(query, item, **kwargs)

        # note: we use the default format of xml since json loses some
        # structure
        # todo: diagnostics=true e.g. if context.test
        # todo: consider paging for large result sets
        query = urllib.urlencode({'q':yql,})
        req = urllib2.Request(url, query)
        response = urllib2.urlopen(req)

        #Parse the response
        ft = ElementTree.parse(response)
        if context and context.verbose:
            print "pipe_yql loading xml:", yql
        root = ft.getroot()

        # note: query also has row count
        results = root.find('results')

        # Convert xml into generation of dicts
        for element in results.getchildren():
            yield util.xml_to_dict(element)

        if item.get('forever'):
            # _INPUT is pipeforever and not a loop,
            # so we just yield our item once
            break
