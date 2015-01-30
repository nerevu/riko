# -*- coding: utf-8 -*-
# vim: sw=4:ts=4:expandtab
"""
    pipe2py.modules.pipexpathfetchpage
    ~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

    http://pipes.yahoo.com/pipes/docs?doc=sources#XPathFetchPage
"""

from __future__ import (
    absolute_import, division, print_function, with_statement,
    unicode_literals)

from urllib2 import urlopen
from lxml import html
from lxml.html import html5parser
from pipe2py.lib import utils
from pipe2py.lib.dotdict import DotDict


def pipe_xpathfetchpage(context=None, item=None, conf=None, **kwargs):
    """A source that fetches the content of a given website as DOM nodes or a
    string. Loopable.

    context : pipe2py.Context object
    _INPUT : pipeforever pipe or an iterable of items or fields
    conf : dict
       URL -- url object contain the URL to download
       xpath -- xpath to extract
       html5 -- use html5 parser?
       useAsString -- emit items as string?

       TODOS:
        - don't retrieve pages larger than 1.5MB
        - don't retrieve if page is not indexable.

    Yields
    ------
    _OUTPUT : items
    """
    conf = DotDict(conf)
    urls = utils.listize(conf['URL'])

    for item in _INPUT:
        for item_url in urls:
            url = utils.get_value(DotDict(item_url), DotDict(item), **kwargs)
            url = utils.get_abspath(url)
            f = urlopen(url)

            # TODO: it seems that Yahoo! converts relative links to
            # absolute. This needs to be done on the content but seems to
            # be a non-trival task python?
            content = unicode(f.read(), 'utf-8')

            if context and context.verbose:
                print('............Content .................')
                print(content)
                print('...............EOF...................')

            xpath = conf.get('xpath', **kwargs)
            html5 = conf.get('html5', **kwargs) == 'true'
            use_as_string = conf.get('useAsString', **kwargs) == 'true'
            tree = html5parser.parse(f) if html5 else html.parse(f)
            root = tree.getroot()
            items = root.xpath(xpath)

            if context and context.verbose:
                print('XPathFetchPage: found count items:', len(items))

            for etree in items:
                i = utils.etree_to_dict(etree)

                if context and context.verbose:
                    print('--------------item data --------------------')
                    print(i)
                    print('--------------EOF item data ----------------')

                if use_as_string:
                    yield {'content': unicode(i)}
                else:
                    yield i

        if item.get('forever'):
            # _INPUT is pipeforever and not a loop,
            # so we just yield our item once
            break
