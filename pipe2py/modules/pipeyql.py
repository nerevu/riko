# pipeyql.py
#

import requests

from lxml.etree import parse
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
        r = requests.get(url, params={'q': yql}, stream=True)

        # Parse the response
        tree = parse(r.raw)

        if context and context.verbose:
            print "pipe_yql loading xml:", yql

        root = tree.getroot()

        # note: query also has row count
        results = root.find('results')

        # Convert xml into generation of dicts
        for element in results.getchildren():
            yield util.etree_to_dict(element)

        if item.get('forever'):
            # _INPUT is pipeforever and not a loop,
            # so we just yield our item once
            break
