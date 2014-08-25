# piperssitembuilder.py
#

import urllib
from pipe2py import util
from pipe2py.lib.dotdict import DotDict

# map frontend names to rss items (use dots for sub-levels)
# todo: more?
map_key_to_rss = {'mediaThumbURL': 'media:thumbnail.url'}


def pipe_rssitembuilder(context=None, _INPUT=None, conf=None, **kwargs):
    """This source builds an rss item.

    Keyword arguments:
    context -- pipeline context
    _INPUT -- source generator
    conf:
        dictionary of key/values
    Yields (_OUTPUT):
    item
    """
    conf = DotDict(conf)

    for item in _INPUT:
        item = DotDict(item)
        d = DotDict()

        for key in conf:
            try:
                value = util.get_value(conf[key], item, **kwargs)  #todo really dereference item? (sample pipe seems to suggest so: surprising)
            except KeyError:
                continue  #ignore if the source doesn't have our source field (todo: issue a warning if debugging?)

            key = map_key_to_rss.get(key, key)

            if value:
                if key == 'title':
                    d.set('y:%s' % key, value)
                #todo also for guid -> y:id (is guid the only one?)

                #todo try/except?
                d.set(key, value)

        yield d

        if item.get('forever'):
            # _INPUT is pipeforever and not a loop,
            # so we just yield our item once
            break
