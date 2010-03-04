# pipefetch.py
#

import feedparser

def pipe_fetch(_INPUT, conf):
    """This source fetches and parses one or more feeds to yield the feed entries.
    
    Keyword arguments:
    _INPUT -- not used
    conf:
        URL -- url
    
    Yields (_OUTPUT):
    feed entries
    """
    url = conf['URL']
    
    for item in url:
        d = feedparser.parse(item['value'])
        
        for entry in d['entries']:
            yield entry

# Example use
if __name__ == '__main__':
    feeds = pipe_fetch(None, conf={"URL":[{"value":"../test/feed.xml"}]})
    for f in feeds:
        print f
        print f.keys()
