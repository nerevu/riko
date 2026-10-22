# vim: sw=4:ts=4:expandtab
"""
Runs an embedded module once per input item.

The embedded result can replace the input item or be assigned back onto it.

Examples:

    Basic usage::

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

    Assigning the first embedded result::

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

    OPTS: Operator decoration options.
    DEFAULTS: Default operator configuration.

"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from riko.base._logging import get_logger
from riko.types._options import DecorationOptions, Defaults

from ._decorators import operator

if TYPE_CHECKING:
    from logging import Logger

    from riko.coercion._dynamic_conf import DynamicConf
    from riko.types._streams import Stream
    from riko.types._wrappers import PipeTuples

OPTS: DecorationOptions = {"listize": False, "parse": False}
DEFAULTS: Defaults = Defaults({})
logger: Logger = get_logger(__name__)


def parser(
    stream: Stream, objconf: DynamicConf, tuples: PipeTuples, **kwargs: object
) -> Stream:
    """
    Passes the source through unchanged.

    The looping happens around this parser, not inside it: ``embed`` is run per
    item and its results folded back before the stream reaches a consumer.

    Args:

        stream: The input stream. Note: this shares the `tuples` iterator, so
            consuming it will consume `tuples` as well.

        objconf: The module configuration. Unused.

        tuples: Iterable of (item, objconf). `item` is an element in the source
            stream. Note: this shares the `stream` iterator, so consuming it
            will consume `stream` as well.

    Yields:

        Each input item, untouched.

    """
    yield from stream


@operator(DEFAULTS, isasync=True, **OPTS)
def async_pipe(*args: Any, **kwargs: object) -> Stream:
    """
    Asynchronously runs an embedded module once per input item.

    Runs it once per parent lazily and sequentially while preserving parent order. The
    input stream advances only as the consumer pulls, and ``count="first"`` stops after
    the first result.

    Args:

        items (Items): The input stream.
        context (Context): the run environment

    Kwargs:

        embed (callable): The pipe to run once per item. Any loopable processor
            (everything except ``*input``) or a stored workflow's pipe, looked up by
            its ``pipe_<id>`` name.

        conf (dict): The **embedded module's** configuration, not loop's.

        field (str): Field fed to the embedded module (default: None).

        count (str): How many embedded-module results to keep per input item, either
            "all" or "first" (default: "all").

        assign (str): Field each kept result folds into. Ignored when ``emit`` is True
            (default: "loop").

        emit (bool): Whether to replace each input item with the embedded module's
            results rather than fold them under ``assign`` (default: True for a normal
            item stream).

    Yields:

        - the embedded module's results per item when ``emit`` is True (default)
        - merged ``{Item, <assign>: <result>}`` once per kept result when ``emit`` is
          False

    Notes:

        An embedded module that yields one value per item (``rename``, ``strconcat``,
        ``urlbuilder``, ``regex``) suits ``emit=True``, which replaces the item and
        makes ``count`` irrelevant. One that yields many (``tokenizer``, ``fetchdata``)
        suits ``emit=False`` with ``assign``.

        Without an ``embed``, the input stream passes through unchanged.

    """
    return parser(*args, **kwargs)


@operator(DEFAULTS, **OPTS)
def pipe(*args: Any, **kwargs: object) -> Stream:
    """
    Runs an embedded module once per input item.

    Its results replace each item or are folded back into it.

    Args:

        items (Items): The input stream.
        context (Context): the run environment

    Kwargs:

        embed (callable): The pipe to run once per item. Any loopable processor
            (everything except ``*input``) or a stored workflow's pipe, looked up by
            its ``pipe_<id>`` name.

        conf (dict): The **embedded module's** configuration, not loop's.

        field (str): Field fed to the embedded module (default: None).

        count (str): How many embedded-module results to keep per input item, either
            "all" or "first" (default: "all").

        assign (str): Field each kept result folds into. Ignored when ``emit`` is True
            (default: "loop").

        emit (bool): Whether to replace each input item with the embedded module's
            results rather than fold them under ``assign`` (default: True for a normal
            item stream).

    Yields:

        - the embedded module's results per item when ``emit`` is True (default)
        - merged ``{Item, <assign>: <result>}`` once per kept result when ``emit`` is
          False

    Notes:

        An embedded module that yields one value per item (``rename``, ``strconcat``,
        ``urlbuilder``, ``regex``) suits ``emit=True``, which replaces the item and
        makes ``count`` irrelevant. One that yields many (``tokenizer``, ``fetchdata``)
        suits ``emit=False`` with ``assign``.

        Without an ``embed``, the input stream passes through unchanged.

    """
    return parser(*args, **kwargs)
