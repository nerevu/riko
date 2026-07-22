# vim: sw=4:ts=4:expandtab
"""
Provides functions for creating submodules from existing pipes

    http://pipes.yahoo.com/pipes/docs?doc=operators#Loop

A ``loop`` runs a processor *submodule* (``embed``) once per source item and
folds the submodule's output back into the stream. Any loopable processor may
be embedded (i.e. everything except ``*input``). Two independent settings
control the fold; understanding them is the key to reading loops.

``count`` -- how many submodule results to keep per source item:

* ``"all"``   -- keep every result (default)
* ``"first"`` -- keep only the first result

``emit`` / ``assign`` -- where the submodule output goes. These exist at **two
distinct levels**, and confusing them is the most common source of loop bugs:

1. **Loop level** -- passed as ``loop(..., emit=, assign=)`` kwargs (like every
   other module). This controls how the loop folds submodule output into the
   *parent* item:

   * ``emit=True``            -- replace each source item with the submodule output
   * ``emit=False, assign="foo"`` -- store the submodule output at ``item["foo"]``

   The default is ``is_mapping`` -- emit when the submodule output is a mapping,
   which is effectively ``True`` for the usual stream of item dicts. Pass
   ``emit=False`` explicitly to fold into a subkey instead.

2. **Embed level** -- ``conf["embed"]["value"]["emit"]`` / ``["assign"]``. These
   are the *submodule's own* options, applied while the submodule runs, before
   the loop folds its result.

Rule of thumb: if the submodule yields exactly **one** value per item
(``rename``, ``strconcat``, ``urlbuilder``, ``regex``), embed-level ``assign`` is
enough and ``count`` is irrelevant. If the submodule yields **many** values
(``fetchdata``, ``tokenizer``) and you want a single result folded into a
subkey, use **loop-level** ``assign`` together with ``count="first"`` -- the
``count`` reduction happens as the loop folds, which only the loop level sees.

Canonical conf shape::

    loop(
        source,
        embed=itembuilder,
        assign="info",  # loop-level fold options are module-level kwargs
        emit=False,
        conf={
            "count": "all",
            "embed": {
                "type": "module",
                "value": {
                    "type": "itembuilder",
                    "id": "sw-1",
                    "assign": "loop:itembuilder",  # submodule (embed-level) opts
                    "emit": False,
                    "conf": {"attrs": [...]},       # submodule conf
                },
            },
        },
    )

Scenarios:
    1. Transform a field in place -- ``emit=True`` makes the loop yield the
       submodule's transformed items (each source item is replaced)::

        >>> from riko.modules.loop import pipe
        >>> from riko.modules.regex import pipe as regex
        >>>
        >>> items = [{"title": "hello"}, {"title": "yellow"}]
        >>> rule = {
        ...     "field": {"type": "text", "value": "title"},
        ...     "match": {"type": "text", "value": "l"},
        ...     "replace": {"type": "text", "value": "L"},
        ... }
        >>> conf = {
        ...     "embed": {
        ...         "type": "module",
        ...         "value": {
        ...             "type": "regex",
        ...             "id": "r",
        ...             "emit": {"type": "bool", "value": True},
        ...             "conf": {"rule": [rule]},
        ...         },
        ...     }
        ... }
        >>> list(pipe(items, embed=regex, conf=conf))
        [{'title': 'heLLo'}, {'title': 'yeLLow'}]

    2. Enrich each item with the first of many submodule results --
       ``emit=False`` + ``assign`` at the **loop level** with ``count="first"``.
       The submodule (``tokenizer``) yields several values; the loop keeps the
       first and stores it under the ``assign`` subkey::

        >>> from riko.modules.tokenizer import pipe as tokenizer
        >>>
        >>> value = {
        ...     "type": "tokenizer",
        ...     "id": "t",
        ...     "emit": {"type": "bool", "value": True},
        ...     "field": {"type": "text", "value": "title"},
        ...     "conf": {"delimiter": {"type": "text", "value": " "}},
        ... }
        >>> conf = {
        ...     "count": {"type": "text", "value": "first"},
        ...     "embed": {"type": "module", "value": value},
        ... }
        >>> item = {"title": "a b c"}
        >>> list(pipe([item], embed=tokenizer, conf=conf, assign="first", emit=False))
        [{'first': {'content': 'a'}}]

       Swapping ``count`` to ``"all"`` keeps every result instead (one output
       item per token). This is exactly the shape used by real pipelines that
       loop ``fetchdata`` to attach a lookup: ``assign="info"``, ``emit=False``,
       ``count="first"`` stores the first fetched record at ``item["info"]``.

Attributes:
    OPTS (dict): The default pipe options
    DEFAULTS (dict): The default parser options

"""

import pygogo as gogo

from riko.types.configs import LoopObjconf
from riko.types.general import Defaults, Opts, PipeTuples, Stream

from . import operator

OPTS: Opts = {"listize": False, "parse": False}
DEFAULTS = Defaults({})
logger = gogo.Gogo(__name__, monolog=True).logger


def parser(
    stream: Stream, objconf: LoopObjconf, tuples: PipeTuples, **kwargs
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


@operator(DEFAULTS, **OPTS)
def pipe(*args, **kwargs) -> Stream:
    """
    An operator that creates submodules from existing pipes.

    Args:
        items (Iter[dict]): The source.
        kwargs (dict): The keyword arguments passed to the wrapper

    Kwargs:
        embed: the submodule. Any loopable processor (everything except
            ``*input``) can be a submodule.

        assign (str): Loop-level subkey to fold the submodule output into (used
            when ``emit`` is False). See the module docstring for the loop-level
            vs embed-level distinction.

        emit (bool): Loop-level fold mode. True replaces each source item with
            the submodule output; False stores it under ``assign``. Default:
            ``is_mapping`` (emit when the output is a mapping, i.e. effectively
            True for a normal item stream).

        field (str): Loop-level source field to feed the submodule (a
            module-level kwarg, like every other module).

        conf (dict): The loop configuration. May contain:
            "count": "all" (keep every submodule result, default) or "first"
                (keep only the first).
            "embed": {"type": "module", "value": {"type", "id", "conf", and the
                submodule's own "assign"/"emit"/"field"}}.

    """
    return parser(*args, **kwargs)
