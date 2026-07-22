# vim: sw=4:ts=4:expandtab
"""
Provides functions for performing string transformations on text, e.g.,
capitalize, uppercase, etc.

Examples:
    basic usage::

        >>> from riko.modules.strtransform import pipe
        >>>
        >>> conf = {'rule': {'transform': 'title'}}
        >>> item = {'content': 'hello world'}
        >>> next(pipe(item, conf=conf))['strtransform']
        'Hello World'

Attributes:
    OPTS (dict): The default pipe options
    DEFAULTS (dict): The default parser options

"""

from collections.abc import Sequence
from functools import reduce

import pygogo as gogo

from riko.bado.itertools import coop_reduce
from riko.cast import BasicCastType
from riko.types.configs import StrTransformObjconf
from riko.types.general import Defaults, Opts
from riko.types.modules import StrTransformConfRule

from . import processor

OPTS: Opts = {
    "listize": True,
    "ftype": BasicCastType.TEXT,
    "field": "content",
    "extract": "rule",
}
DEFAULTS: Defaults = {}
logger = gogo.Gogo(__name__, monolog=True).logger

ATTRS = {
    "capitalize",
    "lower",
    "upper",
    "swapcase",
    "title",
    "strip",
    "rstrip",
    "lstrip",
    "zfill",
    "replace",
    "count",
    "find",
}


def reducer(word, rule):
    if rule.transform in ATTRS:
        args = rule.args.split(",") if rule.args else []
        result = getattr(word, rule.transform)(*args)
    else:
        logger.warning(f"Invalid transformation: {rule.transform}")
        result = word

    return result


async def async_parser(
    word: str,
    rules: Sequence[StrTransformConfRule],
    objconf: StrTransformObjconf,
    **kwargs,
):
    """
    Asynchronously parses the pipe content

    Args:
        word (str): The string to transform
        rules (List[obj]): the parsed rules (Objectify instances).
        kwargs (dict): Keyword arguments

    Kwargs:
        assign (str): Attribute to assign parsed content (default: strtransform)
        stream (dict): The original item

    Returns:
        Awaitable: item

    Examples:
        >>> from riko.bado import run
        >>> from meza.fntools import Objectify
        >>>
        >>> async def main():
        ...     item = {'content': 'hello world'}
        ...     conf = {'rule': {'transform': 'title'}}
        ...     rule = Objectify(conf['rule'])
        ...     result = await async_parser(item['content'], [rule], None, stream=item)
        ...     print(result)
        >>>
        >>> run(main)
        Hello World

    """
    return await coop_reduce(reducer, rules, word)


def parser(
    word: str,
    rules: Sequence[StrTransformConfRule],
    objconf: StrTransformObjconf,
    **kwargs,
) -> str:
    """
    Parses the pipe content

    Args:
        word (str): The string to transform
        rules (List[obj]): the parsed rules (Objectify instances).
        kwargs (dict): Keyword arguments

    Kwargs:
        assign (str): Attribute to assign parsed content (default: strtransform)
        stream (dict): The original item

    Returns:
        dict: The item

    Examples:
        >>> from meza.fntools import Objectify
        >>>
        >>> item = {'content': 'hello world'}
        >>> conf = {'rule': {'transform': 'title'}}
        >>> rule = Objectify(conf['rule'])
        >>> args = item['content'], [rule], False
        >>> kwargs = {'stream': item, 'conf': conf}
        >>> parser(*args, **kwargs)
        'Hello World'

    """
    return reduce(reducer, rules, word)


@processor(DEFAULTS, isasync=True, **OPTS)
async def async_pipe(*args, **kwargs) -> str:
    """
    A processor module that asynchronously performs string transformations
    on the field of an item.

    Args:
        item (dict): The entry to process
        kwargs (dict): The keyword arguments passed to the wrapper

    Kwargs:
        conf (dict): The pipe configuration. Must contain the key 'rule'.

            rule (dict): can be either a dict or list of dicts. Must contain
                the key 'transform'. May contain the key 'args'

                transform (str): The string transformation to apply. Must be
                    one of: 'capitalize', 'lower', 'upper', 'swapcase',
                    'title', 'strip', 'rstrip', 'lstrip', 'zfill', 'replace',
                    'count', or 'find'

                args (str): A comma separated list of arguments to supply the
                    transformer.

        assign (str): Attribute to assign parsed content (default: strtransform)
        field (str): Item attribute to operate on (default: 'content')

    Returns:
       Awaitable: item with transformed content

    Examples:
        >>> from riko.bado import run
        >>>
        >>> async def main():
        ...     conf = {'rule': {'transform': 'title'}}
        ...     result = await async_pipe({'content': 'hello world'}, conf=conf)
        ...     print(next(result)['strtransform'])
        >>>
        >>> run(main)
        Hello World

    """
    parsed = await async_parser(*args, **kwargs)
    return parsed


@processor(DEFAULTS, **OPTS)
def pipe(*args, **kwargs) -> str:
    """
    A processor that performs string transformations on the field of an item.

    Args:
        item (dict): The entry to process
        kwargs (dict): The keyword arguments passed to the wrapper

    Kwargs:
        conf (dict): The pipe configuration. Must contain the key 'rule'.

            rule (dict): can be either a dict or list of dicts. Must contain
                the key 'transform'. May contain the key 'args'

                transform (str): The string transformation to apply. Must be
                    one of: 'capitalize', 'lower', 'upper', 'swapcase',
                    'title', 'strip', 'rstrip', 'lstrip', 'zfill', 'replace',
                    'count', or 'find'

                args (str): A comma separated list of arguments to supply the
                    transformer.

        assign (str): Attribute to assign parsed content (default: strtransform)
        field (str): Item attribute to operate on (default: 'content')

    Yields:
        dict: an item with transformed content

    Examples:
        >>> conf = {'rule': {'transform': 'title'}}
        >>> item = {'content': 'hello world'}
        >>> next(pipe(item, conf=conf))['strtransform']
        'Hello World'
        >>> rules = [
        ...     {'transform': 'lower'}, {'transform': 'count', 'args': 'g'}]
        >>> conf = {'rule': rules}
        >>> kwargs = {'conf': conf, 'field': 'title', 'assign': 'result'}
        >>> next(pipe({'title': 'Greetings'}, **kwargs))['result']
        2

    """
    return parser(*args, **kwargs)
