# pipetextinput.py
#

def pipe_textinput(_INPUT, conf, verbose=False, **kwargs):
    """This source prompts the user for some text and yields it forever.
    
    Keyword arguments:
    _INPUT -- not used
    conf:
        default -- default
        prompt -- prompt
    
    Yields (_OUTPUT):
    date
    """
    default = conf['default']['value']   
    prompt = conf['prompt']['value']
    
    value = raw_input(prompt + (" (default=%s) " % default))
    if value == "":
        value = default
        
    while True:
        yield value

