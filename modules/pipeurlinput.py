# pipeurlinput.py
#

def pipe_urlinput(context, _INPUT, conf, **kwargs):
    """This source prompts the user for a url and yields it forever.
    
    Keyword arguments:
    context -- pipeline context
    _INPUT -- not used
    conf:
        default -- default
        prompt -- prompt
    
    Yields (_OUTPUT):
    url
    """
    default = conf['default']['value']   
    prompt = conf['prompt']['value']
    
    if context.test:
        value = ""  #we skip user interaction during tests
    else:
        value = raw_input(prompt + (" (default=%s) " % default))
    if value == "":
        value = default
        
    while True:
        yield value

