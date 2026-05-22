# -*- coding: utf-8 -*-
# vim: sw=4:ts=4:expandtab
"""
riko.modules.loop
~~~~~~~~~~~~~~~~~
Provides functions for creating submodules from existing pipes

    http://pipes.yahoo.com/pipes/docs?doc=operators#Loop

loop(
    context,
    sw_637,
    embed=pipe_sw_696,
    conf={
        "count": {"type": "text", "value": "all"},
        "assign": {"type": "text", "value": "loop:itembuilder"},
        "emit": {"type": "bool", "value": True},
        "embed": {
            "type": "module",
            "value": {
                "type": "itembuilder",
                "id": "sw-696",
                "conf": {
                    "attrs": [
                        {
                            "value": {"type": "text", "value": "NEWTITLE"},
                            "key": {"type": "text", "value": "newtitle"},
                        },
                        {
                            "value": {"type": "text", "subkey": "title"},
                            "key": {"type": "text", "value": "title"},
                        },
                    ]
                },
            },
        },
        "with": {"type": "text", "value": ""},
    },
)

Examples:
    basic usage::

        >>> from riko.modules.loop import pipe
        >>>
        >>> items = [{"content": "b"}, {"content": "a"}, {"content": "c"}]
        >>> next(pipe(items))
        True

Attributes:
    OPTS (dict): The default pipe options
    DEFAULTS (dict): The default parser options
"""
import pygogo as gogo

from copy import copy
from functools import partial
from itertools import chain, starmap

from . import get_broadcast_funcs, operator
from riko.bado import itertools as ait, coroutine, return_value
from riko.bado.itertools import async_starmap
from riko.bado.util import async_none
from riko.utils import def_itemgetter as itemgetter

OPTS = {"ftype": "with", "listize": False, "parse": False}
DEFAULTS = {}
logger = gogo.Gogo(__name__, monolog=True).logger


def parser(stream, objconf, tuples, **kwargs):
    """Parses the pipe content

    Args:
        stream (Iter[dict]): The source. Note: this shares the `tuples`
            iterator, so consuming it will consume `tuples` as well.

        objconf (obj): The pipe configuration (an Objectify instance)

        tuples (Iter[(dict, obj)]): Iterable of tuples of (item, objconf)
            `item` is an element in the source stream and `objconf` is the item
            configuration (an Objectify instance). Note: this shares the
            `stream` iterator, so consuming it will consume `stream` as well.

        kwargs (dict): Keyword arguments.

    Kwargs:
        conf (dict): The pipe configuration.
        embed : the submodule. processor modules, with the exception of *input can be
            sub-modules.

    Returns:
        List(dict): The output stream
    """
    yield from stream


@operator(DEFAULTS, **OPTS)
def pipe(*args, **kwargs):
    """An operator that eagerly sorts a stream according to a specified
    key. Note that this pipe is not lazy.

    Args:
        items (Iter[dict]): The source.
        kwargs (dict): The keyword arguments passed to the wrapper

    Kwargs:
        embed : the submodule. processor modules, with the exception of *input can be
            sub-modules.

        conf (dict): The pipe configuration. May contain
            "with": {"value": <looped field name or blank>},
            "embed": {"value": {"conf": <module conf>}}
    """
    return parser(*args, **kwargs)
