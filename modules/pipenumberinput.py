# pipenumberinput.py
#

from pipe2py import util

def pipe_numberinput(context, _INPUT, conf, **kwargs):
    """This source prompts the user for a number and yields it forever.
    
    Keyword arguments:
    context -- pipeline context
    _INPUT -- not used
    conf:
        name -- input parameter name
        default -- default
        prompt -- prompt

    Yields (_OUTPUT):
    text
    """
    value = util.get_input(context, conf)
        
    try:
        value = float(value)
    except:
        value = 0
    
    while True:
        yield value

