# pipefetch.py
#

import feedparser
from pipe2py import util

def pipe_fetch(_INPUT, conf, **kwargs):
    """This source fetches and parses one or more feeds to yield the feed entries.
    
    Keyword arguments:
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
        
        d = feedparser.parse(value)
        
        for entry in d['entries']:
            yield entry

# Example use
if __name__ == '__main__':
    feeds = pipe_fetch(None, conf={"URL":[{"value":"../test/feed.xml"}]})
    for f in feeds:
        print f
        print f.keys()
