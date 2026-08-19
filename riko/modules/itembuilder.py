# vim: sw=4:ts=4:expandtab
"""
Creates a single-item data source from assigned attributes.

With the item builder module, you can create a single-item data source by
assigning values to one or more item attributes.

Its strength is restructuring and renaming several elements at once. When fed an
input stream, an assigned value can read an existing attribute of that stream,
so attributes can be reassigned or used to build entirely new ones.

Examples:
    Basic usage::

        >>> from riko.modules.itembuilder import pipe
        >>>
        >>> attrs = {"key": "title", "value": "the title"}
        >>> next(pipe(conf={"attrs": attrs}))["title"]
        'the title'

Attributes:
    OPTS: Processor wrapper options.
    DEFAULTS: Default processor configuration.

"""

from collections.abc import Sequence
from logging import Logger
from typing import Any, cast

import pygogo as gogo

from riko.cast import BasicCastType
from riko.dotdict import DotDict
from riko.types.configs import ItemBuilderObjconf
from riko.types.general import Defaults, Opts
from riko.types.modules import ParsedParam
from riko.types.values import RikoDict

from . import processor

OPTS: Opts = {"ftype": BasicCastType.NONE, "listize": True, "extract": "attrs"}
DEFAULTS: Defaults = {}
logger: Logger = gogo.Gogo(__name__, monolog=True).logger


def parser(
    _: object,
    extraction: Sequence[ParsedParam],
    objconf: ItemBuilderObjconf,
    **kwargs: object,
) -> RikoDict:
    """
    Builds one item from the resolved attributes.

    A dotted ``key`` creates a nested value, so ``"desc.content"`` yields
    ``{"desc": {"content": ...}}``.

    Args:
        _: The item. Unused; the attributes arrive already resolved.
        extraction: The resolved attributes, each with a `key` and `value`.
        objconf: The pipe configuration. Unused.

    Returns:
        The built item.

    Examples:
        >>> attrs = [
        ...     {"key": "title", "value": "the title"},
        ...     {"key": "desc", "value": "the desc"}
        ... ]
        >>> parser(None, attrs, None)
        {'title': 'the title', 'desc': 'the desc'}

    """
    item = {a["key"]: a["value"] for a in extraction}
    return cast(RikoDict, DotDict(item).asdict())


@processor(DEFAULTS, isasync=True, **OPTS)
def async_pipe(*args: Any, **kwargs: object) -> RikoDict:
    """
    Asynchronously builds a single item from assigned attributes.

    Args:
        item (Item | Items): The entry, or stream of entries, supplying values.
        conf (dict): The pipe configuration.

            attrs (dict | list): The attributes to assign, either one dict or a
                list of them. Required.

                key (str): The attribute name. A dotted key nests, so
                    ``"desc.content"`` yields ``{"desc": {"content": ...}}``.
                value (str | dict): The attribute value, either a literal or a
                    ``{"subkey": ...}`` reference reading it from ``item``.

        context (Context): the execution context

    Kwargs:
        assign (str): Field the built item is nested under. Ignored when ``emit``
            is True (default: "content").

        emit (bool): Whether to emit the built item directly rather than assign
            it. Overrides ``assign`` (default: True).

    Yields:
        - the built item when ``emit`` is True (default)
        - ``{<assign>: <built>}`` when ``emit`` is False and no item given
        - merged ``{Item, <assign>: <built>}`` when ``emit`` is False and item is given

    Raises:
        TypeError: If ``conf`` has no ``attrs`` key.

    Examples:
        >>> from riko import run
        >>>
        >>> async def main():
        ...     attrs = [
        ...         {"key": "title", "value": "the title"},
        ...         {"key": "desc.content", "value": "the desc"}]
        ...
        ...     result = await async_pipe(conf={"attrs": attrs})
        ...     print(next(result)["title"])
        >>>
        >>> run(main)
        the title

    """
    return parser(*args, **kwargs)


@processor(DEFAULTS, **OPTS)
def pipe(*args: Any, **kwargs: object) -> RikoDict:
    """
    Builds a single item from assigned attributes.

    Args:
        item (Item | Items): The entry, or stream of entries, supplying values.
        conf (dict): The pipe configuration.

            attrs (dict | list): The attributes to assign, either one dict or a
                list of them. Required.

                key (str): The attribute name. A dotted key nests, so
                    ``"desc.content"`` yields ``{"desc": {"content": ...}}``.
                value (str | dict): The attribute value, either a literal or a
                    ``{"subkey": ...}`` reference reading it from ``item``.

        context (Context): the execution context

    Kwargs:
        assign (str): Field the built item is nested under. Ignored when ``emit``
            is True (default: "content").

        emit (bool): Whether to emit the built item directly rather than assign
            it. Overrides ``assign`` (default: True).

    Yields:
        - the built item when ``emit`` is True (default)
        - ``{<assign>: <built>}`` when ``emit`` is False and no item given
        - merged ``{Item, <assign>: <built>}`` when ``emit`` is False and item is given

    Raises:
        TypeError: If ``conf`` has no ``attrs`` key.

    Examples:
        >>> attrs = [
        ...     {"key": "title", "value": "the title"},
        ...     {"key": "desc.content", "value": "the desc"}]
        >>> next(pipe(conf={"attrs": attrs}))
        {'title': 'the title', 'desc': {'content': 'the desc'}}

    """
    return parser(*args, **kwargs)
