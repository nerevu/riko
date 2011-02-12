# pipefetchsitefeed.py
#

#Note: this is really a macro module

from pipefeedautodiscovery import pipe_feedautodiscovery
from pipefetch import pipe_fetch
from pipeforever import pipe_forever

from pipe2py import util

def pipe_fetchsitefeed(context, _INPUT, conf, **kwargs):
    """This source fetches and parses the first feed found on one or more sites 
       to yield the feed entries.
    
    Keyword arguments:
    context -- pipeline context       
    _INPUT -- not used
    conf:
        URL -- url
    
    Yields (_OUTPUT):
    feed entries
    """
    forever = pipe_forever(context, None, conf=None)
    
    urls = conf['URL']
    if not isinstance(urls, list):
        urls = [urls]
            
    for item in _INPUT:
        for item_url in urls:
            url = util.get_value(item_url, item, **kwargs)
            
            if not '://' in url:
                url = 'http://' + url
            
            if context.verbose:
                print "pipe_fetchsitefeed loading:", url
            
            for feed in pipe_feedautodiscovery(context, forever, {u'URL': {u'type': u'url', u'value': url}}):
                for feed_item in pipe_fetch(context, forever, {u'URL': {u'type': u'url', u'value': feed['link']}}):
                    yield feed_item
                
        if item == True: #i.e. this is being fed forever, i.e. not in a loop, so we just yield our item once
            break
