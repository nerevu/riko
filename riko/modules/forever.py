# vim: sw=4:ts=4:expandtab
"""
Produces a placeholder item endlessly.

The stream never ends, so bound it before operations that require the source to
finish.

Examples:

    Basic usage::

        >>> from riko.modules.forever import pipe
        >>>
        >>> next(pipe())
        {'forever': True}

Attributes:

    OPTS: Processor wrapper options.
    DEFAULTS: Default processor configuration.

"""

from __future__ import annotations

from itertools import repeat, takewhile
from typing import TYPE_CHECKING, Any

import pygogo as gogo

from riko.coercion.cast import SourceOpts

from ._decorators import processor

if TYPE_CHECKING:
    from collections.abc import Iterator
    from logging import Logger

    from riko.coercion._dynamic_conf import DynamicConf
    from riko.types._options import Defaults, Opts
    from riko.types._streams import Item

OPTS: Opts = SourceOpts
DEFAULTS: Defaults = {}
logger: Logger = gogo.Gogo(__name__, monolog=True).logger


def parser(
    _: Item, extraction: object, objconf: DynamicConf, **kwargs: object
) -> Iterator[dict[str, bool]]:
    """
    Emits ``{"forever": True}`` endlessly.

    Args:

        _: The item. Unused.
        extraction: The extracted conf value. Unused.
        objconf: The pipe configuration. Unused.

    Returns:

        An endless iterator, one placeholder item at a time.

    Examples:

        >>> result = parser(None, None, None)
        >>> next(result)
        {'forever': True}

    """
    return takewhile(bool, repeat({"forever": True}))


@processor(DEFAULTS, isasync=True, **OPTS)
def async_pipe(*args: Any, **kwargs: object) -> Iterator[dict[str, bool]]:
    """
    Asynchronously yields a placeholder item endlessly.

    Takes no input and reads no configuration. The stream never ends, so bound it
    downstream with ``truncate`` or ``timeout``.

    Args:

        item (Item | Items): The entry, or stream of entries. Unused.
        conf (dict): The pipe configuration. Unused.
        context (Context): the execution context

    Kwargs:

        assign (str): Field each placeholder is nested under. Ignored when
            ``emit`` is True (default: "content").

        emit (bool): Whether to emit each placeholder directly rather than assign
            it. Overrides ``assign`` (default: True).

    Yields:

        - ``{"forever": True}`` when ``emit`` is True (default)
        - ``{<assign>: {"forever": True}}`` when ``emit`` is False and no item given
        - merged ``{Item, <assign>: [...]}`` when ``emit`` is False and an item
          is given — see the note below

    Notes:

        Assigning into an existing item collects every value into one list, so
        ``emit=False`` with an input item never returns. Leave ``emit`` at its
        default, or bound the stream before assigning.

    Examples:

        >>> from riko import run
        >>>
        >>> async def main():
        ...     result = async_pipe()
        ...     print(await anext(result))
        >>>
        >>> run(main)
        {'forever': True}

    """
    return parser(*args, **kwargs)


@processor(DEFAULTS, **OPTS)
def pipe(*args: Any, **kwargs: object) -> Iterator[dict[str, bool]]:
    """
    Emits a placeholder item endlessly.

    Takes no input and reads no configuration. The stream never ends, so bound it
    downstream with ``truncate`` or ``timeout``.

    Args:

        item (Item | Items): The entry, or stream of entries. Unused.
        conf (dict): The pipe configuration. Unused.
        context (Context): the execution context

    Kwargs:

        assign (str): Field each placeholder is nested under. Ignored when
            ``emit`` is True (default: "content").

        emit (bool): Whether to emit each placeholder directly rather than assign
            it. Overrides ``assign`` (default: True).

    Yields:

        - ``{"forever": True}`` when ``emit`` is True (default)
        - ``{<assign>: {"forever": True}}`` when ``emit`` is False and no item given
        - merged ``{Item, <assign>: [...]}`` when ``emit`` is False and an item
          is given (see the note below)

    Notes:

        Assigning into an existing item collects every value into one list. So
        ``emit=False`` with an input item hangs indefinitely. Leave ``emit`` at its
        default, or bound the stream before assigning.

    Examples:

        >>> next(pipe())
        {'forever': True}

    """
    return parser(*args, **kwargs)
