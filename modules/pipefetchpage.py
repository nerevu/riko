# -*- mode: python -*-
#
# Author: Gerrit Riessen, gerrit.riessen@open-source-consultants.de
# Copyright (C) 2011 Gerrit Riessen
# This code is licensed under the GNU Public License.
#
# $Id$
#

import urllib2
import re

def pipe_fetchpage(context, _INPUT, conf, **kwargs):
    """Fetch Page module

    _INPUT -- not used since this does not have inputs.

    conf:
       URL -- url object contain the URL to download
       from -- string from where to start the input
       to -- string to limit the input
       token -- if present, split the input on this token to generate items
    """
    url = conf['URL']["value"]
    if context.verbose:
        print "Preparing to download:",url

    try:
        content = urllib2.urlopen(url).read()
        # have we got a from?
        from_delimiter = conf["from"]["value"]
        from_location = content.find( from_delimiter )
        if from_location > 0:
            from_location += len(from_delimiter)

        # to_delimiter = conf["to"]["value"]
        items = content[from_location:].split( conf["token"]["value"] )
        print items
        for item in items:
            i = dict()
            i['content'] = item
            yield i
    except Exception, e:
        if context.verbose:
            print "failed to retrieve: ", url
