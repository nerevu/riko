# vim: sw=4:ts=4:expandtab
"""
Renames, copies, or deletes item fields.

Each rule maps an existing ``field`` onto a ``newval``. Omit ``newval`` to
delete the field instead, or set ``copy`` to keep the original alongside the
new one. Useful when input data is not in RSS form and you want to emit it as
RSS.

Examples:
    Basic usage::

        >>> from riko.modules.rename import pipe
        >>>
        >>> conf = {"rule": {"field": "content", "newval": "greeting"}}
        >>> item = {"content": "hello world"}
        >>> next(pipe(item, conf=conf))
        {'greeting': 'hello world'}

Attributes:
    OPTS: Processor wrapper options.
    DEFAULTS: Default processor configuration.

"""

from collections.abc import Sequence
from functools import reduce
from logging import Logger
from typing import Any, cast

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
logger: Logger = gogo.Gogo(__name__, monolog=True).logger


_MISSING = object()


def reducer(item: Item, rule: RenameConfRule) -> Item:
    value = DotDict(item).get(rule.field, _MISSING)
    reduced = DotDict(item if rule.copy else remove_keys(item, rule.field))

    if rule.newval and value is not _MISSING:
        reduced.update({rule.newval: value})

    return cast(Item, reduced)


async def async_parser(
    item: Item,
    rules: Sequence[RenameConfRule],
    objconf: RenameObjconf,
    **kwargs: object,
) -> Item:
    """
    Asynchronously applies each rename rule in turn to ``item``.

    Args:
        item: The entry to process.
        rules: The parsed rename rules.
        objconf: The pipe configuration. Unused.

    Returns:
        The item with each rule applied.

    Examples:
        >>> from riko import run
        >>> from meza.fntools import Objectify
        >>>
        >>> async def main():
        ...     item = {"content": "hello world"}
        ...     rule = {"field": "content", "newval": "greeting"}
        ...     result = await async_parser(item, [Objectify(rule)], None, stream=item)
        ...     print(result)
        >>>
        >>> run(main)
        {'greeting': 'hello world'}

    """
    return await coop_reduce(reducer, rules, item)


def parser(
    item: Item,
    rules: Sequence[RenameConfRule],
    objconf: RenameObjconf,
    **kwargs: object,
) -> Item:
    """
    Applies each rename rule in turn to ``item``.

    Args:
        item: The entry to process.
        rules: The parsed rename rules.
        objconf: The pipe configuration. Unused.

    Returns:
        The item with each rule applied.

    Examples:
        >>> from meza.fntools import Objectify
        >>>
        >>> item = {"content": "hello world"}
        >>> rule = {"field": "content", "newval": "greeting"}
        >>> args = [item, [Objectify(rule)], None]
        >>> parser(*args, stream=item)
        {'greeting': 'hello world'}

    """
    return reduce(reducer, rules, item)


@processor(DEFAULTS, isasync=True, **OPTS)
async def async_pipe(*args: Any, **kwargs: object) -> Item:
    """
    Asynchronously renames, copies, or deletes item fields.

    Both iterator and iterable sources are mapped over. See the FAQ's "How does a
    processor map over items?".

    Args:
        item (Item | Items): The entry, or stream of entries, to process.

        conf (dict): The pipe configuration.

            rule (dict | list): The rename criteria, one dict or a list of
                them. Required.

                field (str): Item attribute to rename, copy, or delete.

                newval (str): New attribute name. A dotted name nests, so
                    ``"a.b"`` yields ``{"a": {"b": <value>}}``. Omit it to
                    delete ``field`` instead (default: None).

                copy (bool): Whether to keep ``field`` as well as adding
                    ``newval`` (default: False).

        context (Context): the execution context

    Kwargs:
        assign (str): Field the rewritten item is nested under. Ignored when
            ``emit`` is True (default: "rename").

        emit (bool): Whether to emit the rewritten item directly rather than
            nest it. Overrides ``assign`` (default: True).

    Yields:
        - the rewritten ``Item`` when ``emit`` is True (default)
        - ``{<assign>: Item}`` when ``emit`` is False

    Raises:
        TypeError: If ``conf`` has no ``rule`` key.

    Notes:
        A rule naming a field the item lacks is skipped, leaving the item
        untouched.

    Examples:
        >>> from riko import run
        >>>
        >>> async def main():
        ...     conf = {"rule": {"field": "content", "newval": "greeting"}}
        ...     result = await async_pipe({"content": "hello world"}, conf=conf)
        ...     print(next(result)["greeting"])
        >>>
        >>> run(main)
        hello world

    """
    return await async_parser(*args, **kwargs)


@processor(DEFAULTS, **OPTS)
def pipe(*args: Any, **kwargs: object) -> Item:
    """
    Renames, copies, or deletes item fields.

    Both iterator and iterable sources are mapped over. See the FAQ's "How does a
    processor map over items?".

    Args:
        item (Item | Items): The entry, or stream of entries, to process.

        conf (dict): The pipe configuration.

            rule (dict | list): The rename criteria, one dict or a list of
                them. Required.

                field (str): Item attribute to rename, copy, or delete.

                newval (str): New attribute name. A dotted name nests, so
                    ``"a.b"`` yields ``{"a": {"b": <value>}}``. Omit it to
                    delete ``field`` instead (default: None).

                copy (bool): Whether to keep ``field`` as well as adding
                    ``newval`` (default: False).

        context (Context): the execution context

    Kwargs:
        assign (str): Field the rewritten item is nested under. Ignored when
            ``emit`` is True (default: "rename").

        emit (bool): Whether to emit the rewritten item directly rather than
            nest it. Overrides ``assign`` (default: True).

    Yields:
        - the rewritten ``Item`` when ``emit`` is True (default)
        - ``{<assign>: Item}`` when ``emit`` is False

    Raises:
        TypeError: If ``conf`` has no ``rule`` key.

    Notes:
        A rule naming a field the item lacks is skipped, leaving the item
        untouched.

    Examples:
        >>> rule = {"field": "content", "newval": "greeting"}
        >>> item = {"content": "hello world"}
        >>> next(pipe(item, conf={"rule": rule}))
        {'greeting': 'hello world'}
        >>> conf = {"rule": {"field": "content"}}
        >>> next(pipe({"content": "hello world"}, conf=conf))
        {}
        >>> rule["copy"] = True
        >>> result = pipe({"content": "hello world"}, conf={"rule": rule})
        >>> sorted(next(result))
        ['content', 'greeting']

    """
    return parser(*args, **kwargs)
