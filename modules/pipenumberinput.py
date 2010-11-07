# pipenumberinput.py
#

def pipe_numberinput(context, _INPUT, conf, **kwargs):
    """This source prompts the user for a number and yields it forever.
    
    Keyword arguments:
    context -- pipeline context
    _INPUT -- not used
    conf:
        default -- default
        prompt -- prompt

    Yields (_OUTPUT):
    text
    """
    name = conf['name']['value']
    default = conf['default']['value']
    prompt = conf['prompt']['value']
    debug = conf['debug']['value']
    
    if context.test:
        value = default  #we skip user interaction during tests  #Note: docs say debug is used, but doesn't seem to be
    elif context.console:
        value = raw_input(prompt + (" (default=%s) " % default))
        if value == "":
            value = default
    else:
        value = context.inputs.get(name, default)
        
    try:
        value = float(value)
    except:
        value = 0
    
    while True:
        yield value

