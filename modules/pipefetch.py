# pipefetch.py
#

import feedparser
from pipe2py import util

def pipe_fetch(context, _INPUT, conf, **kwargs):
    """This source fetches and parses one or more feeds to yield the feed entries.
    
    Keyword arguments:
    context -- pipeline context       
    _INPUT -- not used
    conf:
        URL -- url
    
    Yields (_OUTPUT):
    feed entries
    """
    url = conf['URL']
    
    if not isinstance(url, list):
        url = [url]
    
    for item in url:
        value = util.get_value(item, kwargs)
        
        if context.verbose:
            print "pipe_fetch loading:", value
        d = feedparser.parse(value)
        
        for entry in d['entries']:
            entry['pubDate'] = entry['date_parsed']  #map from universal feedparser's normalised names
            if 'author_detail' in entry:
                entry['author.uri'] = entry['author_detail']['href']
                entry['author.name'] = entry['author_detail']['name']
            yield entry

