# pipefetchsitefeed.py
#

try:
    import speedparser as feedparser
except ImportError:
    import feedparser

    feedparser.USER_AGENT = (
        "pipe2py (feedparser/%s) +https://github.com/ggaughan/pipe2py" %
        feedparser.__version__
    )

from urllib2 import urlopen
from pipe2py.lib import autorss
from pipe2py import util
from pipe2py.lib.dotdict import DotDict


def pipe_fetchsitefeed(context=None, _INPUT=None, conf=None, **kwargs):
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
    conf = DotDict(conf)
    urls = util.listize(conf['URL'])

    for item in _INPUT:
        for item_url in urls:
            url = util.get_value(DotDict(item_url), DotDict(item), **kwargs)
            url = util.get_abspath(url)

            if context and context.verbose:
                print "pipe_fetchsitefeed loading:", url

            for link in autorss.getRSSLink(url.encode('utf-8')):
                parsed = feedparser.parse(urlopen(link).read())

                for entry in util.gen_entries(parsed):
                    yield entry

        if item.get('forever'):
            # _INPUT is pipeforever and not a loop,
            # so we just yield our item once
            break
