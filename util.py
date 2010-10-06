"""Utility functions"""

import string

def pythonise(id):
    """Return a Python-friendly id"""
    if id:
        id = id.replace("-", "_").replace(":", "_")
        
        if id[0] in string.digits:
            id = "_" + id
        
        return id.encode('ascii')

def xml_to_dict(element):
    """Convert xml into dict"""
    i = dict(element.items())
    if element.getchildren():
        if element.text and element.text.strip():
            i['content'] = element.text
        for child in element.getchildren():
            tag = child.tag.split('}', 1)[-1]
            i[tag] = xml_to_dict(child)
    else:
        if not i.keys():
            if element.text and element.text.strip():
                i = element.text
        else:
            if element.text and element.text.strip():
                i['content'] = element.text
            
    return i

    
def get_value(item, kwargs):
    """Return either a literal value or a value via a terminal"""
    if 'value' in item:
        return item['value']  #simple value
    elif 'terminal' in item:
        return kwargs[pythonise(item['terminal'])].next()
