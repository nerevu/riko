# pipeloop.py
#

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

    Keyword arguments:
    context -- pipeline context
    _INPUT -- source generator
    kwargs -- other inputs, e.g. to feed terminals for rule values
    conf:
        mode -- how to affect output - either assign or EMIT
        assign_to -- if mode is assign, which field to assign to
            (new or existing)

        loop_with -- pass a particular field into the submodule rather than the
            whole item
    embed -- embedded submodule

    Yields (_OUTPUT):
    source items after passing through the submodule and adding/replacing values
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
            if len(results) == 1 and not hasattr(results[0], 'keys'):
                results = results[0]

            item.set(assign_to, results)
            yield item
        else:
            raise Exception(
                "Invalid mode: %s. (Expected 'assign' or 'EMIT')" % mode)
