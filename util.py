"""Utility functions"""

import string
from operator import itemgetter

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

    
def get_value(_item, _loop_item=None, **kwargs):
    """Return either:
           a literal value 
           a value via a terminal (then kwargs must contain the terminals)
           a value via a subkey reference (then _loop_item must be passed)
       Note: subkey values use dot notation and we map onto nested dictionaries, e.g. 'a.content' -> ['a']['content']
    """
    if 'value' in _item:  #simple value
        return _item['value']
    elif 'terminal' in _item:  #value fed in from another module
        return kwargs[pythonise(_item['terminal'])].next()
    elif 'subkey' in _item:  #reference to current loop item
        return reduce(lambda i,k:i.get(k), _item['subkey'].split('.'), _loop_item) #raises an exception if any part is not found

def set_value(item, key, value):
    """Set a key's value in the item
       Note: keys use dot notation and we map onto nested dictionaries, e.g. 'a.content' -> ['a']['content']
    """
    reduce(lambda i,k:i.setdefault(k, {}), key.split('.')[:-1], item)[key.split('.')[-1]] = value

def del_value(item, key):
    """Remove a value (and its key) from the item
       Note: keys use dot notation and we map onto nested dictionaries, e.g. 'a.content' -> ['a']['content']
    """
    del reduce(lambda i,k:i.get(k), [item] + key.split('.')[:-1])[key.split('.')[-1]]
    
    
def multikeysort(items, columns):
    """Sorts a list of items by the columns
       
       (columns precedeed with a '-' will sort descending)
    """
    comparers = [ ((itemgetter(col[1:].strip()), -1) if col.startswith('-') else (itemgetter(col.strip()), 1)) for col in columns]  
    def comparer(left, right):
        for fn, mult in comparers:
            try:
                result = cmp(fn(left), fn(right))
            except KeyError:
                #todo perhaps care more if only one side has the missing key
                result = 0
            if result:
                return mult * result
        else:
            return 0
    return sorted(items, cmp=comparer)
