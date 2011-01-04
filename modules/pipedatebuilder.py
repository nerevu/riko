# pipedatebuilder.py
#

from pipe2py import util

def pipe_datebuilder(context, _INPUT, conf, **kwargs):
    """This source builds a date and yields it forever.
    
    Keyword arguments:
    context -- pipeline context
    _INPUT -- XXX
    conf:
        DATE -- date
    
    Yields (_OUTPUT):
    date
    """
    for item in _INPUT:
        date = util.get_value(conf['DATE'], item, **kwargs)

        yield date

        if item == True: #i.e. this is being fed forever, i.e. not in a loop, so we just yield our item once
            break
