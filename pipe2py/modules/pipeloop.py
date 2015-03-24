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
from itertools import chain, starmap
from twisted.internet.defer import inlineCallbacks, returnValue
from . import get_splits, asyncGetSplits, _get_broadcast_funcs as get_funcs
from pipe2py.lib import utils
from pipe2py.lib.utils import combine_dicts as cdicts
from pipe2py.twisted.utils import asyncStarMap, asyncNone

opts = {'ftype': 'pass', 'listize': False, 'parse': False, 'dictize': True}


# Common functions
def get_cust_func(context, conf, embed, parse_func, **kwargs):
    # Prepare the submodule to take parameters from the loop instead of from
    # the user
    embed_context = copy(context)
    embed_context.submodule = True
    copts = {'context': embed_context, 'conf': conf, 'embed': embed}
    pkwargs = cdicts(copts, kwargs)
    return partial(parse_func, **pkwargs)


def parse_result(conf, item, _pass, submodule):
    if _pass:
        result = iter([item])
    else:
        emit = conf.get('mode') == 'EMIT'
        first_part = 'emit_part' if emit else 'assign_part'
        assign_to = conf.get('assign_to')
        first = conf.get(first_part) == 'first'
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
        result = iter([item])

    return result


def parse_embed(item, context=None, conf=None, embed=None, **kwargs):
    parsed_conf = get_funcs(conf, **cdicts(opts, kwargs))[0](item)

    try:
        embedded = parsed_conf['embed'].get()
    except TypeError:
        embedded = parsed_conf['embed']

    embedded_conf = embedded.get('conf', {})
    pairs = [('pass_if', kwargs), ('setup_output', kwargs), ('pdictize', embedded)]
    true_pairs = ((x, y[x]) for x, y in pairs if x in y)
    ekwargs = dict(chain([('with', parsed_conf.get('with'))], true_pairs))
    context.inputs = get_funcs(embedded_conf, **ekwargs)[0](item)
    return embed(context, iter([item]), embedded_conf, **ekwargs)


# Async functions
@inlineCallbacks
def asyncParseResult(conf, item, _pass, asyncSubmodule):
    submodule = yield asyncNone if _pass else asyncSubmodule
    result = parse_result(conf, item, _pass, submodule)
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
    if kwargs.get('setup'):
        setup_output = yield kwargs['setup'](context, conf['embed']['conf'])
        kwargs.update({'setup_output': setup_output})

    cust_func = get_cust_func(context, conf, embed, parse_embed, **kwargs)
    opts.update({'cust_func': cust_func})
    splits = yield asyncGetSplits(_INPUT, conf, **cdicts(opts, kwargs))
    gathered = yield asyncStarMap(asyncParseResult, splits)
    _OUTPUT = utils.multiplex(gathered)
    returnValue(_OUTPUT)


# Synchronous functions
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
    cust_func = get_cust_func(context, conf, embed, parse_embed, **kwargs)
    opts.update({'cust_func': cust_func})
    splits = get_splits(_INPUT, conf, **cdicts(opts, kwargs))
    gathered = starmap(parse_result, splits)
    _OUTPUT = utils.multiplex(gathered)
    return _OUTPUT
