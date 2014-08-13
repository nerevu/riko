# pipefetch.py
#

import feedparser
feedparser.USER_AGENT = "pipe2py (feedparser/%s) +https://github.com/ggaughan/pipe2py" % feedparser.__version__

from pipe2py.lib.dotdict import DotDict
from pipe2py import util


def pipe_fetch(context=None, _INPUT=None, conf=None, **kwargs):
    """Fetches and parses one or more feeds to yield the feed entries.

    Keyword arguments:
    context -- pipeline context
    _INPUT -- not used
    conf:
        URL -- url

    Yields (_OUTPUT):
    feed entries
    """
    conf = DotDict(conf)
    urls = util.listize(conf['URL'])

    for item in _INPUT:
        for item_url in urls:
            url = util.get_value(DotDict(item_url), DotDict(item), **kwargs)
            url = url if '://' in url else 'http://' + url

            if context and context.verbose:
                print "pipe_fetch loading:", url
            d = feedparser.parse(url.encode('utf-8'))

            for entry in d['entries']:
                if 'updated_parsed' in entry:
                    entry['pubDate'] = entry['updated_parsed']  #map from universal feedparser's normalised names
                    entry['y:published'] = entry['updated_parsed']  #yahoo's own version
                if 'author' in entry:
                    entry['dc:creator'] = entry['author']
                if 'author_detail' in entry:
                    if 'href' in entry['author_detail']:
                        entry['author.uri'] = entry['author_detail']['href']
                    if 'name' in entry['author_detail']:
                        entry['author.name'] = entry['author_detail']['name']
                #todo more!?
                if 'title' in entry:
                    entry['y:title'] = entry['title']  #yahoo's own versions
                if 'id' in entry:
                    entry['y:id'] = entry['id']  #yahoo's own versions
                #todo more!?
                yield entry

        if item.get('forever'):
            # _INPUT is pipeforever and not a loop,
            # so we just yield our item once
            break
