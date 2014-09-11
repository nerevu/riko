# Author: Gerrit Riessen, gerrit.riessen@open-source-consultants.de
# Copyright (C) 2011 Gerrit Riessen
# This code is licensed under the GNU Public License.

from urllib2 import urlopen
from pipe2py import util
from pipe2py.lib.dotdict import DotDict


def pipe_fetchpage(context=None, _INPUT=None, conf=None, **kwargs):
    """Fetch Page module

    _INPUT -- not used since this does not have inputs.

    conf:
       URL -- url object contain the URL to download
       from -- string from where to start the input
       to -- string to limit the input
       token -- if present, split the input on this token to generate items

       Description: http://pipes.yahoo.com/pipes/docs?doc=sources#FetchPage

       TODOS:
        - don't retrieve pages larger than 200k
        - don't retrieve if page is not indexable.
        - item delimiter removes the closing tag if using a HTML tag
          (not documented but happens)
        - items should be cleaned, i.e. stripped of HTML tags
    """
    conf = DotDict(conf)
    split_token = conf.get('token', **kwargs)
    urls = util.listize(conf['URL'])

    for item in _INPUT:
        for item_url in urls:
            url = util.get_value(DotDict(item_url), DotDict(item), **kwargs)
            url = util.get_abspath(url)

            if not url:
                continue

            f = urlopen(url)

            # TODO: it seems that Yahoo! converts relative links to
            # absolute. This needs to be done on the content but seems to
            # be a non-trival task python?
            content = unicode(f.read(), 'utf-8')

            if context and context.verbose:
                print '............Content .................'
                print content
                print '...............EOF...................'

            from_delimiter = conf.get("from", **kwargs)
            to_delimiter = conf.get("to", **kwargs)
            split_token = conf.get("token", **kwargs)

            # determine from location, i.e. from where to start reading
            # content
            from_location = 0

            if from_delimiter != "":
                from_location = content.find(from_delimiter)
                # Yahoo! does not strip off the from_delimiter.
                # if from_location > 0:
                # from_location += len(from_delimiter)

            # determine to location, i.e. where to stop reading content
            to_location = 0

            if to_delimiter != "":
                to_location = content.find(to_delimiter, from_location)

            # reduce the content depended on the to/from locations
            if from_location > 0 and to_location > 0:
                content = content[from_location:to_location]
            elif from_location > 0:
                content = content[from_location:]
            elif to_location > 0:
                content = content[:to_location]

            items = content.split(split_token) if split_token else [content]

            if context and context.verbose:
                print "FetchPage: found count items:", len(items)

            for i in items:
                if context and context.verbose:
                    print "--------------item data --------------------"
                    print i
                    print "--------------EOF item data ----------------"

                yield {"content": i}

        if item.get('forever'):
            # _INPUT is pipeforever and not a loop,
            # so we just yield our item once
            break
