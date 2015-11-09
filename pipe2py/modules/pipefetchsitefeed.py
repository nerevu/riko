# -*- coding: utf-8 -*-
# vim: sw=4:ts=4:expandtab
"""
    pipe2py.modules.pipefetchsitefeed
    ~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

    http://pipes.yahoo.com/pipes/docs?doc=sources#FetchSiteFeed
"""

from __future__ import (
    absolute_import, division, print_function, with_statement,
    unicode_literals)

import speedparser

from urllib2 import urlopen
from pipe2py.lib import autorss
from pipe2py.lib import utils
from pipe2py.lib.dotdict import DotDict


def pipe_fetchsitefeed(context=None, _INPUT=None, conf=None, **kwargs):
    """A source that fetches and parses the first feed found on one or more
    sites. Loopable.

    Parameters
    ----------
    context : pipe2py.Context object
    _INPUT : pipeforever pipe or an iterable of items or fields
    conf : URL -- url

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

            if context and context.verbose:
                print("pipe_fetchsitefeed loading:", url)

            for link in autorss.getRSSLink(url.encode('utf-8')):
                parsed = speedparser.parse(urlopen(link).read())

                for entry in utils.gen_entries(parsed):
                    yield entry

        if item.get('forever'):
            # _INPUT is pipeforever and not a loop,
            # so we just yield our item once
            break
