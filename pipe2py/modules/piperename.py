# piperename.py
# vim: sw=4:ts=4:expandtab

from pipe2py import util
from pipe2py.lib.dotdict import DotDict


def pipe_rename(context=None, _INPUT=None, conf=None, **kwargs):
    """This operator renames or copies fields in the input source.

    Keyword arguments:
    context -- pipeline context
    _INPUT -- source generator
    kwargs -- other inputs, e.g. to feed terminals for rule values
    conf:
        RULE -- rules - each rule comprising (op, field, newval)

    Yields (_OUTPUT):
    source items after copying/renaming
    """
    rules = []
    conf = DotDict(conf)
    rule_defs = util.listize(conf['RULE'])

    for rule in rule_defs:
        rule = DotDict(rule)
        newval = util.get_value(rule['newval'], None, **kwargs) #todo use subkey?
        newfield = rule['field']
        #trick the get_value in the loop to mapping value onto an item key (rather than taking it literally, i.e. make it a LHS reference, not a RHS value)
        newfield['subkey'] = newfield['value']
        del newfield['value']

        rules.append((rule['op']['value'], newfield, newval))

    for item in _INPUT:
        item = DotDict(item)
        for rule in rules:
            try:
                value = util.get_value(rule[1], item, **kwargs) #forces an exception if any part is not found
                item.set(rule[2], value)
            except AttributeError:
                pass  #ignore if the source doesn't have our field (todo: issue a warning if debugging?)
            else:
                if rule[0] == 'rename':
                    try:
                        item.delete(rule[1]['subkey'])
                    except (KeyError, TypeError):  #TypeError catches pseudo subkeys, e.g. summary.content
                        pass  #ignore if the target doesn't have our field (todo: issue a warning if debugging?)

        yield item

