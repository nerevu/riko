# vim: sw=4:ts=4:expandtab
"""
Provides functions for creating a single-item data source

With the Item Builder module, you can create a single-item data source by
assigning values to one or more item attributes. The module lets you assign
a value to an attribute.

Item Builder's strength is its ability to restructure and rename multiple
elements in a stream. When Item Builder is fed an input stream, the assigned
values can be existing attributes of the stream. These attributes can be
reassigned or used to create entirely new attributes.

Examples:
    basic usage::

        >>> from riko.modules.itembuilder import pipe
        >>>
        >>> attrs = {'key': 'title', 'value': 'the title'}
        >>> next(pipe(conf={'attrs': attrs}))['title']
        'the title'

Attributes:
    OPTS (dict): The default pipe options
    DEFAULTS (dict): The default parser options

"""

from collections.abc import Sequence

import pygogo as gogo

from riko import Objconf
from riko.cast import BasicCastType
from riko.dotdict import DotDict
from riko.types.general import Defaults, Opts
from riko.types.modules import ParsedParam
from riko.types.values import RikoDict

from . import processor

OPTS: Opts = {"ftype": BasicCastType.NONE, "listize": True, "extract": "attrs"}
DEFAULTS: Defaults = {}
logger = gogo.Gogo(__name__, monolog=True).logger


def parser(
    _, extraction: Sequence[ParsedParam], objconf: Objconf, **kwargs
) -> RikoDict:
    """
    Parses the pipe content

    Args:
        _ (None): Ignored
        attrs (List[dict]): Attributes
        kwargs (dict): Keyword arguments

    Kwargs:
        stream (dict): The original item

    Returns:
        Iter(dict): The stream of items

    Examples:
        >>> from riko.dotdict import DotDict
        >>> attrs = [
        ...     {'key': 'title', 'value': 'the title'},
        ...     {'key': 'desc', 'value': 'the desc'}]
        >>> parser(None, map(DotDict, attrs), None)
        {'title': 'the title', 'desc': 'the desc'}

    """
    item = {a["key"]: a["value"] for a in extraction}
    return DotDict(item).asdict()


@processor(DEFAULTS, isasync=True, **OPTS)
def async_pipe(*args, **kwargs) -> RikoDict:
    """
    A source that asynchronously builds an item.

    Args:
        item (dict): The entry to process
        kwargs (dict): The keyword arguments passed to the wrapper

    Kwargs:
        conf (dict): The pipe configuration. Must contain the key 'attrs'.

            attrs (dict): can be either a dict or list of dicts. Must contain
                the keys 'key' and 'value'.

                key (str): the attribute name
                value (str): the attribute value

    Returns:
        dict: twisted.internet.defer.Deferred an iterator of items

    Examples:
        >>> from riko.bado import react
        >>> from riko.bado.mock import FakeReactor
        >>>
        >>> async def run(reactor):
        ...     attrs = [
        ...         {'key': 'title', 'value': 'the title'},
        ...         {'key': 'desc.content', 'value': 'the desc'}]
        ...
        ...     result = await async_pipe(conf={'attrs': attrs})
        ...     print(next(result)['title'])
        >>>
        >>> try:
        ...     react(run, _reactor=FakeReactor())
        ... except SystemExit:
        ...     pass
        ...
        the title

    """
    return parser(*args, **kwargs)


@processor(DEFAULTS, **OPTS)
def pipe(*args, **kwargs) -> RikoDict:
    """
    A source that builds an item.

    Args:
        item (dict): The entry to process
        kwargs (dict): The keyword arguments passed to the wrapper

    Kwargs:
        conf (dict): The pipe configuration. Must contain the key 'attrs'.

            attrs (dict): can be either a dict or list of dicts. Must contain
                the keys 'key' and 'value'.

                key (str): the attribute name
                value (str): the attribute value

    Yields:
        dict: an item

    Examples:
        >>> attrs = [
        ...     {'key': 'title', 'value': 'the title'},
        ...     {'key': 'desc.content', 'value': 'the desc'}]
        >>> next(pipe(conf={'attrs': attrs}))
        {'title': 'the title', 'desc': {'content': 'the desc'}}

    """
    return parser(*args, **kwargs)
