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

from riko.bado.itertools import coop_reduce
from riko.dotdict import DotDict
from riko.types.configs import RenameObjconf
from riko.types.general import Defaults, Item, Opts
from riko.types.modules import RenameConfRule

from . import processor

OPTS: Opts = {"extract": "rule", "listize": True, "emit": True}
DEFAULTS: Defaults = {}
logger = gogo.Gogo(__name__, monolog=True).logger


def reducer(item: Mapping, rule: RenameConfRule) -> DotDict:
    reduced = DotDict(item if rule.copy else remove_keys(item, rule.field))
    new_dict = {rule.newval: item.get(rule.field)} if rule.newval else {}
    reduced.update(new_dict)
    return reduced


async def async_parser(
    item: Item, rules: Sequence[RenameConfRule], objconf: RenameObjconf, **kwargs
) -> DotDict | Item:
    """
    Asynchronously parses the pipe content

    Args:
        item (obj): The entry to process (a DotDict instance)
        rules (List[obj]): the parsed rules (Objectify instances).
        kwargs (dict): Keyword arguments

    Kwargs:
        stream (dict): The original item

    Returns:
        Awaitable: item

    Examples:
        >>> from riko.bado import run
        >>> from riko.dotdict import DotDict
        >>> from meza.fntools import Objectify
        >>>
        >>> async def main():
        ...     item = DotDict({'content': 'hello world'})
        ...     rule = {'field': 'content', 'newval': 'greeting'}
        ...     result = await async_parser(item, [Objectify(rule)], None, stream=item)
        ...     print(result)
        >>>
        >>> run(main)
        {'greeting': 'hello world'}

    """
    return await coop_reduce(reducer, rules, item)


def parser(
    item: Item, rules: Sequence[RenameConfRule], objconf: RenameObjconf, **kwargs
) -> DotDict | Item:
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
    return reduce(reducer, rules, item)


@processor(DEFAULTS, isasync=True, **OPTS)
async def async_pipe(*args, **kwargs) -> DotDict | Item:
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
       Awaitable: item with renamed content

    Examples:
        >>> from riko.bado import run
        >>>
        >>> async def main():
        ...     conf = {'rule': {'field': 'content', 'newval': 'greeting'}}
        ...     result = await async_pipe({'content': 'hello world'}, conf=conf)
        ...     print(next(result)['greeting'])
        >>>
        >>> run(main)
        hello world

    """
    return await async_parser(*args, **kwargs)


@processor(DEFAULTS, **OPTS)
def pipe(*args, **kwargs) -> DotDict | Item:
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
