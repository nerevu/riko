# pipeurlinput.py
#

import urllib2

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
    name = conf['name']['value']
    default = conf['default']['value']   
    prompt = conf['prompt']['value']
    debug = conf['debug']['value']
    
    if context.submodule:
        value = context.inputs.get(name, default)
    elif context.test:
        value = default  #we skip user interaction during tests  #Note: docs say debug is used, but doesn't seem to be
    elif context.console:
        value = raw_input(prompt.encode('utf-8') + (" (default=%s) " % default.encode('utf-8')))
        if value == "":
            value = default
    else:
        value = context.inputs.get(name, default)
        
    #Ensure url is valid
    value = urllib2.quote(value, safe="%/:=&?~#+!$,;'@()*[]")
        
    while True:
        yield value

