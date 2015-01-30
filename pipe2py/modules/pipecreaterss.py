# -*- coding: utf-8 -*-
# vim: sw=4:ts=4:expandtab
"""
    pipe2py.modules.pipecreaterss
    ~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

    http://pipes.yahoo.com/pipes/docs?doc=operators#CreateRSS
"""

# Copyright (C) 2011  Nick Savchenko <nsavch@gmail.com>

# Kindly sponsored by Oberst BV, see http://oberst.com/

# This program is free software: you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation, either version 3 of the License, or
# (at your option) any later version.

from __future__ import (
    absolute_import, division, print_function, with_statement,
    unicode_literals)

from pipe2py.lib.dotdict import DotDict

# note: for some reason the config needs to match pubdate but should output
# pubDate
RSS_FIELDS = {
    u'mediaContentHeight': u'mediaContentHeight',
    u'description': u'description',
    u'pubdate': u'pubDate',
    u'mediaThumbHeight': u'mediaThumbHeight',
    u'link': u'link',
    u'guid': u'guid',
    u'mediaThumbURL': u'mediaThumbURL',
    u'mediaContentType': u'mediaContentType',
    u'author': u'author',
    u'title': u'title',
    u'mediaContentWidth': u'mediaContentWidth',
    u'mediaContentURL': u'mediaContentURL',
    u'mediaThumbWidth': u'mediaThumbWidth',
}


def pipe_createrss(context=None, item=None, conf=None, **kwargs):
    """An operator that converts a source into an RSS stream. Not loopable.

    """
    conf = DotDict(conf)

    for item in _INPUT:
        item = DotDict(item)

        yield {
            value: item.get(conf.get(key, **kwargs))
            for key, value in RSS_FIELDS.items()}
