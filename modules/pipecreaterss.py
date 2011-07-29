# implementation of yahoo pipes createrss operator,
# see http://pipes.yahoo.com/pipes/docs?doc=operators#CreateRSS

# Copyright (C) 2011  Nick Savchenko <nsavch@gmail.com>

# Kindly sponsored by Oberst BV, see http://oberst.com/

# This program is free software: you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation, either version 3 of the License, or
# (at your option) any later version.

import sys
from pipe2py import util

RSS_FIELDS = [
    u'mediaContentHeight',
    u'description',
    u'pubdate',
    u'mediaThumbHeight',
    u'link',
    u'guid',
    u'mediaThumbURL',
    u'mediaContentType',
    u'author',
    u'title',
    u'mediaContentWidth',
    u'mediaContentURL',
    u'mediaThumbWidth']

def transform_to_rss(item, conf):
    new = dict()
    for i in RSS_FIELDS:
        try:
            field_conf = conf[i]
            if field_conf['value']:
                new[i] = util.get_subkey(field_conf['value'], item)
        except KeyError:
            continue
    return new

def pipe_createrss(context, _INPUT, conf, **kwargs):
    for item in _INPUT:
        yield transform_to_rss(item, conf)
        
