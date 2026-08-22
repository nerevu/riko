# vim: sw=4:ts=4:expandtab
"""
Provides functions for splitting a string into an array of strings.

A delimiter string (often just a single character) tells the module where to
split the input string. The delimiter string doesn't appear in the output.

Examples:
    basic usage::

        >>> from riko.modules.tokenizer import pipe
        >>>
        >>> item = {'content': 'Once,twice,thrice'}
        >>> next(pipe(item))
        {'content': 'Once'}

Attributes:
    OPTS (dict): The default pipe options
    DEFAULTS (dict): The default parser options

"""

from collections.abc import Iterator
from logging import Logger
from typing import Any

import pygogo as gogo

from riko.cast import BasicCastType
from riko.types.configs import TokenizerObjconf
from riko.types.general import Defaults, Extraction, Opts

from . import processor

TOKEN_KEY = "content"  # noqa: S105

OPTS: Opts = {"ftype": BasicCastType.TEXT, "field": "content"}
DEFAULTS: Defaults = {
    "delimiter": ",",
    "dedupe": False,
    "sort": False,
    "token_key": TOKEN_KEY,
}


logger: Logger = gogo.Gogo(__name__, monolog=True).logger


def parser(
    content: str, extraction: Extraction, objconf: TokenizerObjconf, **kwargs: object
) -> Iterator[dict[str, str]]:
    """
    Parses the pipe content

    Args:
        content (str): The content to tokenize
        objconf (obj): The pipe configuration (an Objectify instance)

    Returns:
        Iter[dict]: The stream of items

    Examples:
        >>> from meza.fntools import Objectify
        >>>
        >>> objconf = Objectify({'delimiter': '//', 'token_key': 'token'})
        >>> content = 'Once//twice//thrice//no more'
        >>> result = parser(content, None, objconf)
        >>> next(result)
        {'token': 'Once'}

    """
    keyfunc = lambda s: s.lower()
    splits = [s.strip() for s in content.split(objconf.delimiter) if s]
    deduped = dict.fromkeys(splits) if objconf.dedupe else splits
    chunks = sorted(deduped, key=keyfunc) if objconf.sort else deduped
    token_key = objconf.token_key or TOKEN_KEY
    return ({token_key: chunk} for chunk in chunks)


@processor(DEFAULTS, isasync=True, **OPTS)
def async_pipe(*args: Any, **kwargs: object) -> Iterator[dict[str, str]]:
    """
    A processor module that asynchronously splits a string by a delimiter.

    Args:
        item (dict or Iter[dict]): The entry, or stream of entries, to process
        kwargs (dict): The keyword arguments passed to the wrapper

    Kwargs:
        conf (dict): The pipe configuration. May contain the keys 'delimiter',
            'dedupe', 'sort', or 'token_key'.

            delimiter (str): the delimiter string (default: ',')
            dedupe (bool): Remove duplicates (default: False).
            sort (bool): Sort tokens (default: False)

            token_key (str): Attribute to assign individual tokens (default:
                content)

        assign (str): Attribute to assign parsed content (default:
            tokenizer)

        field (str): Item attribute from which to obtain the string to be
            tokenized (default: 'content')

        emit (bool): Return the stream as is and don't assign it to an item
            attribute (default: False)

    Returns:
        Awaitable: item with tokenized content

    Examples:
        >>> from riko import run
        >>>
        >>> async def main():
        ...     item = {'content': 'Once,twice,thrice,no more'}
        ...     result = await async_pipe(item)
        ...     print(next(result))
        >>>
        >>> run(main)
        {'content': 'Once'}

    """
    return parser(*args, **kwargs)


@processor(DEFAULTS, **OPTS)
def pipe(*args: Any, **kwargs: object) -> Iterator[dict[str, str]]:
    """
    A processor that splits a string by a delimiter.

    Args:
        item (dict or Iter[dict]): The entry, or stream of entries, to process
        kwargs (dict): The keyword arguments passed to the wrapper

    Kwargs:
        conf (dict): The pipe configuration. May contain the keys 'delimiter',
            'dedupe', 'sort', or 'token_key'.

            delimiter (str): the delimiter string (default: ',')
            dedupe (bool): Remove duplicates (default: False).
            sort (bool): Sort tokens (default: False)
            token_key (str): Attribute to assign individual tokens (default:
                content)

        assign (str): Attribute to assign parsed content (default:
            tokenizer)

        field (str): Item attribute from which to obtain the string to be
            tokenized (default: content)

        emit (bool): Return the stream as is and don't assign it to an item
            attribute (default: False)

    Returns:
        dict: an item with tokenized content

    Examples:
        >>> item = {'description': 'Once//twice//thrice//no more'}
        >>> conf = {'delimiter': '//', 'sort': True}
        >>> kwargs = {'field': 'description', 'emit': False, 'assign': 'tokens'}
        >>> next(pipe(item, conf=conf, **kwargs))['tokens'][0]
        {'content': 'no more'}
        >>> kwargs.update({'emit': True})
        >>> conf.update({'token_key': 'token'})
        >>> next(pipe(item, conf=conf, **kwargs))
        {'token': 'no more'}
        >>> conf = {"dedupe": True}
        >>> item = {"content": "delta,alpha,delta,bravo,alpha"}
        >>> [t["content"] for t in pipe(item, conf=conf)]
        ['delta', 'alpha', 'bravo']

    """
    return parser(*args, **kwargs)
