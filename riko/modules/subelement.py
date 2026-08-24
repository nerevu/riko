# vim: sw=4:ts=4:expandtab
"""
Extracts sub-elements buried in an item's hierarchy.

``path`` names the element to pull out, and everything above it is discarded.
Feeding a item the path ``"stanzas.verses"`` yields each verse of each stanza
on its own. It drops the stanza and all other first level fields.

Examples:
    Basic usage::

        >>> from riko.modules.subelement import pipe
        >>>
        >>> sonnet = {
        ...     "author": "William Shakespeare",
        ...     "title": "Sonnet 21",
        ...     "stanzas": [
        ...         {"id": "st1", "verses": ["st1v1", "st1v2", "st1v3"]},
        ...         {"id": "st2", "verses": ["st2v1", "st2v2", "st2v3"]},
        ...     ],
        ... }
        >>>
        >>> next(pipe(sonnet, conf={"path": "stanzas.verses"}))
        {'content': 'st1v1'}

Attributes:
    OPTS: Processor wrapper options.
    DEFAULTS: Default processor configuration.

"""

from collections.abc import Sequence
from logging import Logger
from typing import Any

import pygogo as gogo

from riko._rssutils import gen_items
from riko.modules._prepare import require_conf
from riko.types.configs import SubelementObjconf
from riko.types.general import Defaults, Extraction, Item, Opts, Stream
from riko.types.values import RikoValue

from . import processor

OPTS: Opts = {"emit": True}
DEFAULTS: Defaults = {"token_key": "content"}
logger: Logger = gogo.Gogo(__name__, monolog=True).logger


def parser(
    item: Item, extraction: Extraction, objconf: SubelementObjconf, **kwargs: RikoValue
) -> Stream:
    """
    Extracts the element ``path`` names from ``item``.

    Args:
        item: The entry to process.
        extraction: The extracted conf value. Unused.
        objconf: The pipe configuration, containing `path` and `token_key`.

    Returns:
        The extracted flattened tokens. Or nothing when the path is absent.

    Raises:
        TypeError: If ``conf`` has no ``path`` key.

    Examples:
        >>> from riko.dotdict import DotDict
        >>> from meza.fntools import Objectify
        >>>
        >>> conf = {"path": "stanzas.verses", "token_key": "content"}
        >>> objconf = Objectify(conf)
        >>> stanza = {"verses": ["verse1", "verse2"]}
        >>>
        >>> next(parser(DotDict({"stanzas": [stanza]}), None, objconf))
        {'content': 'verse1'}
        >>> next(parser(DotDict({"stanzas": stanza}), None, objconf))
        {'content': 'verse1'}
        >>> sonnet = DotDict({"stanzas": {"verses": "verse1"}})
        >>> next(parser(sonnet, None, objconf))
        {'content': 'verse1'}

    """
    raw: str | Sequence[str] = require_conf(objconf, "path", "subelement")
    path = raw if isinstance(raw, str) else ".".join(raw)
    element = item.get(path, **kwargs)
    return gen_items(element, objconf.token_key or "")


@processor(DEFAULTS, isasync=True, **OPTS)
def async_pipe(*args: Any, **kwargs: RikoValue) -> Stream:
    """
    Asynchronously extracts sub-elements from an item.

    Both iterator and iterable sources are mapped over. See the FAQ's "How does a
    processor map over items?".

    Args:
        item (Item | Items): The entry, or stream of entries, to process.

        conf (dict): The pipe configuration.

            path (str | list[str]): Dotted path to the element to extract. A list is
                joined with dots. Required.

            token_key (str): Field each token is assigned to, or None to yield
                the raw text instead of a dict (default: "content").

        context (Context): the execution context

    Kwargs:
        assign (str): Field the tokens are nested under. Ignored when ``emit``
            is True (default: "subelement").

        emit (bool): Whether to emit each token directly rather than nest them.
            Overrides ``assign`` (default: True).

    Yields:
        - ``<token>`` when ``emit`` is True (default)
        - ``{<assign>: <token>}`` when ``emit`` is False and no item given
        - one merged ``{Item, <assign>: [<token>, ...]}`` when ``emit`` is False
          and item is given

    Raises:
        TypeError: If ``conf`` has no ``path`` key.

    Notes:
        Nested lists are flattened and ``None`` values are dropped. So tokens
        arrive as one flat stream. A path the item lacks yields nothing.

    Examples:
        >>> from riko import run
        >>>
        >>> async def main():
        ...     sonnet = {"stanzas": [{"verses": ["verse1", "verse2"]}]}
        ...     result = await async_pipe(sonnet, conf={"path": "stanzas.verses"})
        ...     print(next(result))
        >>>
        >>> run(main)
        {'content': 'verse1'}

    """
    return parser(*args, **kwargs)


@processor(DEFAULTS, **OPTS)
def pipe(*args: Any, **kwargs: RikoValue) -> Stream:
    """
    Extracts sub-elements from an item.

    Both iterator and iterable sources are mapped over. See the FAQ's "How does a
    processor map over items?".

    Args:
        item (Item | Items): The entry, or stream of entries, to process.

        conf (dict): The pipe configuration.

            path (str | list[str]): Dotted path to the element to extract. A list is
                joined with dots. Required.

            token_key (str): Field each token is assigned to, or None to yield
                the raw text instead of a dict (default: "content").

        context (Context): the execution context

    Kwargs:
        assign (str): Field the tokens are nested under. Ignored when ``emit``
            is True (default: "subelement").

        emit (bool): Whether to emit each token directly rather than nest them.
            Overrides ``assign`` (default: True).

    Yields:
        - ``<token>`` when ``emit`` is True (default)
        - ``{<assign>: <token>}`` when ``emit`` is False and no item given
        - one merged ``{Item, <assign>: [<token>, ...]}`` when ``emit`` is False
          and item is given

    Raises:
        TypeError: If ``conf`` has no ``path`` key.

    Notes:
        Nested lists are flattened and ``None`` values are dropped. So tokens
        arrive as one flat stream. A path the item lacks yields nothing.

    Examples:
        >>> sonnet = {
        ...     "author": "William Shakespeare",
        ...     "title": "Sonnet 21",
        ...     "stanzas": [
        ...         {"id": "st1", "verses": ["st1v1", "st1v2", "st1v3"]},
        ...         {"id": "st2", "verses": ["st2v1", "st2v2", "st2v3"]},
        ...         {"id": "st3", "verses": ["st3v1", "st3v2", "st3v3"]},
        ...     ],
        ... }
        >>>
        >>> conf = {"path": "stanzas.verses"}
        >>> verses = list(pipe(sonnet, conf=conf))
        >>> len(verses)
        9
        >>> verses[0], verses[8]
        ({'content': 'st1v1'}, {'content': 'st3v3'})
        >>> conf.update({"token_key": "verse"})
        >>> next(pipe(sonnet, conf=conf))
        {'verse': 'st1v1'}
        >>> conf.update({"token_key": None})
        >>> next(pipe(sonnet, conf=conf))
        'st1v1'

    """
    return parser(*args, **kwargs)
