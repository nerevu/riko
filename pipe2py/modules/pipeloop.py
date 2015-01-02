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
from twisted.internet.defer import inlineCallbacks, returnValue
from pipe2py.lib import utils
from pipe2py.lib.dotdict import DotDict
from pipe2py.twisted.utils import asyncGather, asyncNone


# Common functions
def get_splits(context, _INPUT, conf, embed, parse_func, **kwargs):
    inputs = imap(DotDict, _INPUT)
    test = kwargs.pop('pass_if', None)

    # Prepare the submodule to take parameters from the loop instead of from
    # the user
    embed_context = copy(context)
    embed_context.submodule = True
    embed_conf = conf.get('embed').get('conf', {})
    kwargs.update({'context': embed_context, 'with': conf.get('with')})
    get_submodule = lambda i: parse_func(i, embed_conf, embed, **kwargs)
    get_pass = partial(utils.get_pass, test=test)
    broadcast_funcs = [get_submodule, utils.passthrough, get_pass]
    return utils.broadcast(inputs, *broadcast_funcs)


def get_inputs(item, conf):
    # Pass any input parameters into the submodule
    func = partial(utils.get_value, item=item, func=unicode)
    return imap(lambda key: (key, func(conf[key])), conf.iterkeys())


def parse_result(submodule, item, _pass, **kwargs):
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


def get_pkwargs(conf, **kwargs):
    test = kwargs.get('pass_if')
    emit = conf.get('mode') == 'EMIT'
    assign_to = conf.get('assign_to')
    first_part = 'emit_part' if emit else 'assign_part'
    first = conf.get(first_part) == 'first'
    pkwargs = {'assign_to': assign_to, 'test': test, 'emit': emit}
    pkwargs.update({'first': first})
    return pkwargs


# Async functions
@inlineCallbacks
def asyncParseEmbed(item, conf, asyncEmbed, **kwargs):
    context = kwargs.pop('context')
    context.inputs = dict(get_inputs(item, conf))  # prepare the submodule
    submodule = yield asyncEmbed(context, [item], conf, **kwargs)
    returnValue(submodule)


@inlineCallbacks
def asyncParseResult(asyncSubmodule, item, _pass, **kwargs):
    submodule = yield asyncNone if _pass else asyncSubmodule
    result = parse_result(submodule, item, _pass, **kwargs)
    returnValue(result)


@inlineCallbacks
def asyncPipeLoop(context=None, _INPUT=None, conf=None, embed=None, **kwargs):
    """An operator that asynchronously loops over the input and performs the
    embedded submodule. Not loopable.

    Parameters
    ----------
    context : pipe2py.Context object
    _INPUT : asyncPipe like object (twisted Deferred iterable of items)
    embed : the submodule, i.e., asyncPipe*(context, _INPUT, conf)
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
    _OUTPUT : twisted.internet.defer.Deferred generator of items
    """
    _input = yield _INPUT
    conf = DotDict(conf)
    pkwargs = get_pkwargs(conf, **kwargs)
    splits = get_splits(context, _input, conf, embed, asyncParseEmbed, **kwargs)
    gathered = yield asyncGather(splits, partial(asyncParseResult, **pkwargs))
    _OUTPUT = utils.multiplex(gathered) if pkwargs['emit'] else gathered
    returnValue(_OUTPUT)


# Synchronous functions
def parse_embed(item, conf, embed, **kwargs):
    context = kwargs.pop('context')
    context.inputs = dict(get_inputs(item, conf))  # prepare the submodule
    submodule = embed(context, iter([item]), conf, **kwargs)
    return submodule


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
    pkwargs = get_pkwargs(conf, **kwargs)
    splits = get_splits(context, _INPUT, conf, embed, parse_embed, **kwargs)
    gathered = utils.gather(splits, partial(parse_result, **pkwargs))
    _OUTPUT = utils.multiplex(gathered) if pkwargs['emit'] else gathered
    return _OUTPUT

