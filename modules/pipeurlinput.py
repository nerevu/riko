# pipeurlinput.py
#

def pipe_urlinput(_INPUT, conf, verbose=False, **kwargs):
    """This source prompts the user for a url and yields it forever.
    
    Keyword arguments:
    _INPUT -- not used
    conf:
        default -- default
        prompt -- prompt
    
    Yields (_OUTPUT):
    url
    """
    default = conf['default']['value']   
    prompt = conf['prompt']['value']
    
    value = raw_input(prompt + (" (default=%s) " % default))
    if value == "":
        value = default
        
    while True:
        yield value

