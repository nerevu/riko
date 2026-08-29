# vim: sw=4:ts=4:expandtab
"""
Runs a submodule once per item.

A loop runs a processor or compiled sub-pipeline (``embed`` submodule)
once per source item, and folds its output back into the stream. All processors
except ``*input`` are loopable and may be embedded.

Examples:
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
    OPTS: Operator wrapper options.
    DEFAULTS: Default operator configuration.

"""

from logging import Logger
from typing import Any

import pygogo as gogo

from riko.types._dynamic_conf import DynamicConf
from riko.types._options import Defaults, Opts
from riko.types._streams import Stream
from riko.types._wrappers import PipeTuples

from . import operator

OPTS: Opts = {"listize": False, "parse": False}
DEFAULTS: Defaults = Defaults({})
logger: Logger = gogo.Gogo(__name__, monolog=True).logger


def parser(
    stream: Stream, objconf: DynamicConf, tuples: PipeTuples, **kwargs: object
) -> Stream:
    """
    Returns the source unchanged.

    The looping happens around this parser, not inside it: ``embed`` is run per
    item and its results folded back before the stream reaches a consumer.

    Args:
        stream: The source. Note: this shares the `tuples` iterator, so
            consuming it will consume `tuples` as well.

        objconf: The pipe configuration. Unused.

        tuples: Iterable of (item, objconf). `item` is an element in the source
            stream. Note: this shares the `stream` iterator, so consuming it
            will consume `stream` as well.

    Yields:
        Each source item, untouched.

    """
    yield from stream


@operator(DEFAULTS, isasync=True, **OPTS)
def async_pipe(*args: Any, **kwargs: object) -> Stream:
    """
    Asynchronously creates submodules from existing pipes.

    Runs the submodule once per parent lazily and sequentially — parent order
    is preserved, the source advances only as the consumer pulls, and
    ``count="first"`` stops after the first result.

    Args:
        items (Items): The source stream.
        context (Context): the execution context

    Kwargs:
        embed (callable): The submodule to run once per item. Any loopable
            processor (everything except ``*input``) or a compiled sub-pipeline.
            Required.

        conf (dict): The **submodule's** configuration, not this pipe's.

        field (str): Source field fed to the submodule (default: None).

        count (str): How many submodule results to keep per source item, either
            "all" or "first" (default: "all").

        assign (str): Subkey each kept result folds into. Ignored when ``emit``
            is True (default: "loop").

        emit (bool): Whether to replace each source item with the submodule
            output rather than fold it under ``assign`` (default: True for a
            normal item stream).

    Yields:
        - the submodule output per item when ``emit`` is True (default)
        - merged ``{Item, <assign>: <result>}`` once per kept result when
          ``emit`` is False

    Notes:
        A submodule that yields one value per item (``rename``, ``strconcat``,
        ``urlbuilder``, ``regex``) suits ``emit=True``, which replaces the item
        and makes ``count`` irrelevant. One that yields many (``tokenizer``,
        ``fetchdata``) suits ``emit=False`` with ``assign``.

        A missing ``embed`` logs a warning and passes the source through
        unchanged.

    """
    return parser(*args, **kwargs)


@operator(DEFAULTS, **OPTS)
def pipe(*args: Any, **kwargs: object) -> Stream:
    """
    Creates submodules from existing pipes.

    Runs the submodule once per source item and folds its output back into the
    stream.

    Args:
        items (Items): The source stream.
        context (Context): the execution context

    Kwargs:
        embed (callable): The submodule to run once per item. Any loopable
            processor (everything except ``*input``) or a compiled sub-pipeline.
            Required.

        conf (dict): The **submodule's** configuration, not this pipe's.

        field (str): Source field fed to the submodule (default: None).

        count (str): How many submodule results to keep per source item, either
            "all" or "first" (default: "all").

        assign (str): Subkey each kept result folds into. Ignored when ``emit``
            is True (default: "loop").

        emit (bool): Whether to replace each source item with the submodule
            output rather than fold it under ``assign`` (default: True for a
            normal item stream).

    Yields:
        - the submodule output per item when ``emit`` is True (default)
        - merged ``{Item, <assign>: <result>}`` once per kept result when
          ``emit`` is False

    Notes:
        A submodule that yields one value per item (``rename``, ``strconcat``,
        ``urlbuilder``, ``regex``) suits ``emit=True``, which replaces the item
        and makes ``count`` irrelevant. One that yields many (``tokenizer``,
        ``fetchdata``) suits ``emit=False`` with ``assign``.

        A missing ``embed`` logs a warning and passes the source through
        unchanged.

    """
    return parser(*args, **kwargs)
