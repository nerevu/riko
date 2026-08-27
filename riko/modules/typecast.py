# vim: sw=4:ts=4:expandtab
"""
Casts an item field into a specific type.

Useful as terminal data. Loopable.

Examples:
    Basic usage::

        >>> from riko.modules.typecast import pipe
        >>>
        >>> conf = {"type": "date"}
        >>> next(pipe({"content": "5/4/82"}, conf=conf))["typecast"].year
        1982

Attributes:
    OPTS: Processor wrapper options.
    DEFAULTS: Default processor configuration.

"""

from logging import Logger
from typing import Any

import pygogo as gogo

from riko.cast import CastType, cast_value
from riko.types.configs import TypecastObjconf
from riko.types.general import Defaults, Extraction, Opts
from riko.types.values import PrimitiveValue

from . import processor

OPTS: Opts = {"field": "content"}
DEFAULTS: Defaults = {"type": "text"}

logger: Logger = gogo.Gogo(__name__, monolog=True).logger


def parser(
    content: str, extraction: Extraction, objconf: TypecastObjconf, **kwargs: object
) -> PrimitiveValue:
    """
    Casts ``content`` to the configured type.

    Args:
        content: The value to cast.
        extraction: The extracted conf value. Unused.
        objconf: The pipe configuration, containing `type`.

    Returns:
        The cast value, or ``content`` unchanged when ``type`` is unset.

    Examples:
        >>> from meza.fntools import Objectify
        >>>
        >>> item = {"content": "1.0"}
        >>> objconf = Objectify({"type": "int"})
        >>> kwargs = {"stream": item, "assign": "content"}
        >>> parser(item["content"], None, objconf, **kwargs)
        1

    """
    return cast_value(content, CastType(objconf.type)) if objconf.type else content


@processor(DEFAULTS, isasync=True, **OPTS)
def async_pipe(*args: Any, **kwargs: object) -> PrimitiveValue:
    """
    Asynchronously casts an item field into another type.

    Both iterator and iterable sources are mapped over. See the FAQ's "How does a
    processor map over items?".

    Args:
        item (Item | Items): The entry, or stream of entries, to process.

        conf (dict): The pipe configuration.

            type (str): Type to cast to, one of "bool", "date", "datetime",
                "decimal", "float", "int", "location", "none", "pass", "text",
                "url" (default: "text").

        context (Context): the execution context

    Kwargs:
        field (str): Item attribute to cast. A missing field casts ``None``
            (default: "content").

        assign (str): Field the cast value is assigned to. Ignored when ``emit``
            is True (default: "typecast").

        emit (bool): Whether to emit the cast value in place of the item rather
            than assign it. Overrides ``assign`` (default: False).

    Yields:
        - merged ``{Item, <assign>: <value>}`` when ``emit`` is False and item
          is given (default)
        - ``{<assign>: <value>}`` when ``emit`` is False and no item given
        - ``<value>`` when ``emit`` is True

    Examples:
        >>> from riko import run
        >>>
        >>> async def main():
        ...     result = await async_pipe({"content": "1.0"}, conf={"type": "int"})
        ...     print(next(result)["typecast"])
        >>>
        >>> run(main)
        1

    """
    return parser(*args, **kwargs)


@processor(DEFAULTS, **OPTS)
def pipe(*args: Any, **kwargs: object) -> PrimitiveValue:
    """
    Casts an item field into another type.

    Both iterator and iterable sources are mapped over. See the FAQ's "How does a
    processor map over items?".

    Args:
        item (Item | Items): The entry, or stream of entries, to process.

        conf (dict): The pipe configuration.

            type (str): Type to cast to, one of "bool", "date", "datetime",
                "decimal", "float", "int", "location", "none", "pass", "text",
                "url" (default: "text").

        context (Context): the execution context

    Kwargs:
        field (str): Item attribute to cast. A missing field casts ``None``
            (default: "content").

        assign (str): Field the cast value is assigned to. Ignored when ``emit``
            is True (default: "typecast").

        emit (bool): Whether to emit the cast value in place of the item rather
            than assign it. Overrides ``assign`` (default: False).

    Yields:
        - merged ``{Item, <assign>: <value>}`` when ``emit`` is False and item
          is given (default)
        - ``{<assign>: <value>}`` when ``emit`` is False and no item given
        - ``<value>`` when ``emit`` is True

    Examples:
        >>> from datetime import datetime as dt
        >>>
        >>> next(pipe({"content": "1.0"}, conf={"type": "int"}))["typecast"]
        1
        >>> conf = {"type": "datetime"}
        >>> item = {"content": "5/4/82"}
        >>> next(pipe(item, conf=conf, emit=True)).isoformat()
        '1982-05-04T00:00:00+00:00'
        >>> next(pipe({"content": "bogus"}, conf=conf, emit=True))
        >>> item = {"content": dt(1982, 5, 4).timetuple()}
        >>> next(pipe(item, conf=conf, emit=True)).isoformat()
        '1982-05-04T00:00:00+00:00'
        >>> item = {"content": None}
        >>> next(pipe(item, emit=True))
        ''
        >>> conf = {"type": "bool"}
        >>> next(pipe(item, conf=conf, emit=True))
        False

    """
    # TODO: add option to specify timezone
    return parser(*args, **kwargs)
