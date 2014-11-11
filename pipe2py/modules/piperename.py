# piperename.py
# vim: sw=4:ts=4:expandtab

from pipe2py import util
from pipe2py.lib.dotdict import DotDict


def _convert_item(rules, item, **kwargs):
    for rule in rules:
        field, op, newfield = rule

        try:
            # forces an exception if any part is not found
            item.set(newfield, item.get(field, **kwargs))
        except AttributeError:
            # ignore if the source doesn't have our field
            # todo: issue a warning if debugging?
            pass

        if op == 'rename':
            try:
                item.delete(field)
            # TypeError catches pseudo subkeys, e.g. summary.content
            except (KeyError, TypeError):
                # ignore if the target doesn't have our field
                # todo: issue a warning if debugging?
                pass

    return item


def pipe_rename(context=None, _INPUT=None, conf=None, **kwargs):
    """This operator renames or copies fields in the input source.

    context : pipe2py.Context object
    _INPUT : source generator of dicts
    conf : dict
        {
            'RULE': [
                {
                    'op': {'value': 'rename or copy'},
                    'field': {'value': 'old field'},
                    'newval': {'value': 'new field'}
                }
            ]
        }

    kwargs : other inputs, e.g., to feed terminals for rule values

    Yields
    ------
    _OUTPUT : source pipe after copying/renaming

    """
    conf = DotDict(conf)
    fields = ['field', 'op', 'newval']
    rule_defs = util.listize(conf['RULE'])
    rule_defs = [DotDict(rule_def) for rule_def in rule_defs]

    # use list bc iterator gets used up if there are no matching feeds
    rules = list(util.gen_rules(rule_defs, fields, **kwargs))

    for item in _INPUT:
        yield _convert_item(rules, DotDict(item), **kwargs)
