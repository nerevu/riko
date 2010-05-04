# pipetextinput.py
#

def pipe_textinput(context, _INPUT, conf, **kwargs):
    """This source prompts the user for some text and yields it forever.
    
    Keyword arguments:
    context -- pipeline context
    _INPUT -- not used
    conf:
        default -- default
        prompt -- prompt

    Yields (_OUTPUT):
    text
    """
    default = conf['default']['value']   
    prompt = conf['prompt']['value']
    
    value = raw_input(prompt + (" (default=%s) " % default))
    if value == "":
        value = default
        
    while True:
        yield value

