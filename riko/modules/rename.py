# vim: sw=4:ts=4:expandtab
"""
Provides functions for renaming, copying, and deleting elements of an item.

There are several cases when this is useful, for example when the input data is
not in RSS format (e.g., elements are not named title, link, description, etc.)
and you want to output it as RSS, or when the input data contains geographic
data but their element names aren't recognized by the Location Extractor
module.

You rename an element by creating a mapping between the original name and a new
element name. You delete an element by not supplying a new element name. You
copy an element by setting the `copy` field to True.

Examples:
    basic usage::

        >>> from riko.modules.rename import pipe
        >>>
        >>> conf = {'rule': {'field': 'content', 'newval': 'greeting'}}
        >>> item = {'content': 'hello world'}
        >>> next(pipe(item, conf=conf))
        {'greeting': 'hello world'}

Attributes:
    OPTS (dict): The default pipe options
    DEFAULTS (dict): The default parser options

"""

from collections.abc import Mapping, Sequence
from functools import reduce

import pygogo as gogo
from meza.fntools import remove_keys

from riko import Objconf
from riko.bado import coroutine, return_value
from riko.bado import itertools as ait
from riko.dotdict import DotDict
from riko.types.general import BasicMapping, ItemArg, ObjconfRule

from . import processor

OPTS = {"extract": "rule", "listize": True, "emit": True}
DEFAULTS = {}
logger = gogo.Gogo(__name__, monolog=True).logger


def reducer(item: BasicMapping | DotDict, rule: ObjconfRule) -> DotDict:
    new_dict = {rule.newval: item.get(rule.field)} if rule.newval else {}
    old_dict = item if rule.copy else remove_keys(item, rule.field)
    return DotDict({**old_dict, **new_dict})


@coroutine  # pyright: ignore[reportArgumentType]
def async_parser(
    item: ItemArg, rules: Sequence[ObjconfRule], objconf: Objconf, skip=False, **kwargs
):
    """
    Asynchronously parses the pipe content

    Args:
        item (obj): The entry to process (a DotDict instance)
        rules (List[obj]): the parsed rules (Objectify instances).
        skip (bool): Don't parse the content
        kwargs (dict): Keyword arguments

    Kwargs:
        stream (dict): The original item

    Returns:
        Deferred: twisted.internet.defer.Deferred item

    Examples:
        >>> from riko.bado import react
        >>> from riko.dotdict import DotDict
        >>> from riko.bado.mock import FakeReactor
        >>> from meza.fntools import Objectify
        >>>
        >>> def run(reactor):
        ...     callback = lambda x: print(x)
        ...     item = DotDict({'content': 'hello world'})
        ...     rule = {'field': 'content', 'newval': 'greeting'}
        ...     d = async_parser(item, [Objectify(rule)], None, stream=item)
        ...     return d.addCallbacks(callback, logger.error)
        >>>
        >>> try:
        ...     react(run, _reactor=FakeReactor())
        ... except SystemExit:
        ...     pass
        ...
        {'greeting': 'hello world'}

    """
    if skip:
        item = kwargs["stream"]
    elif isinstance(item, Mapping):
        item = yield ait.coop_reduce(reducer, rules, item)  # pyright: ignore[reportCallIssue]

    return_value(item)


def parser(
    item: ItemArg, rules: Sequence[ObjconfRule], objconf: Objconf, skip=False, **kwargs
) -> ItemArg:
    """
    Parsers the pipe content

    Args:
        item (obj): The entry to process (a DotDict instance)
        rules (List[obj]): the parsed rules (Objectify instances).
        skip (bool): Don't parse the content
        kwargs (dict): Keyword arguments

    Kwargs:
        stream (dict): The original item

    Returns:
        dict: The item

    Examples:
        >>> from riko.dotdict import DotDict
        >>> from meza.fntools import Objectify
        >>>
        >>> item = DotDict({'content': 'hello world'})
        >>> rule = {'field': 'content', 'newval': 'greeting'}
        >>> args = [item, [Objectify(rule)], None]
        >>> parser(*args, skip=False, stream=item)
        {'greeting': 'hello world'}

    """
    if skip:
        item = kwargs["stream"]
    elif isinstance(item, Mapping):
        item = reduce(reducer, rules, item)
    else:
        msg = f"{item=} is a {type(item)=}, not a mapping, skipping processing."
        logger.warning(msg)
        item = kwargs["stream"]

    return item


@processor(DEFAULTS, isasync=True, **OPTS)  # pyright: ignore[reportArgumentType]
def async_pipe(*args, **kwargs):
    """
    A processor module that asynchronously renames or copies fields in an
    item.

    Args:
        item (dict): The entry to process
        kwargs (dict): The keyword arguments passed to the wrapper

    Kwargs:
        conf (dict): The pipe configuration. Must contain the key 'rule'.

            rule (dict): can be either a dict or list of dicts. Must contain
                the key 'field'.

                field (str): The item attribute to rename
                newval (str): The new item attribute name (default: None). If
                    blank, the field will be deleted.

                copy (bool): Copy the item attribute instead of renaming it
                    (default: False)

    Returns:
       Deferred: twisted.internet.defer.Deferred item with renamed content

    Examples:
        >>> from riko.bado import react
        >>> from riko.bado.mock import FakeReactor
        >>>
        >>> def run(reactor):
        ...     callback = lambda x: print(next(x)['greeting'])
        ...     conf = {'rule': {'field': 'content', 'newval': 'greeting'}}
        ...     d = async_pipe({'content': 'hello world'}, conf=conf)
        ...     return d.addCallbacks(callback, logger.error)
        >>>
        >>> try:
        ...     react(run, _reactor=FakeReactor())
        ... except SystemExit:
        ...     pass
        ...
        hello world

    """
    return async_parser(*args, **kwargs)


@processor(DEFAULTS, **OPTS)
def pipe(*args, **kwargs):
    """
    A processor that renames or copies fields in an item.

    Args:
        item (dict): The entry to process
        kwargs (dict): The keyword arguments passed to the wrapper

    Kwargs:
        conf (dict): The pipe configuration. Must contain the key 'rule'.

            rule (dict): can be either a dict or list of dicts. Must contain
                the key 'field'. May contain the keys 'newval' or 'copy'.

                field (str): The item attribute to rename
                newval (str): The new item attribute name (default: None). If
                    blank, the field will be deleted.

                copy (bool): Copy the item attribute instead of renaming it
                    (default: False)

    Yields:
        dict: an item with renamed content

    Examples:
        >>> rule = {'field': 'content', 'newval': 'greeting'}
        >>> item = {'content': 'hello world'}
        >>> next(pipe(item, conf={'rule': rule}))
        {'greeting': 'hello world'}
        >>> conf = {'rule': {'field': 'content'}}
        >>> next(pipe({'content': 'hello world'}, conf=conf))
        {}
        >>> rule['copy'] = True
        >>> result = pipe({'content': 'hello world'}, conf={'rule': rule})
        >>> sorted(next(result))
        ['content', 'greeting']

    """
    return parser(*args, **kwargs)
