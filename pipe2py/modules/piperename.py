# piperename.py
# vim: sw=4:ts=4:expandtab

from pipe2py import util
from pipe2py.lib.dotdict import DotDict


def _gen_rules(rule_defs, **kwargs):
    rule_defs = util.listize(rule_defs)

    # todo: use subkey?
    for rule_def in rule_defs:
        rule_def = DotDict(rule_def)
        op = rule_def.get('op', **kwargs)
        newfield = {'subkey': rule_def.get('field')}
        newval = rule_def.get('newval', **kwargs)
        yield (op, newfield, newval)


def _convert_item(rules, item, **kwargs):
    for rule in rules:
        value = util.get_value(rule[1], item, **kwargs)

        try:
            # forces an exception if any part is not found
            item.set(rule[2], value)
        except AttributeError:
            # ignore if the source doesn't have our field
            # todo: issue a warning if debugging?
            pass

        if rule[0] == 'rename':
            try:
                item.delete(rule[1]['subkey'])
            # TypeError catches pseudo subkeys, e.g. summary.content
            except (KeyError, TypeError):
                # ignore if the target doesn't have our field
                # todo: issue a warning if debugging?
                pass

    return item


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
    conf = DotDict(conf)
    rules = list(_gen_rules(conf['RULE'], **kwargs))

    for item in _INPUT:
        yield _convert_item(rules, DotDict(item), **kwargs)
