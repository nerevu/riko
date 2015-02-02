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
from itertools import chain, imap, starmap
from twisted.internet.defer import inlineCallbacks, returnValue
from . import get_splits, asyncGetSplits
from pipe2py.lib import utils
from pipe2py.lib.utils import combine_dicts as cdicts
from pipe2py.lib.dotdict import DotDict
from pipe2py.twisted.utils import asyncStarMap, asyncNone

opts = {'ftype': 'pass', 'listize': False, 'dictize': True}


# Common functions
def get_cust_func(context, conf, embed, parse_func, **kwargs):
    # Prepare the submodule to take parameters from the loop instead of from
    # the user
    embed_context = copy(context)
    embed_context.submodule = True
    kwargs.update({'context': embed_context, 'with': conf.get('with')})
    return partial(parse_func, embed=embed, **kwargs)


def get_inputs(item, conf):
    # Pass any input parameters into the submodule
    func = partial(utils.get_value, item=item, func=unicode)
    return {key: func(conf[key]) for key in conf}


def parse_result(submodule, item, _pass, **kwargs):
    if _pass:
        result = item
    else:
        assign_to = kwargs.get('assign_to')
        emit = kwargs.get('emit')
        first = kwargs.get('first')
        first_result = submodule.next()
        is_item = hasattr(first_result, 'keys')
        isnt_item = not is_item

    if not (_pass or first) and is_item:
        # submodule delivers one or more results, e.g. fetchpage, tokenizer so
        # grab the rest
        all_results = chain([first_result], submodule)
    elif not _pass:
        # submodule delivers one result (text, number...), e.g. strconcat
        all_results = first_result

    if not _pass and emit:
        result = iter([all_results]) if (first or isnt_item) else all_results
    elif not _pass:
        assign = all_results if (first or isnt_item) else list(all_results)
        item.set(assign_to, assign)
        result = item

    return result


def get_pkwargs(conf):
    emit = conf.get('mode') == 'EMIT'
    first_part = 'emit_part' if emit else 'assign_part'
    pkwargs = {
        'assign_to': conf.get('assign_to'),
        'pass_if': conf.get('pass_if'),
        'emit': emit,
        'first': conf.get(first_part) == 'first'
    }
    return pkwargs


# Async functions
@inlineCallbacks
def asyncParseEmbed(conf, item=None, embed=None, **kwargs):
    context = kwargs.pop('context')
    context.inputs = get_inputs(item, conf)  # prepare the submodule
    submodule = yield embed(context, iter([item]), conf, **kwargs)
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
    conf = DotDict(conf)
    pkwargs = cdicts(get_pkwargs(conf), kwargs)
    embed_conf = conf.get('embed').get('conf', {})
    cust_func = get_cust_func(context, conf, embed, asyncParseEmbed, **kwargs)
    opts.update({'cust_func': cust_func})
    splits = yield asyncGetSplits(_INPUT, embed_conf, **cdicts(opts, kwargs))
    gathered = yield asyncStarMap(partial(asyncParseResult, **pkwargs), splits)
    _OUTPUT = utils.multiplex(gathered) if pkwargs['emit'] else gathered
    returnValue(_OUTPUT)


# Synchronous functions
def parse_embed(conf, item=None, embed=None, **kwargs):
    context = kwargs.pop('context')
    context.inputs = get_inputs(item, conf)  # prepare the submodule
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
    pkwargs = cdicts(get_pkwargs(conf), kwargs)
    embed_conf = conf.get('embed').get('conf', {})
    cust_func = get_cust_func(context, conf, embed, parse_embed, **kwargs)
    opts.update({'cust_func': cust_func})
    splits = get_splits(_INPUT, embed_conf, **cdicts(opts, kwargs))
    gathered = starmap(partial(parse_result, **pkwargs), splits)
    _OUTPUT = utils.multiplex(gathered) if pkwargs['emit'] else gathered
    return _OUTPUT
