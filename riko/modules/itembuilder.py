# vim: sw=4:ts=4:expandtab
"""
Creates a single-item data source from assigned fields.

With the item builder module, you can create a single-item data source by
assigning values to one or more item fields.

Its strength is restructuring and renaming several elements at once. When fed an
input stream, an assigned value can read an existing field of that stream,
so fields can be reassigned or used to build entirely new ones.

Examples:

    Basic usage::

        >>> from riko.modules.itembuilder import pipe
        >>>
        >>> attrs = {"key": "title", "value": "the title"}
        >>> next(pipe(conf={"attrs": attrs}))["title"]
        'the title'

Attributes:

    OPTS: Processor decoration options.
    DEFAULTS: Default processor configuration.

"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, cast

from riko.base._logging import get_logger
from riko.parsing._dotdict import DotDict
from riko.types._enums import BasicCastType

from ._decorators import processor

if TYPE_CHECKING:
    from collections.abc import Sequence
    from logging import Logger

    from riko.coercion._configs import ItemBuilderObjconf
    from riko.types._options import DecorationOptions, Defaults
    from riko.types._values import RikoDict
    from riko.types.modules import ParsedParam

logger: Logger = get_logger(__name__)

OPTS: DecorationOptions = {
    "ftype": BasicCastType.NONE,
    "listize": True,
    "extract": "attrs",
}

DEFAULTS: Defaults = {}


def parser(
    _: object,
    extraction: Sequence[ParsedParam],
    objconf: ItemBuilderObjconf,
    **kwargs: object,
) -> RikoDict:
    """
    Builds one item from the resolved fields.

    A dotted ``key`` creates a nested value, so ``"desc.content"`` yields
    ``{"desc": {"content": ...}}``.

    Args:

        _: The item. Unused; the fields arrive already resolved.
        extraction: The resolved fields, each with a `key` and `value`.
        objconf: The module configuration. Unused.

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
    return cast("RikoDict", DotDict(item).asdict())


@processor(DEFAULTS, isasync=True, **OPTS)
def async_pipe(*args: Any, **kwargs: object) -> RikoDict:
    """
    Asynchronously builds a single item from assigned fields.

    Args:

        item (Item | Items): The entry, or stream of entries, supplying values.
        conf (dict): The module configuration.

            attrs (dict | list[dict]): The fields to assign. Required.

                key (str): The field name. A dotted path nests, so
                    ``"desc.content"`` yields ``{"desc": {"content": ...}}``.
                value (str | dict): The field value, either a literal or a
                    ``{"subkey": ...}`` reference reading it from ``item``.

        context (Context): the run environment

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
        ...     result = async_pipe(conf={"attrs": attrs})
        ...     print((await anext(result))["title"])
        >>>
        >>> run(main)
        the title

    """
    return parser(*args, **kwargs)


@processor(DEFAULTS, **OPTS)
def pipe(*args: Any, **kwargs: object) -> RikoDict:
    """
    Builds a single item from assigned fields.

    Args:

        item (Item | Items): The entry, or stream of entries, supplying values.
        conf (dict): The module configuration.

            attrs (dict | list[dict]): The fields to assign. Required.

                key (str): The field name. A dotted path nests, so
                    ``"desc.content"`` yields ``{"desc": {"content": ...}}``.
                value (str | dict): The field value, either a literal or a
                    ``{"subkey": ...}`` reference reading it from ``item``.

        context (Context): the run environment

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
