# vim: sw=4:ts=4:expandtab
"""
Provides functions for sorting a stream by an item field.

Examples:
    basic usage::

        >>> from riko.modules.sort import pipe
        >>>
        >>> items = [{'content': 'b'}, {'content': 'a'}, {'content': 'c'}]
        >>> next(pipe(items))
        {'content': 'a'}

Attributes:
    OPTS (dict): The default pipe options
    DEFAULTS (dict): The default parser options

"""

from collections.abc import Sequence
from functools import reduce

import pygogo as gogo

from riko.bado.itertools import async_reduce
from riko.types.general import Defaults, Opts, PipeTuples, Stream
from riko.types.modules import SortConfRule
from riko.utils import def_itemgetter

from . import operator

OPTS: Opts = {"listize": True, "extract": "rule"}
DEFAULTS: Defaults = {"rule": SortConfRule(dir="asc", field="content")}
logger = gogo.Gogo(__name__, monolog=True).logger


def reducer(stream: Stream, rule: SortConfRule) -> Stream:
    reverse = rule.dir.lower() == "desc" if rule.dir else False
    keyfunc = def_itemgetter(rule.field, _type=rule.type)
    return iter(sorted(stream, key=keyfunc, reverse=reverse))


async def async_parser(
    stream: Stream, rules: Sequence[SortConfRule], tuples: PipeTuples, **kwargs
) -> Stream:
    """
    Asynchronously parses the pipe content

    Args:
        stream (Iter[dict]): The source. Note: this shares the `tuples`
            iterator, so consuming it will consume `tuples` as well.

        rules (List[obj]): the item independent rules (Objectify instances).

        tuples (Iter[(dict, obj)]): Iterable of tuples of (item, objconf)
            `item` is an element in the source stream and `objconf` is the item
            configuration (an Objectify instance). Note: this shares the
            `stream` iterator, so consuming it will consume `stream` as well.

        kwargs (dict): Keyword arguments.

    Kwargs:
        conf (dict): The pipe configuration.

    Returns:
        List(dict): Deferred output stream

    Examples:
        >>> from itertools import repeat
        >>> from riko.bado import run, _issync
        >>> from meza.fntools import Objectify
        >>>
        >>> async def main():
        ...     kwargs = {'field': 'content', 'dir': 'desc'}
        ...     rule = Objectify(kwargs)
        ...     stream = ({'content': result} for result in range(5))
        ...     tuples = zip(stream, repeat(rule))
        ...     result = await async_parser(stream, [rule], tuples, **kwargs)
        ...     print(next(result))
        >>>
        >>> if _issync:
        ...     {'content': 4}
        ... else:
        ...     run(main)
        {'content': 4}

    """
    return await async_reduce(reducer, list(reversed(rules)), stream)


def parser(
    stream: Stream, rules: Sequence[SortConfRule], tuples: PipeTuples, **kwargs
) -> Stream:
    """
    Parses the pipe content

    Args:
        stream (Iter[dict]): The source. Note: this shares the `tuples`
            iterator, so consuming it will consume `tuples` as well.

        rules (List[obj]): the item independent rules (Objectify instances).

        tuples (Iter[(dict, obj)]): Iterable of tuples of (item, objconf)
            `item` is an element in the source stream and `objconf` is the item
            configuration (an Objectify instance). Note: this shares the
            `stream` iterator, so consuming it will consume `stream` as well.

        kwargs (dict): Keyword arguments.

    Kwargs:
        conf (dict): The pipe configuration.

    Returns:
        List(dict): The output stream

    Examples:
        >>> from meza.fntools import Objectify
        >>> from itertools import repeat
        >>>
        >>> kwargs = {'field': 'content', 'dir': 'desc'}
        >>> rule = Objectify(kwargs)
        >>> stream = ({'content': x} for x in range(5))
        >>> tuples = zip(stream, repeat(rule))
        >>> next(parser(stream, [rule], tuples, **kwargs))
        {'content': 4}

    """
    return reduce(reducer, list(reversed(rules)), stream)


@operator(DEFAULTS, isasync=True, **OPTS)
def async_pipe(*args, **kwargs) -> Stream:
    """
    An operator that asynchronously and eagerly sorts the input source
    according to a specified key. Note that this pipe is not lazy.

    Args:
        items (Iter[dict]): The source.
        kwargs (dict): The keyword arguments passed to the wrapper

    Kwargs:
        conf (dict): The pipe configuration. May contain the key 'rule'

            rule (dict): The sort configuration, can be either a dict or list
                of dicts (default: {'dir': 'asc', 'field': 'content'}).
                Must contain the key 'field'. May contain the key 'dir' or 'type'.

                type (str): Expected value type. May be one of
                    'float', 'decimal', 'int', 'text', 'datetime', 'date', 'url',
                    'bool', 'pass' (default: None).

                field (str): Item attribute on which to sort by (default:
                    'content').

                dir (str): The sort direction. Must be either 'asc' or
                    'desc' (default: 'asc').

    Returns:
        Awaitable: stream

    Examples:
        >>> from riko.bado import run
        >>>
        >>> async def main():
        ...     items = [{'rank': 'b'}, {'rank': 'a'}, {'rank': 'c'}]
        ...     result = await async_pipe(items, conf={'rule': {'field': 'rank'}})
        ...     print(next(result))
        >>>
        >>> run(main)
        {'rank': 'a'}

    """
    return parser(*args, **kwargs)


@operator(DEFAULTS, **OPTS)
def pipe(*args, **kwargs) -> Stream:
    """
    An operator that eagerly sorts a stream according to a specified
    key. Note that this pipe is not lazy.

    Args:
        items (Iter[dict]): The source.
        kwargs (dict): The keyword arguments passed to the wrapper

    Kwargs:
        conf (dict): The pipe configuration. May contain the key 'rule'

            rule (dict): The sort configuration, can be either a dict or list
                of dicts (default: {'dir': 'asc', 'field': 'content'}).
                Must contain the key 'field'. May contain the key 'dir' or 'type'.

                type (str): Expected value type. May be one of
                    'float', 'decimal', 'int', 'text', 'datetime', 'date', 'url',
                    'bool', 'pass' (default: None).

                field (str): Item attribute on which to sort by.
                dir (str): The sort direction. Must be either 'asc' or
                    'desc'.

    Yields:
        dict: an item

    Examples:
        >>> items = [
        ...     {'rank': 'b', 'name': 'adam'},
        ...     {'rank': 'a', 'name': 'sue'},
        ...     {'rank': 'c', 'name': 'bill'}]
        >>> rule = {'field': 'rank'}
        >>> next(pipe(items, conf={'rule': rule}))['rank']
        'a'
        >>> rule = {'field': 'name'}
        >>> next(pipe(items, conf={'rule': rule}))['name']
        'adam'
        >>> rule = {'field': 'name', 'dir': 'desc'}
        >>> next(pipe(items, conf={'rule': rule}))['name']
        'sue'
        >>> tied = [
        ...     {'rank': 'a', 'name': 'sue'},
        ...     {'rank': 'a', 'name': 'bill'},
        ...     {'rank': 'b', 'name': 'adam'}]
        >>> rules = [{'field': 'rank'}, {'field': 'name'}]
        >>> [i['name'] for i in pipe(tied, conf={'rule': rules})]
        ['bill', 'sue', 'adam']

    """
    return parser(*args, **kwargs)
