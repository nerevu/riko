"""Utility functions"""

import string

def pythonise(id):
    """Return a Python-friendly id"""
    if id:
        id = id.replace("-", "_").replace(":", "_")
        
        if id[0] in string.digits:
            id = "_" + id
        
        return id.encode('ascii')

def get_value(item, kwargs):
    """Return either a literal value or a value via a terminal"""
    if 'value' in item:
        return item['value']  #simple value
    elif 'terminal' in item:
        return kwargs[pythonise(item['terminal'])].next()

def yield_forever():
    """Yield True forever"""
    while True:
        yield True