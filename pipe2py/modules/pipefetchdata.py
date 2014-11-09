# -*- coding: utf-8 -*-
# vim: sw=4:ts=4:expandtab
"""
    pipe2py.modules.pipefetchdata
    ~~~~~~~~~~~~~~
    Provides methods for fetching XML and JSON data sources.

    http://pipes.yahoo.com/pipes/docs?doc=sources#FetchData
"""
from lxml import objectify
from lxml.etree import XMLSyntaxError
from urllib2 import urlopen

try:
    from json import loads
except (ImportError, AttributeError):
    from simplejson import loads

from pipe2py import util
from pipe2py.lib.dotdict import DotDict


def _parse_dict(split_path, element):
    for i in split_path:
        element = element.get(i) if element else None

    return element


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
    >>> abspath = p.abspath(p.join(parent, 'data', 'gigs.json'))
    >>> path = 'value.items'
    >>> url = "file://%s" % abspath
    >>> conf = {'URL': {'value': url}, 'path': {'value': path}}
    >>> pipe_fetchdata(_INPUT=pipe_forever(), conf=conf).next().keys()[:5]
    [u'y:repeatcount', u'description', u'pubDate', u'title', u'y:published']
    >>> abspath = p.abspath(p.join(parent, 'data', 'places.xml'))
    >>> path = 'appointment'
    >>> url = "file://%s" % abspath
    >>> conf = {'URL': {'value': url}, 'path': {'value': path}}
    >>> sorted(pipe_fetchdata(_INPUT=pipe_forever(), conf=conf).next().keys())
    ['alarmTime', 'begin', 'duration', 'places', 'subject', 'uid']
    >>> conf = {'URL': {'value': url}, 'path': {'value': ''}}
    >>> sorted(pipe_fetchdata(_INPUT=pipe_forever(), conf=conf).next().keys())
    ['appointment', 'reminder']
    """
    # todo: iCal and KML
    conf = DotDict(conf)
    urls = util.listize(conf['URL'])

    for item in _INPUT:
        for item_url in urls:
            item = DotDict(item)
            url = util.get_value(DotDict(item_url), item, **kwargs)
            url = util.get_abspath(url)
            f = urlopen(url)
            path = util.get_value(conf['path'], item, **kwargs)
            split_path = path.split(".") if path else []
            res = {}

            try:
                tree = objectify.parse(f)
                root = tree.getroot()
            except XMLSyntaxError:
                if context and context.verbose:
                    print "pipe_fetchdata loading json:", url

                f = urlopen(url)
                element = loads(f.read())
            else:
                if context and context.verbose:
                    print "pipe_fetchdata loading xml:", url

                # print etree.tostring(element, pretty_print=True)
                element = util.etree_to_dict(root)
            finally:
                res = _parse_dict(split_path, element) if element else None

                for i in util.gen_items(res, True):
                    yield i

        if item.get('forever'):
            # _INPUT is pipeforever and not a loop,
            # so we just yield our item once
            break
