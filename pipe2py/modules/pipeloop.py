# -*- coding: utf-8 -*-
# vim: sw=4:ts=4:expandtab
"""
    pipe2py.modules.pipeloop
    ~~~~~~~~~~~~~~~~~~~~~~~~
    Provides methods for creating submodules from existing pipes

    http://pipes.yahoo.com/pipes/docs?doc=operators#Loop
"""

from pipe2py import util
from copy import copy
from pipe2py.lib.dotdict import DotDict


def _gen_results(submodule, mode, first=False):
    for i in submodule:
        yield i

        if first:
            break


def _gen_inputs(item, conf):
    # Pass any input parameters into the submodule
    for key in conf:
        yield (key, util.get_value(conf[key], item, func=unicode))


def pipe_loop(context, _INPUT, conf, embed=None, **kwargs):
    """This operator loops over the input performing the embedded submodule.

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

    Yields
    ------
    _OUTPUT : items
    """
    conf = DotDict(conf)
    mode = conf.get('mode')
    assign_to = conf.get('assign_to')
    assign_part = conf.get('assign_part')
    # TODO: what is this for??
    # emit_part = conf.get('emit_part')
    loop_with = conf.get('with')
    embed_conf = conf.get('embed')['conf']

    # Prepare the submodule to take parameters from the loop instead of from
    # the user
    embed_context = copy(context)
    embed_context.submodule = True

    for item in _INPUT:
        item = DotDict(item)
        inp = item.get(loop_with, **kwargs) if loop_with else item

        # prepare the submodule
        embed_context.inputs = dict(_gen_inputs(item, embed_conf))
        submodule = embed(embed_context, [inp], embed_conf)
        first = assign_part == 'first'
        results = _gen_results(submodule, mode, first)

        if not results:
            continue
        elif mode == 'EMIT':
            for i in results:
                yield i
        elif mode == 'assign':
            results = list(results)

            # this is a hack to make sure fetchpage works in an out of a
            # loop while not disturbing strconcat in a loop etc.
            # note: i suspect this needs to be more discerning and only happen
            # if the source can only ever deliver 1 result, e.g. strconcat vs.
            # fetchpage
            if len(results) == 1 and and len(results[0]) == 1:
                try:
                    results = results[0].values()[0]
                except AttributeError:
                    pass

            item.set(assign_to, results)
            yield item
        else:
            raise Exception(
                "Invalid mode: %s. (Expected 'assign' or 'EMIT')" % mode)
