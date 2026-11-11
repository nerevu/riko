# vim: sw=4:ts=4:expandtab
"""
Converts a text string into a date dict.

Accepts commonly formatted date, shorthands (``"today"``/``"tomorrow"``/``"yesterday"``/
``"now"``), offsets (``"3 days"``, ``"-1 month"``, etc.), and word forms
(``"next week"``, ``"last year"``, etc.). The date dict is JSON-friendly: all fields are
either int, str, bool, or None.

Examples:

    Basic usage::

        >>> from riko.modules.datebuilder import pipe
        >>>
        >>> next(pipe({"content": "12/2/2014"}))["datebuilder"]["year"]
        2014

Attributes:

    OPTS: Processor decoration options.
    DEFAULTS: Default processor configuration.

"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from riko.base._logging import get_logger
from riko.base._typing import DateLikeType
from riko.coercion._dates import datetime_to_datedict
from riko.coercion.cast import cast_datetime
from riko.types._enums import BasicCastType

from ._decorators import processor

if TYPE_CHECKING:
    from logging import Logger

    from riko.coercion._dynamic_conf import DynamicConf
    from riko.types._options import DecorationOptions, Defaults
    from riko.types._scalars import DateDict

logger: Logger = get_logger(__name__)

OPTS: DecorationOptions = {
    "ptype": BasicCastType.NONE,
    "field": "content",
    "emit": False,
}
DEFAULTS: Defaults = {}


def parser(
    text: str, extraction: object, objconf: DynamicConf, **kwargs: object
) -> DateDict:
    """
    Converts ``text`` into a date dict.

    Args:

        text: The text to convert.
        extraction: The extracted conf value. Unused.
        objconf: The module configuration. Unused.

    Returns:

        The date dict.

    Raises:

        ValueError: If ``text`` names no date the module recognizes.

    Examples:

        >>> item = {"content": "12/2/2014"}
        >>> parser(item["content"], None, None, stream=item)["year"]
        2014

    """
    try:
        new_date = cast_datetime(text) if isinstance(text, DateLikeType) else None
    except ValueError:
        new_date = None

    if new_date is None:
        raise ValueError(f"the 'datebuilder' module got an unrecognized date {text!r}")

    return datetime_to_datedict(new_date)


@processor(DEFAULTS, isasync=True, **OPTS)
def async_pipe(*args: Any, **kwargs: object) -> DateDict:
    """
    Asynchronously converts a text string into a date dict.

    Both iterator and iterable sources are mapped over. See the FAQ's "How does a
    processor map over items?".

    Args:

        item (Item | Items): The entry, or stream of entries, to process.
        context (Context): the run environment

    Kwargs:

        field (str): Item field to convert (default: "content").

        assign (str): Field the date is assigned to. Ignored when ``emit`` is
            True (default: "datebuilder").

        emit (bool): Whether to emit the date in place of the item rather than
            assign it. Overrides ``assign`` (default: False).

    Yields:

        - merged ``{Item, <assign>: <date>}`` when ``emit`` is False and item is
          given (default)
        - ``{<assign>: <date>}`` when ``emit`` is False and no item given
        - ``<date>`` when ``emit`` is True

    Raises:

        ValueError: If the field names no date the module recognizes.

    Notes:

        An offset counts a unit from ``seconds`` to ``years``, signed or not.
        Sub-day units offset from the current time, the rest from today, and
        both resolve against the clock at call time.

        A ``date``, ``datetime``, or ``struct_time`` passes through, an ``int``
        reads as epoch seconds, and a partial date such as ``"2014"`` takes its
        missing parts from today.

    Examples:

        >>> from riko import run
        >>>
        >>> async def main():
        ...     result = async_pipe({"content": "12/2/2014"})
        ...     print((await anext(result))["datebuilder"]["year"])
        >>>
        >>> run(main)
        2014

    """
    return parser(*args, **kwargs)


@processor(DEFAULTS, **OPTS)
def pipe(*args: Any, **kwargs: object) -> DateDict:
    """
    Converts a text string into a date dict.

    Both iterator and iterable sources are mapped over. See the FAQ's "How does a
    processor map over items?".

    Args:

        item (Item | Items): The entry, or stream of entries, to process.
        context (Context): the run environment

    Kwargs:

        field (str): Item field to convert (default: "content").

        assign (str): Field the date is assigned to. Ignored when ``emit`` is
            True (default: "datebuilder").

        emit (bool): Whether to emit the date in place of the item rather than
            assign it. Overrides ``assign`` (default: False).

    Yields:

        - merged ``{Item, <assign>: <date>}`` when ``emit`` is False and item is
          given (default)
        - ``{<assign>: <date>}`` when ``emit`` is False and no item given
        - ``<date>`` when ``emit`` is True

    Raises:

        ValueError: If the field names no date the module recognizes.

    Notes:

        An offset counts a unit from ``seconds`` to ``years``, signed or not.
        Sub-day units offset from the current time, the rest from today, and
        both resolve against the clock at call time.

        A ``date``, ``datetime``, or ``struct_time`` passes through, an ``int``
        reads as epoch seconds, and a partial date such as ``"2014"`` takes its
        missing parts from today.

    Examples:

        >>> next(pipe({"content": "12/2/2014"}))["datebuilder"]["year"]
        2014
        >>> built = next(pipe({"content": "5/4/82"}, emit=True))
        >>> built["year"], built["month"], built["day"], built["timezone"]
        (1982, 5, 4, 'UTC')
        >>> next(pipe({"content": "tomorrow"}, emit=True))["hour"]
        0
        >>> yesterday = next(pipe({"content": "-1 day"}, emit=True))
        >>> yesterday == next(pipe({"content": "yesterday"}, emit=True))
        True
        >>> next(pipe({"content": "bogus"}))
        Traceback (most recent call last):
            ...
        ValueError: the 'datebuilder' module got an unrecognized date 'bogus'

    """
    return parser(*args, **kwargs)
