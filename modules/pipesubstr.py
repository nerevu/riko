# pipesubstr.py
#

from pipe2py import util

def pipe_substr(context, _INPUT, conf, **kwargs):
    """Returns a substring.
    
    Keyword arguments:
    context -- pipeline context
    _INPUT -- source generator
    conf:
        from -- starting character
        length -- number of characters to return
    
    Yields (_OUTPUT):
    portion of source string
    """
    sfrom = int(util.get_value(conf['from'], None, **kwargs))
    length = int(util.get_value(conf['length'], None, **kwargs))

    for item in _INPUT:
        yield item[sfrom:sfrom+length]

        if item == True: #i.e. this is being fed forever, i.e. not in a loop, so we just yield our item once
            break        
