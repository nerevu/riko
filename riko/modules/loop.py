# vim: sw=4:ts=4:expandtab
"""
Provides functions for creating submodules from existing pipes

    http://pipes.yahoo.com/pipes/docs?doc=operators#Loop

loop(
    source,
    embed=itembuilder,
    conf={
        "count": "all",
        "embed": {
            "assign": "loop:itembuilder",
            "emit": False,
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
)

Examples:
    basic usage::

        >>> from riko.modules.loop import pipe
        >>>
        >>> items = [{"content": "b"}, {"content": "a"}, {"content": "c"}]
        >>> next(pipe(items))
        {'content': 'b'}

Attributes:
    OPTS (dict): The default pipe options
    DEFAULTS (dict): The default parser options

"""

import pygogo as gogo

from riko import Objconf
from riko.types.general import Defaults, Opts, PipeTuples, Stream

from . import operator

OPTS: Opts = {"listize": False, "parse": False}
DEFAULTS = Defaults({})
logger = gogo.Gogo(__name__, monolog=True).logger


def parser(stream: Stream, objconf: Objconf, tuples: PipeTuples, **kwargs) -> Stream:
    """
    Parses the pipe content

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
def pipe(*args, **kwargs) -> Stream:
    """
    An operator that creates submodules from existing pipes.

    Args:
        items (Iter[dict]): The source.
        kwargs (dict): The keyword arguments passed to the wrapper

    Kwargs:
        embed: the submodule. processor modules, with the exception of *input can be
            sub-modules.

        conf (dict): The loop configuration. May contain
            "count":
            "field": <looped field name or blank>,
            "embed": {"conf": <module conf>}

    """
    return parser(*args, **kwargs)
