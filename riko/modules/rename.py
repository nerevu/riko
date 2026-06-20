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
from typing import cast

import pygogo as gogo
from meza.fntools import remove_keys

from riko import Objconf
from riko.bado.itertools import coop_reduce
from riko.dotdict import DotDict
from riko.types.general import Defaults, ItemArg, Opts
from riko.types.modules import RenameConfRule
from riko.types.values import ComplexMapping

from . import processor

OPTS: Opts = {"extract": "rule", "listize": True, "emit": True}
DEFAULTS: Defaults = {}
logger = gogo.Gogo(__name__, monolog=True).logger


def reducer(item: ComplexMapping, rule: RenameConfRule) -> DotDict:
    reduced = DotDict(
        item if rule.copy else cast(ComplexMapping, remove_keys(item, rule.field))
    )
    new_dict = {rule.newval: item.get(rule.field)} if rule.newval else {}
    reduced.update(new_dict)
    return reduced


async def async_parser(
    item: ItemArg, rules: Sequence[RenameConfRule], objconf: Objconf, **kwargs
) -> DotDict | ItemArg:
    """
    Asynchronously parses the pipe content

    Args:
        item (obj): The entry to process (a DotDict instance)
        rules (List[obj]): the parsed rules (Objectify instances).
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
        >>> async def run(reactor):
        ...     item = DotDict({'content': 'hello world'})
        ...     rule = {'field': 'content', 'newval': 'greeting'}
        ...     result = await async_parser(item, [Objectify(rule)], None, stream=item)
        ...     print(result)
        >>>
        >>> try:
        ...     react(run, _reactor=FakeReactor())
        ... except SystemExit:
        ...     pass
        ...
        {'greeting': 'hello world'}

    """
    if isinstance(item, Mapping):
        item = await coop_reduce(reducer, rules, item)
    else:
        msg = f"{item=} is a {type(item)=}, not a mapping, skipping processing."
        logger.warning(msg)

    return item


def parser(
    item: ItemArg, rules: Sequence[RenameConfRule], objconf: Objconf, **kwargs
) -> DotDict | ItemArg:
    """
    Parsers the pipe content

    Args:
        item (obj): The entry to process (a DotDict instance)
        rules (List[obj]): the parsed rules (Objectify instances).
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
        >>> parser(*args, stream=item)
        {'greeting': 'hello world'}

    """
    if isinstance(item, Mapping):
        item = reduce(reducer, rules, item)
    else:
        msg = f"{item=} is a {type(item)=}, not a mapping, skipping processing."
        logger.warning(msg)

    return item


@processor(DEFAULTS, isasync=True, **OPTS)
async def async_pipe(*args, **kwargs) -> DotDict | ItemArg:
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
        >>> async def run(reactor):
        ...     conf = {'rule': {'field': 'content', 'newval': 'greeting'}}
        ...     result = await async_pipe({'content': 'hello world'}, conf=conf)
        ...     print(next(result)['greeting'])
        >>>
        >>> try:
        ...     react(run, _reactor=FakeReactor())
        ... except SystemExit:
        ...     pass
        ...
        hello world

    """
    return await async_parser(*args, **kwargs)


@processor(DEFAULTS, **OPTS)
def pipe(*args, **kwargs) -> DotDict | ItemArg:
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
