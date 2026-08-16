# vim: sw=4:ts=4:expandtab
"""
Provides functions for creating submodules from existing pipes

    http://pipes.yahoo.com/pipes/docs?doc=operators#Loop

A ``loop`` runs a processor or sub-pipeline *submodule* (``embed``) once per
source item and folds the submodule's output back into the stream. Any loopable
processor (everything except ``*input``) or a compiled sub-pipeline may be
embedded. The loop is configured entirely with **top-level kwargs** (the compact
form):

``embed`` -- the submodule callable.
``conf``  -- the submodule's own configuration.
``field`` -- the source field fed to the submodule.
``count`` -- how many submodule results to keep per source item: ``"all"``
    (default) or ``"first"``.
``emit`` / ``assign`` -- how each kept result folds back onto the parent item:

* ``emit=True``                -- replace each source item with the submodule
  output.
* ``emit=False, assign="foo"`` -- store each result at ``item["foo"]`` (one
  preserved-parent copy per result).

Rule of thumb: if the submodule yields exactly **one** value per item (``rename``,
``strconcat``, ``urlbuilder``, ``regex``), ``emit=True`` replaces the item and
``count`` is irrelevant. If it yields **many** (``tokenizer``, ``fetchdata``) and
you want them folded into a subkey, use ``emit=False`` + ``assign`` (with
``count="first"`` to keep only the first).

Scenarios:
    1. Transform a field in place -- ``emit=True`` yields the submodule's
       transformed items (each source item is replaced)::

        >>> from riko.modules.loop import pipe
        >>> from riko.modules.regex import pipe as regex
        >>>
        >>> items = [{"title": "hello"}, {"title": "yellow"}]
        >>> rule = {
        ...     "field": {"type": "text", "value": "title"},
        ...     "match": {"type": "text", "value": "l"},
        ...     "replace": {"type": "text", "value": "L"},
        ... }
        >>> list(pipe(items, embed=regex, conf={"rule": [rule]}, emit=True))
        [{'title': 'heLLo'}, {'title': 'yeLLow'}]

    2. Enrich each item with the first of many submodule results --
       ``emit=False`` + ``assign`` + ``count="first"``. The submodule
       (``tokenizer``) yields several values; the loop keeps the first and stores
       it under the ``assign`` subkey::

        >>> from riko.modules.tokenizer import pipe as tokenizer
        >>>
        >>> item = {"title": "a b c"}
        >>> conf = {"delimiter": {"type": "text", "value": " "}}
        >>> list(pipe(
        ...     [item], embed=tokenizer, conf=conf, field="title",
        ...     count="first", assign="first", emit=False,
        ... ))
        [{'title': 'a b c', 'first': {'content': 'a'}}]

Attributes:
    OPTS (dict): The default pipe options
    DEFAULTS (dict): The default parser options

"""

from logging import Logger
from typing import Any

import pygogo as gogo

from riko.types.configs import DynamicConf
from riko.types.general import Defaults, Opts, PipeTuples, Stream

from . import operator

OPTS: Opts = {"listize": False, "parse": False}
DEFAULTS: Defaults = Defaults({})
logger: Logger = gogo.Gogo(__name__, monolog=True).logger


def parser(
    stream: Stream, objconf: DynamicConf, tuples: PipeTuples, **kwargs: object
) -> Stream:
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


@operator(DEFAULTS, isasync=True, **OPTS)
def async_pipe(*args: Any, **kwargs: object) -> Stream:
    """
    Async counterpart of ``pipe`` — creates submodules from existing pipes,
    running the embed once per parent *lazily and sequentially* (parent order
    preserved, source advanced only as the consumer pulls, ``count="first"``
    stopping after the first result) and applying the same per-parent
    ``count``/``emit``/``assign`` fold. See ``pipe`` for kwargs.
    """
    return parser(*args, **kwargs)


@operator(DEFAULTS, **OPTS)
def pipe(*args: Any, **kwargs: object) -> Stream:
    """
    An operator that creates submodules from existing pipes.

    Args:
        items (Iter[dict]): The source.
        kwargs (dict): The keyword arguments passed to the wrapper

    Kwargs:
        embed: the submodule. Any loopable processor (everything except
            ``*input``) or a compiled sub-pipeline can be a submodule.

        conf (dict): The submodule's own configuration.

        field (str): The source field fed to the submodule.

        count (str): How many submodule results to keep per source item —
            ``"all"`` (default) or ``"first"``.

        assign (str): Subkey to fold each kept result into (when ``emit`` is
            False).

        emit (bool): Fold mode. True replaces each source item with the submodule
            output; False stores each result under ``assign``. Default:
            ``is_mapping`` (emit when the output is a mapping, i.e. effectively
            True for a normal item stream).

    """
    return parser(*args, **kwargs)
