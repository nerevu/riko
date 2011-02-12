# pipestringtokenizer.py
#

from pipe2py import util

def pipe_stringtokenizer(context, _INPUT, conf, **kwargs):
    """Splits a string into tokens delimited by separators.
    
    Keyword arguments:
    context -- pipeline context
    _INPUT -- source generator
    conf:
        to-str -- separator string
    
    Yields (_OUTPUT):
    tokens of the input string
    """
    delim = util.get_value(conf['to-str'], None, **kwargs)

    for item in _INPUT:
        if item is not None:
            for chunk in item.split(delim):
                yield {'content':chunk}

        if item == True: #i.e. this is being fed forever, i.e. not in a loop, so we just yield our item once
            break        
