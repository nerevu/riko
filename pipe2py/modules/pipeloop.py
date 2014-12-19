# -*- coding: utf-8 -*-
# vim: sw=4:ts=4:expandtab
"""
    pipe2py.modules.pipeloop
    ~~~~~~~~~~~~~~~~~~~~~~~~
    Provides methods for creating submodules from existing pipes

    http://pipes.yahoo.com/pipes/docs?doc=operators#Loop
"""

from copy import copy
from functools import partial
from itertools import chain, imap
from pipe2py.lib import utils
from pipe2py.lib.dotdict import DotDict


def _gen_inputs(item, conf):
    # Pass any input parameters into the submodule
    for key in conf.iterkeys():
        yield (key, utils.get_value(conf[key], item, func=unicode))


def parse(item, conf, embed, **kwargs):
    context = kwargs.pop('context')
    context.inputs = dict(_gen_inputs(item, conf))  # prepare the submodule
    submodule = embed(context, [item], conf, **kwargs)
    return submodule


def parse_result(submodule, item, **kwargs):
    assign_to = kwargs.get('assign_to')
    test = kwargs.get('test')
    emit = kwargs.get('emit')
    first = kwargs.get('first')

    if utils.get_pass(item, test):
        r = item.get(assign_to)
    else:
        r = submodule.next()

    if not first and hasattr(r, 'keys'):
        # submodule can deliver 1 or more results,
        # e.g. stringtokenizer
        assign = list(chain([r], submodule))
    else:
        # submodule only delivers 1 result, e.g. strconcat
        # or user selected 'first'
        assign = r

    if emit:
        result = assign
    else:
        item.set(assign_to, assign)
        result = item

    return result


def pipe_loop(context=None, _INPUT=None, conf=None, embed=None, **kwargs):
    """An operator that loops over the input and performs the embedded
    submodule. Not loopable.

    Parameters
    ----------
    context : pipe2py.Context object
    _INPUT : pipe2py.modules pipe like object (iterable of items)
    embed : the submodule, i.e., pipe_*(context, _INPUT, conf)
        Most modules, with the exception of User inputs and Operators can be
        sub-modules.

    conf : {
        'assign_part': {'value': <all or first>},
        'assign_to': {'value': <assigned field name>},
        'emit_part': {'value': <all or first>},
        'mode': {'value': <assign or EMIT>},
        'with': {'value': <looped field name or blank>},
        'embed': {'value': {'conf': <module conf>}}
    }

    Returns
    -------
    _OUTPUT : generator of items
    """
    conf = DotDict(conf)
    test = kwargs.get('pass_if')
    emit = conf.get('mode') == 'EMIT'
    assign_to = conf.get('assign_to')
    first_part = 'emit_part' if emit else 'assign_part'
    first = conf.get(first_part) == 'first'

    # Prepare the submodule to take parameters from the loop instead of from
    # the user
    embed_context = copy(context)
    embed_context.submodule = True
    embed_conf = conf.get('embed').get('conf', {})
    kwargs.update({'context': embed_context, 'with': conf.get('with')})
    get_submodule = lambda _input: parse(_input, embed_conf, embed, **kwargs)
    pkwargs = {
        'assign_to': assign_to, 'test': test, 'emit': emit, 'first': first}

    inputs = imap(DotDict, _INPUT)
    splits = utils.split_input(inputs, get_submodule, utils.passthrough)
    _OUTPUT = utils.get_output(splits, partial(parse_result, **pkwargs))
    return _OUTPUT
