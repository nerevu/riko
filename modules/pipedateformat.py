# pipedateformat.py
#

import time

from pipe2py import util

def pipe_dateformat(context, _INPUT, conf, **kwargs):
    """This source formats a date.
    
    Keyword arguments:
    context -- pipeline context
    _INPUT -- source generator
    conf:
        format -- date format
    
    Yields (_OUTPUT):
    formatted date
    """
    date_format = util.get_value(conf['format'], None, **kwargs)

    for item in _INPUT:
        s = time.strftime(date_format, item)   #todo check all PHP formats are covered by Python
        #todo silent error handling? e.g. if item is not a date
        
        yield s
