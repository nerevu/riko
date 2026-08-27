# vim: sw=4:ts=4:expandtab
"""
Splits a string into tokens.

Each token is whitespace-stripped and emitted on its own.

Examples:
    Basic usage::

        >>> from riko.modules.tokenizer import pipe
        >>>
        >>> next(pipe({"content": "Once,twice,thrice"}))
        {'content': 'Once'}

Attributes:
    TOKEN_KEY: The field each token is assigned to when ``conf`` supplies none.
    OPTS: Processor wrapper options.
    DEFAULTS: Default processor configuration.

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
    Splits ``content`` on the configured delimiter.

    Args:
        content: The string to split.

        extraction: The extracted conf value. Unused.

        objconf: The pipe configuration, containing `delimiter`, `dedupe`, `sort` and
            `token_key`.

    Returns:
        The tokens, each wrapped in a dict.

    Examples:
        >>> from meza.fntools import Objectify
        >>>
        >>> objconf = Objectify({"delimiter": "//", "token_key": "token"})
        >>> next(parser("Once//twice//thrice//no more", None, objconf))
        {'token': 'Once'}

    """
    splits = [s.strip() for s in content.split(objconf.delimiter) if s]
    deduped = dict.fromkeys(splits) if objconf.dedupe else splits
    chunks = sorted(deduped, key=str.lower) if objconf.sort else deduped
    token_key = objconf.token_key or TOKEN_KEY
    return ({token_key: chunk} for chunk in chunks)


@processor(DEFAULTS, isasync=True, **OPTS)
def async_pipe(*args: Any, **kwargs: object) -> Iterator[dict[str, str]]:
    """
    Asynchronously splits a string into tokens.

    Both iterator and iterable sources are mapped over. See the FAQ's "How does a
    processor map over items?".

    Args:
        item (Item | Items): The entry, or stream of entries, to process.

        conf (dict): The pipe configuration.

            delimiter (str): Where to split the string (default: ",").

            dedupe (bool): Whether to drop repeated tokens (default: False).

            sort (bool): Whether to sort the tokens, ignoring case
                (default: False).

            token_key (str): Field each token is assigned to
                (default: "content").

        context (Context): the execution context

    Kwargs:
        field (str): Item attribute to split (default: "content").

        assign (str): Field the tokens are nested under. Ignored when ``emit``
            is True (default: "tokenizer").

        emit (bool): Whether to emit each token directly rather than nest them.
            Overrides ``assign`` (default: True).

    Yields:
        - ``<token>`` when ``emit`` is True (default)
        - ``{<assign>: <token>}`` when ``emit`` is False and no item given
        - one merged ``{Item, <assign>: [<token>, ...]}`` when ``emit`` is False
          and item is given

    Notes:
        Empty tokens are dropped, and ``dedupe`` keeps the first occurrence of
        each, so the input order survives. A field the item lacks yields nothing.

    Examples:
        >>> from riko import run
        >>>
        >>> async def main():
        ...     result = await async_pipe({"content": "Once,twice,thrice"})
        ...     print(next(result))
        >>>
        >>> run(main)
        {'content': 'Once'}

    """
    return parser(*args, **kwargs)


@processor(DEFAULTS, **OPTS)
def pipe(*args: Any, **kwargs: object) -> Iterator[dict[str, str]]:
    """
    Splits a string into tokens.

    Both iterator and iterable sources are mapped over. See the FAQ's "How does a
    processor map over items?".

    Args:
        item (Item | Items): The entry, or stream of entries, to process.

        conf (dict): The pipe configuration.

            delimiter (str): Where to split the string (default: ",").

            dedupe (bool): Whether to drop repeated tokens (default: False).

            sort (bool): Whether to sort the tokens, ignoring case
                (default: False).

            token_key (str): Field each token is assigned to
                (default: "content").

        context (Context): the execution context

    Kwargs:
        field (str): Item attribute to split (default: "content").

        assign (str): Field the tokens are nested under. Ignored when ``emit``
            is True (default: "tokenizer").

        emit (bool): Whether to emit each token directly rather than nest them.
            Overrides ``assign`` (default: True).

    Yields:
        - ``<token>`` when ``emit`` is True (default)
        - ``{<assign>: <token>}`` when ``emit`` is False and no item given
        - one merged ``{Item, <assign>: [<token>, ...]}`` when ``emit`` is False
          and item is given

    Notes:
        Empty tokens are dropped, and ``dedupe`` keeps the first occurrence of
        each, so the input order survives. A field the item lacks yields nothing.

    Examples:
        >>> item = {"description": "Once//twice//thrice//no more"}
        >>> conf = {"delimiter": "//", "sort": True}
        >>> kwargs = {"field": "description", "emit": False, "assign": "tokens"}
        >>> next(pipe(item, conf=conf, **kwargs))["tokens"][0]
        {'content': 'no more'}
        >>> kwargs.update({"emit": True})
        >>> conf.update({"token_key": "token"})
        >>> next(pipe(item, conf=conf, **kwargs))
        {'token': 'no more'}
        >>> conf = {"dedupe": True}
        >>> item = {"content": "delta,alpha,delta,bravo,alpha"}
        >>> [t["content"] for t in pipe(item, conf=conf)]
        ['delta', 'alpha', 'bravo']

    """
    return parser(*args, **kwargs)
