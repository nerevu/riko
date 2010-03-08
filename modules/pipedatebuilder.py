# pipedatebuilder.py
#

def pipe_datebuilder(_INPUT, conf, **kwargs):
    """This source builds a date and yields it forever.
    
    Keyword arguments:
    _INPUT -- not used
    conf:
        DATE -- date
    
    Yields (_OUTPUT):
    date
    """
    date = conf['DATE']['value']
    
    while True:
        yield date

