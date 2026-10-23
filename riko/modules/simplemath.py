# vim: sw=4:ts=4:expandtab
"""
Performs a simple mathematical operation on an item field.

The field value and ``other`` are both cast to ``Decimal``, so results are
exact rather than binary floats.

Examples:

    Basic usage::

        >>> from decimal import Decimal
        >>> from riko.modules.simplemath import pipe
        >>>
        >>> conf = {"op": "divide", "other": "5"}
        >>> next(pipe({"content": "10"}, conf=conf))["simplemath"]
        Decimal('2')

Attributes:

    OPS: Supported operations, keyed by ``op`` name.
    OPTS: Processor decoration options.
    DEFAULTS: Default processor configuration.

"""

from __future__ import annotations

import operator
from typing import TYPE_CHECKING, Any

from riko.base._logging import get_logger
from riko.base._require_guards import require_conf_key
from riko.coercion.cast import cast_value
from riko.types._enums import BasicCastType, CastType

from ._decorators import processor

if TYPE_CHECKING:
    from collections.abc import Callable
    from decimal import Decimal
    from logging import Logger

    from riko.coercion._configs import SimpleMathObjconf
    from riko.types._options import DecorationOptions, Defaults
    from riko.types._scalars import NumLike

OPTS: DecorationOptions = {"ftype": BasicCastType.DECIMAL, "field": "content"}
DEFAULTS: Defaults = {}
logger: Logger = get_logger(__name__)


def mean(*nums: NumLike) -> float:
    try:
        return sum(nums) / len(nums)  # type: ignore[arg-type]
    except ZeroDivisionError:
        return float("inf")


OPS: dict[str, Callable[[Any, Any], NumLike]] = {
    "add": operator.add,
    "subtract": operator.sub,
    "multiply": operator.mul,
    "mean": mean,
    "divide": operator.truediv,
    "floor": operator.floordiv,
    "modulo": operator.mod,
    "power": operator.pow,
}


def parser(
    num: Decimal, extraction: object, objconf: SimpleMathObjconf, **kwargs: object
) -> NumLike:
    """
    Applies the configured operation to ``num`` and ``other``.

    Args:

        num: The first operand, already cast to ``Decimal``.
        extraction: The extracted conf value. Unused.
        objconf: The module configuration, containing `op` and `other`.

    Returns:

        The result of ``op`` applied to ``num`` and ``other``.

    Raises:

        TypeError: If ``conf`` has no ``op`` or ``other`` key, or ``op`` is
            unsupported.

    Examples:

        >>> from meza.fntools import Objectify
        >>>
        >>> conf = {"op": "divide", "other": 4}
        >>> objconf = Objectify(conf)
        >>> parser(10, None, objconf)
        Decimal('2.5')

    """
    op: str = require_conf_key(objconf, "op", "simplemath")
    raw: object = require_conf_key(objconf, "other", "simplemath")

    if op not in OPS:
        raise TypeError(f"the 'simplemath' module got an unsupported op {op!r}")

    operation = OPS[op]
    other = cast_value(raw, type_=CastType.DECIMAL)
    return operation(num, other)


@processor(DEFAULTS, isasync=True, **OPTS)
def async_pipe(*args: Any, **kwargs: object) -> NumLike:
    """
    Asynchronously performs basic arithmetic on an item field.

    Both iterator and iterable sources are mapped over. See the FAQ's "How does a
    processor map over items?".

    Args:

        item (Item | Items): The entry, or stream of entries, to process.

        conf (dict): The module configuration.

            op (str): The operation, one of "add", "subtract", "multiply",
                "divide", "floor", "modulo", "power", "mean". Required.
            other (number): The second operand, cast to ``Decimal``. Required.

        context (Context): the run environment

    Kwargs:

        field (str): Item field holding the first operand, cast to
            ``Decimal`` (default: "content").

        assign (str): Field the result is assigned to. Ignored when ``emit`` is
            True (default: "simplemath").

        emit (bool): Whether to emit the result in place of the item rather than
            assign it. Overrides ``assign`` (default: False).

    Yields:

        - merged ``{Item, <assign>: <result>}`` when ``emit`` is False and item
          is given (default)
        - ``{<assign>: <result>}`` when ``emit`` is False and no item given
        - ``<result>`` when ``emit`` is True

    Raises:

        TypeError: If ``conf`` has no ``op`` or ``other`` key, or ``op`` is
            unsupported.

    Examples:

        >>> from riko import run
        >>>
        >>> async def main():
        ...     conf = {"op": "divide", "other": "5"}
        ...     result = async_pipe({"content": "10"}, conf=conf)
        ...     print((await anext(result))["simplemath"])
        >>>
        >>> run(main)
        2

    """
    return parser(*args, **kwargs)


@processor(DEFAULTS, **OPTS)
def pipe(*args: Any, **kwargs: object) -> NumLike:
    """
    Performs basic arithmetic on an item field.

    Both iterator and iterable sources are mapped over. See the FAQ's "How does a
    processor map over items?".

    Args:

        item (Item | Items): The entry, or stream of entries, to process.

        conf (dict): The module configuration.

            op (str): The operation, one of "add", "subtract", "multiply",
                "divide", "floor", "modulo", "power", "mean". Required.
            other (number): The second operand, cast to ``Decimal``. Required.

        context (Context): the run environment

    Kwargs:

        field (str): Item field holding the first operand, cast to
            ``Decimal`` (default: "content").

        assign (str): Field the result is assigned to. Ignored when ``emit`` is
            True (default: "simplemath").

        emit (bool): Whether to emit the result in place of the item rather than
            assign it. Overrides ``assign`` (default: False).

    Yields:

        - merged ``{Item, <assign>: <result>}`` when ``emit`` is False and item
          is given (default)
        - ``{<assign>: <result>}`` when ``emit`` is False and no item given
        - ``<result>`` when ``emit`` is True

    Raises:

        TypeError: If ``conf`` has no ``op`` or ``other`` key, or ``op`` is
            unsupported.

    Examples:

        >>> from decimal import Decimal
        >>>
        >>> conf = {"op": "divide", "other": "5"}
        >>> next(pipe({"content": "10"}, conf=conf))["simplemath"]
        Decimal('2')
        >>> kwargs = {"conf": conf, "field": "num", "assign": "result"}
        >>> next(pipe({"num": "10"}, **kwargs))["result"]
        Decimal('2')

    """
    return parser(*args, **kwargs)
