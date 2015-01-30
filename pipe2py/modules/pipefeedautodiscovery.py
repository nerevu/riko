# -*- coding: utf-8 -*-
# vim: sw=4:ts=4:expandtab
"""
    pipe2py.modules.pipefeedautodiscovery
    ~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

    http://pipes.yahoo.com/pipes/docs?doc=sources#FeedAutoDiscovery
"""

from __future__ import (
    absolute_import, division, print_function, with_statement,
    unicode_literals)

from pipe2py.lib import autorss, utils
from pipe2py.lib.dotdict import DotDict


def pipe_feedautodiscovery(context=None, item=None, conf=None, **kwargs):
    """A source that searches for and returns feed links found in a page.
    Loopable.

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
                print("pipe_feedautodiscovery loading:", url)

            for entry in autorss.getRSSLink(url.encode('utf-8')):
                yield {'link': entry}
                # todo: add rel, type, title

        if item.get('forever'):
            # _INPUT is pipeforever and not a loop,
            # so we just yield our item once
            break
