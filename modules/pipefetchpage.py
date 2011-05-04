# Author: Gerrit Riessen, gerrit.riessen@open-source-consultants.de
# Copyright (C) 2011 Gerrit Riessen
# This code is licensed under the GNU Public License.

import urllib2
import re
from pipe2py import util

def pipe_fetchpage(context, _INPUT, conf, **kwargs):
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
    urls = conf['URL']
    if not isinstance(urls, list):
        urls = [urls]

    for item in _INPUT:
        for item_url in urls:
            url = util.get_value(item_url, item, **kwargs)
            if context.verbose:
                print "FetchPage: Preparing to download:",url
                
            try:
                request = urllib2.Request(url)
                request.add_header('User-Agent','Yahoo Pipes 1.0')
                request = urllib2.build_opener().open(request)
                content = unicode(request.read(),
                                  request.headers['content-type'].split('charset=')[-1])
        
                # TODO it seems that Yahoo! converts relative links to absolute
                # TODO this needs to be done on the content but seems to be a non-trival
                # TODO task python?
        
                if context.verbose:
                    print "............FetchPage: content ................."
                    print content.encode("utf-8")
                    print "............FetchPage: EOF     ................."
        
                from_delimiter = util.get_value(conf["from"], _INPUT, **kwargs)
                to_delimiter = util.get_value(conf["to"], _INPUT, **kwargs)
                split_token = util.get_value(conf["token"], _INPUT, **kwargs)
        
                # determine from location, i.e. from where to start reading content
                from_location = 0
                if from_delimiter != "":
                    from_location = content.find(from_delimiter)
                    # Yahoo! does not strip off the from_delimiter.
                    #if from_location > 0:
                    #    from_location += len(from_delimiter)
        
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
        
                # determine items depended on the split_token
                res_items = []
                if split_token != "":
                    res_items = content.split(split_token)
                else:
                    res_items = [content]
        
                if context.verbose:
                    print "FetchPage: found count items:",len(res_items)
        
                for res_item in res_items:
                    if context.verbose:
                        print "--------------item data --------------------"
                        print res_item
                        print "--------------EOF item data ----------------"
                    yield { "content" : res_item }
        
            except Exception, e:
                if context.verbose:
                    print "FetchPage: failed to retrieve from:", url
        
                    print "----------------- FetchPage -----------------"
                    import traceback
                    traceback.print_exc()
                    print "----------------- FetchPage -----------------"
                raise

        if item == True: #i.e. this is being fed forever, i.e. not in a loop, so we just yield our item once
            break
            