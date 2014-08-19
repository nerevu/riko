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

            parsed = feedparser.parse(url.encode('utf-8'))

            for entry in parsed['entries']:
                entry['pubDate'] = entry.get('updated_parsed')
                entry['y:published'] = entry.get('updated_parsed')
                entry['dc:creator'] = entry.get('author')
                entry['author.uri'] = entry.get('author_detail', {}).get(
                    'href')
                entry['author.name'] = entry.get('author_detail', {}).get(
                    'name')
                entry['y:title'] = entry.get('title')
                entry['y:id'] = entry.get('id')
                # TODO: more?
                yield entry

        if item.get('forever'):
            # _INPUT is pipeforever and not a loop,
            # so we just yield our item once
            break
