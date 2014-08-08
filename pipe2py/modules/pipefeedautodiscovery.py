# pipefeedautodiscovery.py
#

import autorss
from pipe2py import util

def pipe_feedautodiscovery(context, _INPUT, conf, **kwargs):
    """This source search for feed links in a page
    
    Keyword arguments:
    context -- pipeline context       
    _INPUT -- not used
    conf:
        URL -- url
    
    Yields (_OUTPUT):
    feed entries
    """
    urls = conf['URL']
    if not isinstance(urls, list):
        urls = [urls]
    
    for item in _INPUT:
        for item_url in urls:
            url = util.get_value(item_url, item, **kwargs)

            if not '://' in url:
                url = 'http://' + url
            
            if context.verbose:
                print "pipe_feedautodiscovery loading:", url
            d = autorss.getRSSLink(url.encode('utf-8'))
            
            for entry in d:
                yield {'link':entry}
                #todo add rel, type, title
    
        if item == True: #i.e. this is being fed forever, i.e. not in a loop, so we just yield our item once
            break
