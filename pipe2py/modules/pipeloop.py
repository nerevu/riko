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
    submodule = embed(context, iter([item]), conf, **kwargs)
    return submodule


def parse_result(submodule, item, **kwargs):
    _pass = utils.get_pass(item, kwargs.get('test'))

    if _pass:
        result = item
    else:
        assign_to = kwargs.get('assign_to')
        emit = kwargs.get('emit')
        first = kwargs.get('first')
        first_result = submodule.next()
        is_item = hasattr(first_result, 'keys')

    if not _pass and first and is_item:
        all_results = iter([first_result])
    elif not _pass and is_item:
        # submodule delivers one or more results, e.g. fetchpage, tokenizer so
        # grab the rest
        all_results = chain([first_result], submodule)
    elif not _pass:
        # submodule delivers one result (text, number...), e.g. strconcat
        all_results = first_result

    if not _pass and emit:
        result = all_results if is_item else iter([all_results])
    elif not _pass:
        assign = list(all_results) if is_item else all_results
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
    splits = utils.broadcast(inputs, get_submodule, utils.passthrough)
    gathered = utils.gather(splits, partial(parse_result, **pkwargs))

    if emit:
        _OUTPUT = utils.multiplex(gathered)
    else:
        _OUTPUT = gathered

    return _OUTPUT
