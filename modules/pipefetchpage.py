# Author: Gerrit Riessen, gerrit.riessen@open-source-consultants.de
# Copyright (C) 2011 Gerrit Riessen
# This code is licensed under the GNU Public License.

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
        print "FetchPage: Preparing to download:",url

    try:
        content = urllib2.urlopen(url).read()

        from_delimiter, to_delimiter = conf["from"]["value"],conf["to"]["value"]
        split_token = conf["token"]["value"]

        # determine from location, i.e. from where to start reading content
        from_location = 0
        if from_delimiter != "":
            from_location = content.find(from_delimiter)
            if from_location > 0:
                from_location += len(from_delimiter)

        # determine to location, i.e. where to stop reading content
        to_location = 0
        if to_delimiter != "":
            to_location = content.find(to_delimiter)

        # reduce the content depended on the to/from locations
        if from_location > 0 and to_location > 0:
            content = content[from_location:to_location]
        elif from_location > 0:
            content = content[from_location:]
        elif to_location > 0:
            content = content[:to_location]

        # determine items depended on the split_token
        items = []
        if split_token != "":
            items = content.split(split_token)
        else:
            items = [content]

        if context.verbose:
            print "FetchPage: found count items:",len(items)

        for item in items:
            yield dict( { "content" : item } )

    except Exception, e:
        if context.verbose:
            print "FetchPage: failed to retrieve from:", url
            import traceback
            traceback.print_exc()
        raise
