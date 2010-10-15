# piperssitembuilder.py
#

import urllib
from pipe2py import util

#map frontend names to rss items (use dots for sub-levels)
map_key_to_rss = {'mediaThumbURL': 'media:thumbnail.url',
                  #todo more?
                 }

def pipe_rssitembuilder(context, _INPUT, conf, **kwargs):
    """This source builds an rss item.
    
    Keyword arguments:
    context -- pipeline context
    _INPUT -- source generator
    conf:
        dictionary of key/values
    Yields (_OUTPUT):
    item
    """
    
    for item in _INPUT:
        d = {}
        
        for key in conf:
            try:
                value = util.get_value(conf[key], item, **kwargs)  #todo really dereference item? (sample pipe seems to suggest so: surprising)
            except KeyError:
                continue  #ignore if the source doesn't have our source field (todo: issue a warning if debugging?)
            
            key = map_key_to_rss.get(key, key)
            
            if value:
                if key == 'title':
                    util.set_value(d, 'y:%s' % key, value)
                #todo also for guid -> y:id (is guid the only one?)

                #todo try/except?
                util.set_value(d, key, value)
        
        yield d
        
        if item == True: #i.e. this is being fed forever, i.e. not in a loop, so we just yield our item once
            break
        